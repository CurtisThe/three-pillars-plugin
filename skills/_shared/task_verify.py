#!/usr/bin/env python3
"""task_verify.py — the mechanical per-task verdict on one attempt worktree.

design: local-implement-and-review (Behavior 5, design-audit-3 #1 #2 #4)

``check`` runs on an attempt opened by ``task_attempts.open_attempt``; first failure wins:

1. the dispatcher HEAD, the guard ref and both trees' ``dirty_outside`` match the
   ``open`` snapshots, else exit 2 (env-error, never auto-undone, carries ``recover``);
2. the attempt was not pushed (``pushed``: via ``refs/remotes``);
3. exactly one commit on the attempt branch (``no commit`` / ``N commits``), except on
   ``opus``: zero commits, a clean tree, named nodes green at base → PASS ``pre_exists``;
4. the attempt's porcelain is empty, untracked included (``uncommitted changes``); then
   its ignored files are deleted (``git clean -ffdX``, each logged ``ignored-removed``
   bar bytecode caches), so step 6 judges exactly the committed tree: an ignored
   implementation file is on disk but never in what ``land`` carries (A32); then HEAD
   is written over the worktree from a fresh index (A35), undoing any edit, deletion or
   mode change hidden from ``git status`` by index bits or stat data. The ``pre_exists``
   path scrubs and writes HEAD the same way before its run;
5. every changed path is listed (``unlisted file: <p>`` / ``design-dir touched: <p>``).
   On the ``opus`` rung, or for a row with ``unparsed_files``, unlisted paths are logged
   (``unlisted-logged``), not failed; a design-dir touch always fails;
6. the row's declared **Targets** pass: each node target, then each target file whole,
   judged per node by its ``--junitxml`` report (`junit_verdict`), never the exit code:
   ``red test``, ``red test (file-missing)``, or ``unverified test (<why>)`` (no or a
   malformed report, no rootdir it fits, a skip, an absent node or a file with no
   tests: the repo's config may deselect them); a runner that cannot start (rc 126/127)
   is exit 2 ``runner-unavailable``. A row without runnable Targets (missing, malformed or ``none``)
   is FAIL ``no oracle`` below ``opus`` and PASS ``unverified`` on ``opus``.

Then red-at-base is logged (``task_verify_red_base``). ``land`` merges a checked attempt
into the dispatcher and discards it. The CLI (``open``/``check``/``land``/``discard``/
``sweep``) prints JSON; attempt lifecycle lives in ``task_attempts``. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import junit_verdict  # noqa: E402 — in-repo, stdlib-only sibling
import task_attempts  # noqa: E402 — in-repo, stdlib-only sibling
import task_scope  # noqa: E402 — in-repo, stdlib-only sibling
import task_scratch_sweep  # noqa: E402 — in-repo, stdlib-only sibling
import task_verify_gate  # noqa: E402 — in-repo, stdlib-only sibling
import task_verify_red_base  # noqa: E402 — in-repo, stdlib-only sibling
from task_verify_load import CliError, load_attempt, task_row  # noqa: E402,F401 — CLI

RUNGS = ("local", "sonnet", "opus")
TAIL_CHARS = 4000


class _Fail(Exception):
    """A step failed: ``reason`` is the verdict's reason."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


_out = task_attempts._out


def _changed(adir: str, base: str) -> list[str]:
    rc, paths = _git_z(adir, "diff", "--name-only", "--no-renames", "-z", base, "HEAD")
    if rc:
        raise _EnvError(f"diff-unreadable (rc {rc})")
    return sorted(paths)


class _EnvError(_Fail):
    """A step-1 (or land) failure: exit 2, never auto-undone; carries ``recover``."""


def recover_command(attempt: dict) -> str:
    """The discard command an operator runs once the env-error is understood; the
    script path is absolute, so it works from a consumer repo's cwd."""
    return (f"python3 {shlex.quote(str(Path(__file__).resolve()))} discard "
            f"--attempt {shlex.quote(str(attempt.get('attempt_id')))}")


