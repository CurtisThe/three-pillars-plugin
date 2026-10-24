#!/usr/bin/env python3
"""docs_compile_publish.py — post-merge: compile the pending fragments onto the rolling `tp/docs-compile` PR.

design: living-doc-fragments, Task 1.14 (§Interfaces docs_compile_publish, §Forge behaviour).
``run(repo_root, *, base, prs=(), runner=None, forge_runner=None) -> list[str]``: open a scratch checkout
(``wt_root`` role ``compile``) on ``origin/tp/docs-compile`` when it exists, else on ``origin/<base>``; from an
existing open-PR branch tip run ``number_issues.py --commit`` (branch-side renumber) and merge ``origin/<base>``
(a conflict aborts); a landed branch instead restarts from the base tip (an ``-s ours`` merge keeps the push
a fast-forward); ``docs_compile.compile_all`` with the ``--pr SLUG=N`` pairs (a refusal pushes nothing; kept
fragments are named); plain ``git push origin tp/docs-compile`` (never forced); then the PR through
``forge.py pr-create``. The previous compile PR is *landed* when the branch is an ancestor of
``origin/<base>`` or every fragment the branch deleted is also gone on the base (so a squash landing counts);
landed or no branch opens a new PR, else the push refreshes the open one. Gitea re-runs ``pr-create`` after
every push. With no ``origin`` the compile is committed on a local ``tp/docs-compile``. Fail-open: always
exit 0, one ``docs-compile:`` line per outcome.

CLI: ``docs_compile_publish.py run --base B [--pr SLUG=N]… [--repo-root R] [--json]``. Stdlib only.
``runner(argv, cwd)`` runs git (and number_issues); ``forge_runner(argv, cwd) -> (rc, stdout, stderr)``
runs ``forge.py``; both exist so tests can record and stub them.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import docs_compile  # noqa: E402
import number_issues  # noqa: E402
import pending_changes  # noqa: E402
import wt_root  # noqa: E402

BRANCH = "tp/docs-compile"
SLUG = "docs-compile"
TITLE = "docs: compile living-doc fragments"
CHANGES = pending_changes.CHANGES_DIR + "/"


def _sh(argv, cwd):
    return subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True)


def _forge(argv, cwd):
    out = subprocess.run([sys.executable, str(_SHARED / "forge.py"), *argv], cwd=str(cwd),
                         capture_output=True, text=True)
    return out.returncode, out.stdout, out.stderr


class _Ctx:
    """The git runner, scratch checkout and say() shared by the steps of one publish."""

    def __init__(self, root, runner, emit):
        self.root, self.runner, self.emit, self.lines, self.cwd = root, runner, emit, [], root

    def git(self, *args, cwd=None):
        return self.runner(["git", *args], cwd or self.cwd)

    def out(self, *args, cwd=None) -> str:
        return self.git(*args, cwd=cwd).stdout.strip()

    def say(self, msg: str) -> None:
        line = f"docs-compile: {msg}"
        self.lines.append(line)
        self.emit(line)

    def has(self, ref: str) -> bool:
        return self.git("rev-parse", "--verify", "--quiet", ref + "^{commit}", cwd=self.root).returncode == 0

    def sha(self, ref: str) -> str:
        return self.out("rev-parse", ref + "^{commit}")


def _landed(c: _Ctx, base_ref: str, branch_ref: str) -> bool:
    """The previous compile PR landed: branch is an ancestor of the base, or its deleted fragments are gone."""
    if c.git("merge-base", "--is-ancestor", branch_ref, base_ref).returncode == 0:
        return True
    merge_base = c.out("merge-base", base_ref, branch_ref)
    gone = c.out("diff", "--name-only", "--diff-filter=D", merge_base, branch_ref, "--", CHANGES).split()
    still = set(c.out("ls-tree", "-r", "--name-only", base_ref, "--", CHANGES).split())
    return bool(gone) and not (set(gone) & still)


def _sync_with_base(c: _Ctx, base_ref: str) -> bool:
    """Renumber the branch's own IDs, then merge the base. False (and a line) on a conflict."""
    num = c.runner([sys.executable, str(_SHARED / "number_issues.py"), "--repo", str(c.cwd),
                    "--base", base_ref, "--commit"], c.cwd)
    if num.returncode != 0:
        c.say(f"number_issues exited {num.returncode}: {num.stderr.strip()}")
    # no-renames: a base that deleted one fragment and added a similar one reads as a rename (a
    # rename/delete conflict); the ort strategy still reports it on git 2.43, so recursive is named.
    if c.git("merge", "--no-edit", "-s", "recursive", "-X", "no-renames", base_ref).returncode == 0:
        return True
    files = c.out("diff", "--name-only", "--diff-filter=U")
    c.git("merge", "--abort")
    c.say(f"base merge conflicts on {', '.join(files.split()) or '(unknown)'}; "
          f"run /tp-merge-from-main on {BRANCH}")
    return False


