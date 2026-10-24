"""rerun_fixture.py — tmp git repo builder for the Tier 3.5 re-run tests.

design: local-implement-and-review

Not a test module (no `test_` prefix, never collected): the shared fixture the
`test_rerun_phase_*.py` files build real tmp repos with. Every git call runs with the
repo-local git env scrubbed, so no fixture ever reads or writes the ambient repository
(M23).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import rerun_phase_tests  # noqa: F401 — puts skills/_shared on sys.path
import wt_root
import task_scope  # the shipped scrub: git_env is dev-only and never ships

IDENTITY = {
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test",
}
DD = "three-pillars-docs/tp-designs/demo"
PLAN = f"{DD}/plan.md"


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=str(repo), env=task_scope._git_env(**IDENTITY),
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def commit(repo: Path, files: dict, msg: str = "change") -> str:
    """Write (``None`` deletes) ``files``, commit them, return the new HEAD SHA."""
    for rel, text in files.items():
        path = repo / rel
        if text is None:
            git(repo, "rm", "-q", "--", rel)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        git(repo, "add", "--", rel)
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def make_repo(tmp_path: Path, *, pytest_ini: bool = True) -> tuple[Path, str]:
    """A fresh repo on ``main`` → ``(repo, base_sha)``."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    files = {"README.md": "demo\n"}
    if pytest_ini:
        files["pytest.ini"] = "[pytest]\n"
    return repo, commit(repo, files, "base")


def task(tid: str, targets: str | None, files: str = "`src/a.py`",
         status: str | None = None) -> str:
    """A task block declaring ``targets`` (``None`` omits the **Targets** line)."""
    block = f"### Task {tid}: task {tid}\n**File**: {files}\n**Test**: prose only.\n"
    if targets is not None:
        block += f"**Targets**: {targets}\n"
    block += "**Red**: red\n**Green**: green\n"
    return block + (f"**Status**: {status}\n" if status else "")


def plan(phases: dict) -> str:
    """``{phase_number: [task blocks]}`` → plan.md text."""
    out = ["# demo — Implementation Plan\n"]
    for num, blocks in phases.items():
        out.append(f"## Phase {num}: phase {num}\n")
        out.extend(blocks)
    return "\n".join(out)


def leftovers(repo: Path) -> tuple[list[str], list[str], int]:
    """``(scratch dirs, tp-rerun/* branches, worktree count)`` after a re-run."""
    dirs = sorted(p.name for p in Path(wt_root.scratch_parent(repo, DD.rsplit("/", 1)[-1])).glob("tp-rerun-*"))
    branches = git(repo, "branch", "--list", "--format=%(refname:short)", "tp-rerun/*").split()
    porcelain = git(repo, "worktree", "list", "--porcelain").splitlines()
    count = sum(1 for line in porcelain if line.startswith("worktree "))
    return dirs, branches, count