def _step_env(attempt: dict) -> None:
    """Step 1: the dispatcher and the guard ref are as ``open`` left them."""
    owner = str((attempt.get("owner") or {}).get("dispatcher_root") or "")
    dd = str(attempt.get("design_dir_rel") or "")
    snap = attempt.get("dirty_snapshot") or {}
    if _out(owner, "rev-parse", "HEAD") != attempt.get("dispatcher_head"):
        raise _EnvError("dispatcher moved")
    ref = attempt.get("guard_ref")
    if ref and task_attempts._resolve(owner, str(ref)) != attempt.get("guard_sha"):
        raise _EnvError("guard-ref moved")
    if task_scope.dirty_outside(owner, dd) != sorted(snap.get("dispatcher") or []):
        raise _EnvError("dispatcher dirtied")
    groot = attempt.get("guard_root")
    if groot and task_scope.dirty_outside(groot, dd) != sorted(snap.get("guard_root") or []):
        raise _EnvError("guard-root dirtied")


def _step_pushed(adir: str, attempt: dict) -> None:
    """Step 2: the attempt branch has a remote-tracking ref, or a ``refs/remotes`` ref
    that moved since ``open`` now contains one of the attempt's commits."""
    base, branch = str(attempt["base_sha"]), str(attempt.get("branch") or "")
    commits = _out(adir, "rev-list", f"{base}..HEAD").split()
    if not commits:
        return
    before = attempt.get("remotes_snapshot") or {}
    for ref, sha in task_attempts.remotes_snapshot(adir).items():
        if branch and ref.endswith("/" + branch):
            raise _Fail("pushed")
        if before.get(ref) == sha:
            continue
        for c in commits:
            if task_attempts._git(adir, "merge-base", "--is-ancestor", c, sha,
                                  check=False).returncode == 0:
                raise _Fail("pushed")


def _step_commits(adir: str, base: str) -> None:
    count = int(_out(adir, "rev-list", "--count", f"{base}..HEAD") or 0)
    if count == 0:
        raise _Fail("no commit")
    if count != 1:
        raise _Fail(f"{count} commits")


_CACHE_NAMES = {"__pycache__", ".pytest_cache"}


def _git_z(adir: str, *args: str) -> tuple[int, list[str]]:
    """``git -z`` output as paths; a name that is not UTF-8 survives (surrogateescape)."""
    done = subprocess.run(["git", "-C", adir, *args], capture_output=True, check=False,
                          env=task_scope._git_env())
    return done.returncode, [p.decode("utf-8", "surrogateescape")
                             for p in done.stdout.split(b"\0") if p]


def _materialize_head(adir: str) -> None:
    """Write every file of the attempt's HEAD commit over its worktree (A35), from a
    fresh index that holds no ``skip-worktree`` / ``assume-unchanged`` bit and no stat
    data. An edit, a deletion or a mode change hidden from ``git status`` by those bits,
    by ``core.ignoreStat`` or by a forged mtime is undone, and sparse checkout's absent
    paths are written, so step 6 runs on exactly the commit ``land`` carries. Gitlinks
    are L105's. A failure is exit 2 ``head-materialize-failed``: the tree is unknown."""
    with tempfile.TemporaryDirectory(prefix="tp-head-index-") as tmp:
        env = task_scope._git_env(GIT_INDEX_FILE=os.path.join(tmp, "index"))
        for args in (("read-tree", "HEAD"), ("checkout-index", "-a", "-f")):
            done = subprocess.run(["git", "-C", adir, *args], capture_output=True,
                                  check=False, env=env)
            if done.returncode:
                raise _EnvError(f"head-materialize-failed ({args[0]} rc {done.returncode})")


