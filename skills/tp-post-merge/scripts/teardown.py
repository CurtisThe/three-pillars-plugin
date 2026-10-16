"""teardown.py — /tp-post-merge teardown steps c, d, e and h as plain code.

design: cheap-tier-offload (Task 5.1; slots doc §Phase 5, D8, D10). The `runbook` slot
runs this with no model. It refuses, deleting nothing, unless `verify_merged` shows the
PR merged. Then: remove the `tp/<slug>` worktree (c), `git branch -D` (d), `git push
origin --delete` (e, fail-open) and drop the slug from `.claude/last-design`, deleting
an emptied file (h). Steps f and g stay on `gc_candidate_branches.py --apply`.

    teardown.py --slug S --base B [--root R]  # {"steps": {...}, "verify_argv": [...]}
    teardown.py --check --slug S [--root R]   # {"residue": [...]}; the oracle's argv
    teardown.py --unlanded --slug S [--root R]  # {"unlanded": [...]}; the inline-path gate

Exits 0 ran / clean, 1 refused (not merged) / residue / unlanded, 2 usage, 3 unobservable
(a `--check` or `--unlanded` whose listing failed prints {"error": ...}, never an empty
result).
Steps are fail-open.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import verify_merged as _vm  # noqa: E402

SLUG_RE = re.compile(r"^[a-z0-9-]+$")
MRU = Path(".claude") / "last-design"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, timeout=120)


def _done(result: subprocess.CompletedProcess, ok: str, bad: str) -> str:
    """`ok` on exit 0, else `bad` plus the last line git printed."""
    lines = (result.stderr or result.stdout or "").strip().splitlines()
    return ok if result.returncode == 0 else bad + (lines or [f"exit {result.returncode}"])[-1]


def verify_merged(root: Path, slug: str, base: str, gh_cmd: str = "gh") -> bool:
    """The step-4 gate: archive on `origin/<base>`, `gh` MERGED, or merged by merge commit."""
    return bool(_vm.evaluate(str(root), slug, base, gh_cmd=gh_cmd)["merged"])


def merge_report(root: Path, slug: str, base: str, gh_cmd: str = "gh") -> dict:
    """The full verdict (every check and the remedy); used only on the refusal path."""
    return _vm.evaluate(str(root), slug, base, gh_cmd=gh_cmd)


class Unobservable(RuntimeError):
    """A git listing failed, so the teardown state cannot be read."""


def _listing(root: Path, *args: str) -> str:
    """git's stdout; raises Unobservable on a nonzero exit or a git that cannot run."""
    try:
        result = _git(Path(root), *args)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Unobservable(f"git {args[0]} did not run: {exc}") from exc
    if result.returncode != 0:
        why = (result.stderr or result.stdout or "").strip().splitlines()
        raise Unobservable(f"git {args[0]} exited {result.returncode}: "
                           + (why[-1] if why else "no output"))
    return result.stdout


def worktree_paths(root: Path, slug: str) -> list[str]:
    """Paths of every worktree that has `tp/<slug>` checked out (Unobservable on a
    failed listing)."""
    paths, current = [], None
    for line in _listing(root, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            current = line[len("worktree "):]
        elif line == f"branch refs/heads/tp/{slug}" and current:
            paths.append(current)
    return paths


def _branch_listed(root: Path, slug: str) -> bool:
    return bool(_listing(root, "branch", "--list", f"tp/{slug}").strip())


def unlanded_commits(root: Path, slug: str) -> list[str]:
    """SHAs reachable from `tp/<slug>` but from no remote-tracking ref (git-only, so
    Gitea behaves like GitHub); `[]` when the local branch is absent."""
    ref = f"refs/heads/tp/{slug}"
    try:
        present = _git(Path(root), "rev-parse", "--verify", "--quiet", ref).returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        raise Unobservable(f"git rev-parse did not run: {exc}") from exc
    if not present:
        return []
    return _listing(root, "rev-list", ref, "--not", "--remotes").split()


def _unlanded_refusal(root: Path, slug: str, base: str = "the base") -> dict | None:
    """A refusal dict when `tp/<slug>` holds commits no remote has (or the listing
    fails); None when nothing would be lost. Pushing alone does not land them."""
    remedy = (f"land these commits on {base} (e.g. a follow-up commit/PR carrying the "
              f"archived log), or confirm they are already on {base}, then delete the "
              "branch by hand")
    try:
        unlanded = unlanded_commits(root, slug)
    except Unobservable as exc:
        return {"refused": f"tp/{slug} unlanded commits unobservable ({exc}); "
                           "nothing deleted", "unlanded": [], "remedy": remedy}
    if not unlanded:
        return None
    return {"refused": f"tp/{slug} holds {len(unlanded)} commit(s) on no remote-tracking "
                       "ref; nothing deleted", "unlanded": unlanded, "remedy": remedy}


def _mru_holds(root: Path, slug: str) -> bool:
    path = root / MRU
    return path.is_file() and slug in {
        line.strip() for line in path.read_text(encoding="utf-8").splitlines()}


def remove_worktrees(root: Path, slug: str) -> str:
    """Step c. Never removes the worktree the teardown runs from."""
    try:
        paths = worktree_paths(root, slug)
    except Unobservable as exc:
        return f"failed: {exc}"
    out = [f"failed {path}: is the teardown root" if Path(path).resolve() == root.resolve()
           else _done(_git(root, "worktree", "remove", path), f"removed {path}",
                      f"failed {path}: ")
           for path in paths]
    return "; ".join(out) or "none found"


def delete_local_branch(root: Path, slug: str) -> str:
    """Step d: always `-D`; the merge was verified before this runs."""
    try:
        listed = _branch_listed(root, slug)
    except Unobservable as exc:
        return f"failed: {exc}"
    return (_done(_git(root, "branch", "-D", f"tp/{slug}"), "deleted", "failed: ")
            if listed else "not present")


def delete_remote_branch(root: Path, slug: str) -> str:
    """Step e, fail-open: an already-deleted remote branch is not an error."""
    return _done(_git(root, "push", "origin", "--delete", f"tp/{slug}"), "deleted",
                 "not deleted (fail-open): ")


def clear_mru(root: Path, slug: str) -> str:
    """Step h: drop the slug's line; delete the file when nothing is left."""
    if not _mru_holds(root, slug):
        return "not present"
    path = root / MRU
    keep = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() != slug]
    if any(ln.strip() for ln in keep):
        path.write_text("\n".join(keep) + "\n", encoding="utf-8")
    else:
        path.unlink()
    return "cleared"


