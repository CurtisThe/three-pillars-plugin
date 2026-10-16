#!/usr/bin/env python3
"""cheap_fix.py — the `pr_fix_reproducer` cheap-tier slot of /tp-pr-fix step 5.

design: cheap-tier-offload (Task 6.3). A cheap fix counts only when proved in a detached
scratch worktree before anything reaches the fix worktree. The scratch lives at
`<repo>/.tp-scratch/cheap-fix-<id>/r1` (`SCRATCH_DIR`; the Scratch rule of
cheap-dispatch.md): in the repo, so a project-scoped drafter can write it, and gitignored,
so the fix worktree stays clean; `scratch` refuses when the dir is not ignored. The finding is
`eligible` (structural, not a sentinel, a runnable reproducer that is REPRODUCED on
head); `adopt` escalates on an empty diff, on any file other than `finding["file"]` or a
new test file (an existing test or any conftest.py is out of scope, so a fix can never
weaken a test to pass), or when the `reproducer_fixed` oracle (the reproducer
passes, and `tests_argv` — pytest over the fix's own tests, never `ci.gate_command` —
exits 0) fails. On accept it applies exactly that one diff, unstaged,
to the fix worktree; `fix_round` still makes the round's one commit. The scratch is
always removed (`discard`: `round_scratch.safe_remove`, then `git worktree prune`;
idempotent, and a refused remove never replaces the verdict).

The drafter's cwd is the fix worktree, so its write scope is guarded, not only
instructed: `scratch` snapshots the fix worktree (`live_tree_guard`, beside `r1`), and
`adopt` first escalates `drafter-wrote-live-tree` on any change there since, undoing
only those paths (tracked files restored, new untracked files removed). An accepted
diff is the site's own change, so `adopt` re-baselines every other pending scratch's
snapshot on the files it applied (`live_tree_guard.rebase`); a later adopt then never
undoes it or blames its drafter. A snapshot that cannot be re-baselined is dropped, so
that adopt escalates `live-tree unobservable` instead of reverting the fix.

The CLI is `cheap_fix_cli.py`. Stdlib-only; no model is called here, and
`fix_round.py` is not touched.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

_SKILLS = Path(__file__).resolve().parent.parent.parent
for _dir in (_SKILLS / "_shared", _SKILLS / "tp-pr-iterate" / "scripts"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import cheap_oracle  # noqa: E402 — in-repo, stdlib-only sibling
import live_tree_guard  # noqa: E402 — in-repo, stdlib-only sibling
import reproduce  # noqa: E402 — tp-pr-iterate's reproducer runner
import scratch_root  # noqa: E402 — the one scratch base
import round_scratch  # noqa: E402 — safe_remove
from finding_class import is_sentinel, valid_reproducer  # noqa: E402

REPRODUCED = reproduce.REPRODUCED
SLOT = "pr_fix_reproducer"
SCRATCH_DIR = scratch_root.SCRATCH_DIR  # repo-relative and gitignored: cheap-dispatch.md, Scratch
PYTEST = [sys.executable or "python3", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
LIVE_TREE = "live-tree"  # the fix worktree's snapshot, in the owner dir beside r1
_PREFIXES = ("cheap-fix", "review-prep")  # owner-dir prefixes scratch may use


def _git(cwd, *args, data: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], input=data, capture_output=True,
                          timeout=300, check=False)


def eligible(finding: dict, outcome: str) -> bool:
    """True only for a structural finding with a reproducer that REPRODUCED on head."""
    return (isinstance(finding, dict) and finding.get("verdict") == "structural"
            and not is_sentinel(finding) and bool(finding.get("file"))
            and valid_reproducer(finding.get("reproducer")) and outcome == REPRODUCED)


def outcome_on_head(finding: dict, cwd) -> str:
    """The reproducer's outcome in `cwd`, a clean checkout of head."""
    with tempfile.TemporaryDirectory(prefix="tp-cheap-fix-repro-") as rd:
        _, downs = reproduce.run_reproducers([finding], cwd=str(cwd), scratch_dir=rd,
                                             round_dir_mode=False)
    return downs[0]["reason"] if downs else REPRODUCED