def _scrub_ignored(attempt: dict) -> list[str]:
    """Delete the attempt's ignored files (A32) → one ``ignored-removed`` note per path,
    bytecode caches unnamed. Only in place (A33): ``attempt_dir`` must pass
    ``task_attempts.removable`` and be its own git toplevel, else exit 2
    ``ignored-scrub-refused``. A scrub that fails is exit 2: the tree is unknown."""
    adir = str(attempt["attempt_dir"])
    top = task_attempts._git(adir, "rev-parse", "--show-toplevel", check=False)
    if not task_attempts.removable(attempt) or top.returncode or (
            os.path.realpath(top.stdout.strip()) != os.path.realpath(adir)):
        raise _EnvError("ignored-scrub-refused (attempt dir not in place)")
    rc, paths = _git_z(adir, "ls-files", "-z", "--others", "--ignored",
                       "--exclude-standard", "--directory")
    done = task_attempts._git(adir, "clean", "-ffdX", "-q", check=False)
    if rc or done.returncode:
        raise _EnvError(f"ignored-scrub-failed (rc {rc or done.returncode})")
    return [f"ignored-removed: {p}" for p in paths
            if not _CACHE_NAMES & set(Path(p).parts) and not p.endswith((".pyc", ".pyo"))]


def _step_scope(changed: list[str], row: dict, design_dir_rel: str, rung: str) -> list[str]:
    """Step 5 → the ``unlisted-logged`` notes (the lenient policy), or raises."""
    lenient = rung == "opus" or bool(row.get("unparsed_files"))
    # The worker writes the resolved test files too; plans list only the implementation.
    listed = {*(row.get("files") or []), *task_scope.row_test_paths(row)}
    logged = []
    for path in changed:
        cls = task_scope.classify_path(path, listed, design_dir_rel)
        if cls == "design-dir":
            raise _Fail(f"design-dir touched: {path}")
        if cls == "unlisted":
            if not lenient:
                raise _Fail(f"unlisted file: {path}")
            logged.append(f"unlisted-logged: {path}")
    return logged


def run(argv: list[str], cwd: str, timeout: int) -> tuple[int | None, str]:
    """Run ``argv`` in ``cwd`` → ``(rc, output tail)``; rc None on timeout, 127/126 when
    the runner is missing or not executable. Never writes bytecode into the attempt."""
    rc, tail, _timed_out = task_scope.run_capture(
        argv, cwd, timeout, env=task_scope._git_env(PYTHONDONTWRITEBYTECODE="1"),
        tail_chars=TAIL_CHARS)
    return rc, tail


def runnable(row: dict, runner: str | None) -> bool:
    """Step 6 applies: declared, runnable **Targets** and a runner."""
    test = row.get("test") or {}
    return bool(runner) and bool(task_scope.row_test_paths(row)) and test.get("kind") in (
        "pytest-node", "pytest-file")


def _step_tests(adir: str, row: dict, runner: str, timeout: int, res: dict) -> None:
    """Every declared node target, then every declared target file whole."""
    nodes = [s for s in row["test"].get("specs") or [] if "::" in s]
    for target in dict.fromkeys([*nodes, *task_scope.row_test_paths(row)]):
        def go(extra, targets):
            argv = task_scope.runner_argv(runner, [*targets, *extra])
            res["commands"].append(argv)
            return run(argv, adir, timeout)
        (rc, tail), (kind, why) = junit_verdict.run_judged(go, target, adir)
        res["test_output_tail"] = tail
        if rc is None:
            raise _Fail("red test (timeout)")
        if rc in task_scope.RUNNER_BROKEN_RCS:  # the runner never started: not the task's
            raise _EnvError(f"runner-unavailable (rc {rc})")
        if kind != "pass":  # red, missing, or no / a malformed report, a skip: never a pass
            raise _Fail({"red": "red test", "missing": f"red test ({why})"}.get(
                kind, f"unverified test ({why})"))


def check(attempt: dict, row: dict, runner: str | None, *, rung: str,
          timeout: int = 600) -> dict:
    """The verdict for one attempt → ``{task_id, verdict, reason, test_output_tail,
    changed_files, red_at_base, attempt_branch, unverified, logged, commands}``; it is
    recorded with the checked sha, which ``land`` requires (``task_verify_gate``)."""
    if rung not in RUNGS:
        raise ValueError(f"unknown rung {rung!r}; expected one of {RUNGS}")
    return task_verify_gate.checked(attempt, rung,
                                    lambda: _verdict(attempt, row, runner, rung, timeout))