def _sweep_scratch() -> None:
    """design: scratch-reaper (Task 1.2). Sweep the framework's own scratch leftovers.

    Fail-open: a missing script, a timeout or a nonzero exit is one stderr line and
    never changes the teardown result. On a completed run the reaper's own stderr
    lines and its last stdout line (the summary) go to this process's stderr, each
    prefixed `teardown: `, so the operator sees them while stdout stays clean JSON.
    """
    script = Path(__file__).resolve().parents[2] / "_shared" / "scratch_reap.py"
    try:
        result = subprocess.run(["python3", str(script)], capture_output=True,
                                text=True, timeout=60)
        if result.returncode != 0:
            why = (result.stderr or result.stdout or "").strip().splitlines()
            print("teardown: scratch sweep failed (fail-open): "
                  + (why or [f"exit {result.returncode}"])[-1], file=sys.stderr)
        else:
            for line in (result.stderr or "").strip().splitlines():
                print(f"teardown: {line}", file=sys.stderr)
            summary = (result.stdout or "").strip().splitlines()
            if summary:
                print(f"teardown: {summary[-1]}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 — the sweep is fail-open by design
        print(f"teardown: scratch sweep failed (fail-open): {exc}", file=sys.stderr)


def teardown(root: Path, slug: str, base: str) -> dict | None:
    """`{steps, verify_argv}`, or None (nothing touched) when the merge is unverified."""
    if not verify_merged(root, slug, base):
        return None
    refusal = _unlanded_refusal(root, slug, base)
    if refusal:
        return refusal
    steps = {"c_worktree": remove_worktrees(root, slug),
             "d_local_branch": delete_local_branch(root, slug),
             "e_remote_branch": delete_remote_branch(root, slug),
             "h_mru": clear_mru(root, slug)}
    argv = ["python3", str(Path(__file__).resolve()), "--check", "--slug", slug,
            "--root", str(root.resolve())]
    try:
        _sweep_scratch()
    except Exception as exc:  # noqa: BLE001 — the sweep never changes the result
        print(f"teardown: scratch sweep failed (fail-open): {exc}", file=sys.stderr)
    return {"steps": steps, "verify_argv": argv}


def residue(root: Path, slug: str) -> list[str]:
    """What a finished teardown must not leave behind; empty means clean. Raises
    Unobservable when git cannot list the root (three outcomes: clean, residue, error)."""
    out = [f"worktree {path} holds tp/{slug}" for path in worktree_paths(root, slug)]
    out += [f"branch tp/{slug} still listed"] if _branch_listed(root, slug) else []
    return out + ([f"{MRU.as_posix()} holds {slug}"] if _mru_holds(root, slug) else [])


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="/tp-post-merge teardown c, d, e, h")
    for flag in ("--slug", "--base", "--root"):
        parser.add_argument(flag)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--unlanded", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code in (0, None) else 2
    if not SLUG_RE.match(args.slug or "") or not (args.check or args.unlanded or args.base):
        print("teardown.py: needs --slug [a-z0-9-]+, and --base unless --check/--unlanded",
              file=sys.stderr)
        return 2
    root = Path(args.root or ".")
    if args.unlanded:
        try:
            found = unlanded_commits(root, args.slug)
        except Unobservable as exc:
            print(json.dumps({"error": str(exc)}))
            return 3
        print(json.dumps({"unlanded": found}))
        return int(bool(found))
    if args.check:
        try:
            found = residue(root, args.slug)
        except Unobservable as exc:
            print(json.dumps({"error": str(exc)}))
            return 3
        print(json.dumps({"residue": found}))
        return int(bool(found))
    result = teardown(root, args.slug, args.base)
    if result is None:
        report = merge_report(root, args.slug, args.base)
        result = {"refused": f"tp/{args.slug} is not verified merged into {args.base}; "
                             "nothing deleted",
                  "checks": report["checks"], "remedy": report["remedy"]}
    print(json.dumps(result))
    return 0 if "steps" in result else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