def _restart_on_base(c: _Ctx, base_ref: str, branch_ref: str) -> str:
    """A landed branch restarts from the base tip; returns the restart sha (no compile on top = nothing to do).

    Its folded content is already on the base, so a renumber of its tip would read the base's copy of
    its own IDs as a collision. An ``-s ours`` merge of the old tip keeps the base tree and makes the
    next plain push a fast-forward.
    """
    c.git("reset", "-q", "--hard", base_ref)
    c.git("merge", "-q", "--no-edit", "-s", "ours", branch_ref)
    return c.sha("HEAD")


def _compile(c: _Ctx, base_ref: str, prs: dict):
    """compile_all with commit; prints its outcome lines. Returns the result, or None to stop (nothing pushed)."""
    try:
        result = docs_compile.compile_all(c.cwd, base_ref=base_ref, prs=prs, commit=True)
    except (docs_compile.DirtyTree, docs_compile.NumberIssuesError, ValueError) as exc:
        c.say(f"compile failed: {exc}")
        return None
    for slug, reason in result.conflicts:
        c.say(f"{slug}: {reason}")
    for rel, chars, hard in result.over_cap:
        c.say(f"{rel} over hard cap ({chars} > {hard}); run /tp-docs-update --diet")
    for issue_id in result.duplicates:
        c.say(f"duplicate issue ID {issue_id}")
    for kind, signature in result.refused:
        c.say(f"dropped {kind}: {signature}")
    if result.refused or result.duplicates or result.over_cap:
        c.say("compile refused; nothing pushed")
        return None
    if result.conflicts:
        c.say("kept " + ", ".join(slug for slug, _ in result.conflicts))
    for slug in result.folded:
        if slug not in prs:
            c.say(f"PR number unknown for {slug}")
    return result


def _kind(forge_runner, root) -> str:
    try:
        rc, out, _err = forge_runner(["resolve"], root)
        return str(json.loads(out).get("kind", "other")) if rc == 0 else "other"
    except (ValueError, OSError, AttributeError):  # tp-allow-fail-open: an unresolvable forge is "other"
        return "other"


def _open_pr(c: _Ctx, forge_runner, base: str, folded: list) -> None:
    body = "Folded fragments: " + (", ".join(folded) if folded else "(none; base merged into the branch)")
    rc, out, err = forge_runner(["pr-create", "--context", "autonomous", "--", "--base", base, "--head",
                                 BRANCH, "--title", TITLE, "--body", body], c.root)
    if rc == 0:
        c.say(f"PR {out.strip() or 'opened'}")
    elif rc == 3:
        c.say(f"bot-auth-unavailable: {err.strip()}")
    else:
        url = out.strip() if rc == 4 else ""
        if not url:
            url = forge_runner(["compare-url", "--base", base, "--head", BRANCH], c.root)[1].strip()
        c.say(f"open a PR from {BRANCH}: {url}")