def _pre_exists(attempt: dict, base: str, row: dict, runner, rung: str, timeout: int,
                res: dict) -> bool:
    """PASS ``pre_exists`` only as ``task_verify_gate.pre_exists_eligible`` allows, with zero
    commits, a clean tree and the named nodes green at base; else ``no commit``."""
    adir = str(attempt["attempt_dir"])
    if not task_verify_gate.pre_exists_eligible(row, rung, runnable(row, runner)) or _out(
            adir, "rev-list", "--count", f"{base}..HEAD") != "0" or _out(
            adir, "status", "--porcelain", "-uall"):
        return False
    res["logged"] = _scrub_ignored(attempt)
    _materialize_head(adir)
    try:
        _step_tests(adir, row, str(runner), timeout, res)
    except _EnvError:
        raise
    except _Fail as exc:
        raise _Fail("no commit") from exc
    res.update(verdict="PASS", exit=0, pre_exists=True, red_at_base="n/a",
               reason="pre-exists: no commit, the Test is green at base")
    return True


def _verdict(attempt: dict, row: dict, runner: str | None, rung: str, timeout: int) -> dict:
    adir, base = str(attempt["attempt_dir"]), str(attempt["base_sha"])
    res = {"task_id": attempt.get("task_id"), "verdict": "FAIL", "reason": "",
           "test_output_tail": "", "changed_files": [], "red_at_base": None,
           "attempt_branch": attempt.get("branch"), "unverified": False, "logged": [],
           "commands": [], "exit": 1, "pre_exists": False}
    try:
        _step_env(attempt)
        _step_pushed(adir, attempt)
        if _pre_exists(attempt, base, row, runner, rung, timeout, res):
            return res
        _step_commits(adir, base)
        if _out(adir, "status", "--porcelain", "-uall"):  # step 4
            raise _Fail("uncommitted changes")
        scrubbed = _scrub_ignored(attempt)
        _materialize_head(adir)
        res["changed_files"] = _changed(adir, base)
        res["logged"] = scrubbed + _step_scope(res["changed_files"], row,
                                               str(attempt.get("design_dir_rel") or ""), rung)
        if runnable(row, runner):
            _step_tests(adir, row, str(runner), timeout, res)
        elif rung != "opus":  # the cheap tier runs only behind a mechanical oracle
            raise _Fail("no oracle (a cheap rung needs a runnable Test)")
        else:
            res["unverified"] = True  # the ladder hears PASS-unverified
    except _EnvError as exc:
        res.update(verdict="env-error", reason=exc.reason, exit=2,
                   recover=recover_command(attempt))
        return res
    except _Fail as exc:
        res["reason"] = exc.reason
        return res
    res.update(verdict="PASS", reason="; ".join(res["logged"]), exit=0, red_at_base="n/a")
    if not res["unverified"]:  # logged evidence, never gating
        res.update(task_verify_red_base.logged(attempt, row, str(runner), timeout, run=run))
    return res


def _land_into(owner: str, attempt: dict, sha: str) -> str:
    """Merge the attempt into the dispatcher → the method; raises ``_EnvError``."""
    base, head = str(attempt["base_sha"]), _out(owner, "rev-parse", "HEAD")
    if head == base:
        res = task_attempts._git(owner, "merge", "--ff-only", "-q", sha, check=False)
        if res.returncode:
            raise _EnvError("land-failed: " + (res.stderr.strip() or "merge --ff-only"))
        return "ff"
    if task_attempts._git(owner, "merge-base", "--is-ancestor", base, head,
                          check=False).returncode:
        raise _EnvError("dispatcher diverged")
    res = task_attempts._git(owner, "cherry-pick", sha, check=False)
    if res.returncode:
        task_attempts._git(owner, "cherry-pick", "--abort", check=False)
        raise _EnvError("land-conflict")
    return "cherry-pick"