def scratch(repo, head, *, prefix: str = "cheap-fix") -> Path:
    """A detached worktree of `repo` at `head`, in a fresh `<prefix>-*` owner dir under
    SCRATCH_DIR. The default owner is `cheap-fix-*`; review-prep passes
    `prefix="review-prep"` so its scratch stays separable from the pr-fix ones."""
    if prefix not in _PREFIXES:
        raise ValueError(f"unknown scratch owner prefix: {prefix!r}")
    top = _git(repo, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        raise RuntimeError(f"not a git checkout: {repo}")
    root = Path(top.stdout.decode().strip())
    scratch_root.ensure_excluded(root)  # fail-open: a consumer repo with no .gitignore line
    if _git(root, "check-ignore", "-q", f"{SCRATCH_DIR}/cheap-fix-probe/").returncode != 0:
        raise RuntimeError(f"{SCRATCH_DIR}/ is not gitignored in {root}")
    (root / SCRATCH_DIR).mkdir(parents=True, exist_ok=True)
    owner = Path(tempfile.mkdtemp(prefix=f"{prefix}-", dir=root / SCRATCH_DIR))
    try:  # before the drafter runs: what the live tree holds now
        live_tree_guard.snapshot(root, owner / LIVE_TREE)
    except (live_tree_guard.GuardError, OSError) as exc:
        shutil.rmtree(owner, ignore_errors=True)  # our own fresh mkdtemp
        raise RuntimeError(f"live-tree snapshot failed: {exc}") from exc
    proc = _git(repo, "worktree", "add", "--detach", str(owner / "r1"), str(head))
    if proc.returncode != 0:
        shutil.rmtree(owner, ignore_errors=True)  # our own fresh mkdtemp
        raise RuntimeError(f"git worktree add failed: {proc.stderr.decode(errors='replace')}")
    return owner / "r1"


def _is_owner(owner: Path) -> bool:
    """A `<prefix>-*` dir (any prefix in `_PREFIXES`) directly under a SCRATCH_DIR,
    and not a symlink."""
    return (any(owner.name.startswith(f"{p}-") for p in _PREFIXES)
            and not owner.is_symlink()
            and owner.parent.as_posix().endswith(SCRATCH_DIR))


def discard(path) -> None:
    """Remove the scratch worktree and its owner dir; prune its git record. Idempotent:
    a scratch that is already gone is a no-op. A scratch that is present but not an
    `r<N>` dir still raises `round_scratch.RemoveRefused`."""
    path = Path(path)
    if path.exists() or path.is_symlink():
        common = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
        round_scratch.safe_remove(path, path.parent)
        if common.returncode == 0:
            pruned = subprocess.run(["git", "--git-dir", common.stdout.decode().strip(),
                                     "worktree", "prune"], capture_output=True, timeout=120,
                                    check=False)
            if pruned.returncode != 0:  # fail-open: a stale record only names a gone path
                print("cheap_fix: worktree prune failed", file=sys.stderr)
    if _is_owner(path.parent):
        shutil.rmtree(path.parent, ignore_errors=True)


def discard_quietly(path) -> None:
    """discard, reporting a refused remove on stderr instead of raising it."""
    try:
        discard(path)
    except round_scratch.RemoveRefused as exc:
        print(f"cheap_fix: scratch not removed: {exc}", file=sys.stderr)


def tests_argv(finding: dict, files, cwd) -> list[str]:
    """pytest over the fix's own tests: the test files in `files`, plus the finding
    file's sibling `test_<stem>.py` in `cwd`; with neither, the finding file's dir.

    It is never `ci.gate_command`: a repo gate (such as a clean-tree ci-local.sh) refuses
    the dirty scratch, and a gate command is never a cheap slot's oracle."""
    src = PurePosixPath(finding["file"])
    targets = [f for f in files if _is_test(f)]
    sibling = str(src.parent / f"test_{src.stem}.py")
    if sibling not in targets and sibling != str(src) and (Path(cwd) / sibling).is_file():
        targets.append(sibling)
    return [*PYTEST, *(targets or [str(src.parent)])]


def _is_test(path: str) -> bool:
    p = PurePosixPath(path)
    return (p.name.startswith("test_") or p.stem.endswith("_test")
            or any(part in ("tests", "test") for part in p.parts[:-1]))


def _in_scope(name: str, status: str, finding: dict) -> bool:
    """The finding's own file, or a newly added test file; never an existing test and
    never a conftest.py, so the fix cannot weaken a test to pass the oracle."""
    if name == finding.get("file"):
        return True
    return status == "A" and _is_test(name) and PurePosixPath(name).name != "conftest.py"


def _changes(path) -> dict:
    """{file: status letter} for the staged scratch diff against HEAD (renames off)."""
    out = _git(path, "diff", "--cached", "--name-status", "--no-renames", "-z", "HEAD")
    parts = [p for p in out.stdout.decode().split("\0") if p]
    return dict(zip(parts[1::2], parts[0::2]))


def escalation(reason: str) -> dict:
    """An escalate verdict for a failure outside the oracle."""
    return _verdict(False, reason)


def _verdict(ok, reason, files=(), oracle="scope") -> dict:
    return {"ok": bool(ok), "oracle": oracle, "reason": reason,
            "action": "accept" if ok else "escalate", "files": list(files)}


def _live_tree(path: Path, fix_worktree) -> dict | None:
    """An escalate verdict when the drafter wrote the fix worktree (its paths undone)."""
    g = live_tree_guard.guard(fix_worktree, path.parent / LIVE_TREE, exclude=[path.parent])
    return None if g["ok"] else _verdict(False, g["reason"], g["paths"], "live-tree")


def _rebase_pending(path: Path, fix_worktree, files) -> None:
    """Record `files`, just applied, as the baseline of every other pending scratch."""
    top = _git(fix_worktree, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return
    root = Path(top.stdout.decode().strip())
    for store in sorted((root / SCRATCH_DIR).glob(f"cheap-fix-*/{LIVE_TREE}")):
        if store.parent.resolve() == path.parent.resolve() or not _is_owner(store.parent):
            continue
        try:
            live_tree_guard.rebase(root, store, files)
        except (live_tree_guard.GuardError, OSError):
            (store / live_tree_guard.SNAPSHOT).unlink(missing_ok=True)  # fail closed


def _judge(path: Path, fix_worktree, finding: dict, argv) -> dict:
    live = _live_tree(path, fix_worktree)
    if live is not None:
        return live
    if _git(path, "add", "-A").returncode != 0:
        return _verdict(False, "git add failed in the scratch")
    changes = _changes(path)
    files = sorted(changes)
    stray = [f for f in files if not _in_scope(f, changes[f], finding)]
    if not files or stray:
        why = f"out of scope: {', '.join(stray)}" if stray else "the scratch holds no change"
        return _verdict(False, why, files)
    patch = _git(path, "diff", "--cached", "--binary", "HEAD").stdout
    argv = tests_argv(finding, files, path) if argv is None else argv
    with tempfile.TemporaryDirectory(prefix="tp-cheap-fix-repro-") as rd:
        ctx = {"finding": finding, "cwd": str(path), "scratch_dir": rd, "test_argv": list(argv)}
        v = cheap_oracle.check(SLOT, {}, ctx)
    if cheap_oracle.settle(SLOT, v) != "accept":
        return _verdict(False, v["reason"], files, v["oracle"])
    applied = _git(fix_worktree, "apply", "--whitespace=nowarn", "-", data=patch)
    why = applied.stderr.decode(errors="replace").strip()
    if applied.returncode == 0:
        _rebase_pending(path, fix_worktree, files)
    return _verdict(applied.returncode == 0, why and f"git apply failed: {why}", files,
                    v["oracle"])


def adopt(path, fix_worktree, finding: dict, *, test_argv=None) -> dict:
    """Judge the scratch fix, apply it on accept, and always remove the scratch.
    `test_argv` defaults to `tests_argv` over the scratch's changed files."""
    try:
        return _judge(Path(path), fix_worktree, finding, test_argv)
    finally:
        discard_quietly(path)