def _publish(c: _Ctx, base: str, pr_items, forge_runner) -> None:
    prs = docs_compile._parse_prs(list(pr_items))
    remote = c.git("remote", "get-url", "origin", cwd=c.root).returncode == 0
    if remote and c.git("fetch", "-q", "origin", cwd=c.root).returncode != 0:
        c.say("fetch from origin failed; nothing compiled")
        return
    base_ref, remote_branch = (f"origin/{base}", f"origin/{BRANCH}") if remote else (base, BRANCH)
    if not c.has(base_ref):
        c.say(f"base {base_ref} not found; nothing compiled")
        return
    branch_ref = remote_branch if c.has(remote_branch) else None
    prev = c.sha(branch_ref or base_ref)
    path = wt_root.open_checkout(c.root, "compile", SLUG, branch_ref or base_ref)
    c.cwd = path
    try:
        if c.git("switch", "-q", "-C", BRANCH).returncode != 0:
            c.say(f"cannot switch to {BRANCH}")
            return
        new_pr = branch_ref is None or _landed(c, base_ref, branch_ref)
        if branch_ref and new_pr:
            prev = _restart_on_base(c, base_ref, branch_ref)
        elif branch_ref and not _sync_with_base(c, base_ref):
            return
        result = _compile(c, base_ref, prs)
        head = c.sha("HEAD")
        if result is None or head in (prev, c.sha(base_ref)):
            if result is not None:
                c.say("nothing to compile")
            return
        if not remote:
            c.say(f"committed on {BRANCH}; run: git merge {BRANCH}")
            return
        pushed = c.git("push", "origin", BRANCH)
        if pushed.returncode != 0:
            c.say(f"push failed: {pushed.stderr.strip()}")
            return
        if new_pr or _kind(forge_runner, c.root) == "gitea":
            _open_pr(c, forge_runner, base, result.folded)
        else:
            c.say(f"updated {BRANCH}; its open PR is refreshed")
    finally:
        c.cwd = c.root
        wt_root.reap(c.root, "compile", SLUG)


@contextlib.contextmanager
def _hooks_off(root):
    """Every git call of one publish runs with ``core.hooksPath`` set to a fresh empty dir.

    The scratch checkout holds the unreviewed ``origin/tp/docs-compile`` tip, and an installed hook
    (e.g. a pre-commit local hook that runs a script of the checked-out tree) would execute that
    tip's scripts. The compile is verified in-process by the operator's own modules and its PR is reviewed
    before merge, so this machine-generated commit needs no commit-time hook. It is scoped to this one
    publish (the env is restored after); it is not a ``--no-verify`` on any operator commit.
    ``GIT_CONFIG_COUNT`` covers the runner's git calls; ``number_issues`` scrubs that from its git env, so
    its ``_run_git`` (also docs_compile's commit) reads ``HOOKS_OFF_ENV``.
    """
    empty = os.path.join(wt_root.ensure_parent(root, SLUG), f"no-hooks-{uuid.uuid4().hex[:8]}")
    os.mkdir(empty)
    n = int(os.environ.get("GIT_CONFIG_COUNT") or 0)
    keys = ("GIT_CONFIG_COUNT", f"GIT_CONFIG_KEY_{n}", f"GIT_CONFIG_VALUE_{n}", number_issues.HOOKS_OFF_ENV)
    saved = {k: os.environ.get(k) for k in keys}
    os.environ.update(zip(keys, (str(n + 1), "core.hooksPath", empty, empty)))
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        with contextlib.suppress(OSError):
            os.rmdir(empty)


def run(repo_root, *, base: str, prs=(), runner=None, forge_runner=None, emit=print) -> list:
    """Publish the compile; returns the ``docs-compile:`` lines (also emitted). Never raises."""
    c = _Ctx(os.path.realpath(str(repo_root)), runner or _sh, emit)
    try:
        with _hooks_off(c.root):
            _publish(c, base, prs, forge_runner or _forge)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:  # tp-allow-fail-open: post-merge publish never blocks teardown
        c.say(f"failed: {exc}")
    return c.lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="docs_compile_publish.py", description="publish the docs compile")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--base", required=True)
    p.add_argument("--pr", action="append", default=[])
    p.add_argument("--repo-root", default=".")
    p.add_argument("--json", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit:  # tp-allow-fail-open: a usage error still exits 0 with one line
        print("docs-compile: usage: run --base B [--pr SLUG=N]... [--repo-root R] [--json]")
        return 0
    lines = run(args.repo_root, base=args.base, prs=args.pr, emit=(lambda _l: None) if args.json else print)
    if args.json:
        print(json.dumps({"lines": lines}))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