def land(attempt: dict) -> dict:
    """Land a checked attempt's one commit in the dispatcher, then ``discard`` it.

    The record goes ``landing`` with ``commit_sha`` first (so ``sweep`` reports a crash
    after the land). ``merge --ff-only`` when the dispatcher HEAD is still ``base_sha``,
    else ``cherry-pick`` (HEAD moved only by this batch's disjoint landings). A conflict
    aborts → exit 2 ``land-conflict``; the attempt is kept for the ``recover`` command.
    → ``{attempt_id, task_id, exit, method, sha, reason}``.
    """
    owner = str(attempt["owner"]["dispatcher_root"])
    out = {"attempt_id": attempt.get("attempt_id"), "task_id": attempt.get("task_id"),
           "exit": 0, "method": None, "sha": None, "reason": ""}
    sha = task_verify_gate.head_of(attempt)
    refusal = task_verify_gate.land_refusal(attempt, sha)
    if refusal:  # only a PASS check of this exact commit lands
        out.update(exit=2, reason=refusal, recover=recover_command(attempt))
        return out
    if sha == attempt["base_sha"]:  # a pre-exists PASS: nothing to land
        out.update(method="none", sha=_out(owner, "rev-parse", "HEAD"))
        task_attempts.discard(attempt, root=owner)
        return out
    rec = {**attempt, "status": "landing", "commit_sha": sha}
    task_attempts._write_record(rec)
    try:
        out["method"] = _land_into(owner, attempt, sha)
    except _EnvError as exc:
        rec.pop("commit_sha")
        task_attempts._write_record({**rec, "status": "open"})
        out.update(exit=2, reason=exc.reason, recover=recover_command(attempt))
        return out
    out["sha"] = _out(owner, "rev-parse", "HEAD")
    task_attempts.discard(rec, root=owner)
    return out


# --- CLI (loaders in task_verify_load) -----------------------------------------------

def _cmd(args) -> tuple[int, dict]:
    root = args.root
    if args.cmd == "open":
        try:
            return 0, task_attempts.open_attempt(root, args.task, args.design_dir,
                                                 guard_ref=args.guard_ref)
        except task_attempts.DirtyTree as exc:
            raise CliError("dirty-tree", paths=exc.paths, reason=str(exc)) from exc
    if args.cmd == "sweep":  # attempts, then the re-run / red-at-base scratch
        slug = task_attempts.slug_of(args.design_dir)
        return 0, {**task_attempts.sweep(root, slug),
                   "scratch": task_scratch_sweep.sweep(root, slug)}
    attempt = load_attempt(root, args.attempt)
    if args.cmd == "discard":
        return 0, task_attempts.discard(attempt)
    if args.cmd == "land":
        out = land(attempt)
        return out["exit"], out
    runner, _why = task_scope.resolve_runner(attempt["attempt_dir"], args.test_cmd)
    res = check(attempt, task_row(attempt, args.plan, args.phase, root), runner,
                rung=args.rung)
    return res["exit"], res


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Per-task attempt worktrees and verdicts.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("open", "check", "land", "discard", "sweep"):
        sp = sub.add_parser(name)
        sp.add_argument("--root", default=".", help="dispatcher root (default: .)")
        if name == "open":
            sp.add_argument("--task", required=True)
            sp.add_argument("--guard-ref")
        if name in ("open", "sweep"):
            sp.add_argument("--design-dir", required=True)
        else:
            sp.add_argument("--attempt", required=True)
        if name == "check":
            sp.add_argument("--plan", required=True)
            sp.add_argument("--phase", type=int, required=True)
            sp.add_argument("--rung", required=True, choices=RUNGS)
            sp.add_argument("--test-cmd")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        code, payload = _cmd(args)
    except CliError as exc:
        code, payload = 2, exc.payload
    except subprocess.CalledProcessError as exc:
        code, payload = 2, {"error": "git", "detail": (exc.stderr or str(exc)).strip()}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
