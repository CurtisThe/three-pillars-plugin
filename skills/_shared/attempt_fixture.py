"""attempt_fixture.py — tmp git repo builder for the attempt-worktree tests.

design: local-implement-and-review

Not a test module (no `test_` prefix, never collected): the shared fixture the
`test_task_verify_{guard,attempts,sweep}.py` files build real tmp repos with. Every
git call runs with the repo-local git env scrubbed, so no fixture ever reads or
writes the ambient repository's worktrees or branches (M23).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import task_scope  # the shipped scrub: git_env is dev-only and never ships

IDENTITY = {
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test",
}
SLUG = "demo"
DD = f"three-pillars-docs/tp-designs/{SLUG}"


def git(repo: Path, *args: str, check: bool = True) -> str:
    out = subprocess.run(["git", *args], cwd=str(repo), env=task_scope._git_env(**IDENTITY),
                         capture_output=True, text=True, check=check)
    return out.stdout.strip()


def write(repo: Path, rel: str, text: str = "x\n") -> Path:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def commit(repo: Path, files: dict, msg: str = "change") -> str:
    """Write ``files``, commit them, return the new HEAD SHA."""
    for rel, text in files.items():
        write(repo, rel, text)
        git(repo, "add", "--", rel)
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def make_seat(tmp_path: Path, slug: str = SLUG) -> tuple[Path, Path]:
    """A seat repo on ``main`` plus a live ``<repo>-wt/<slug>`` worktree on ``tp/<slug>``.

    Returns ``(seat, design_worktree)``. The base commit carries a source file and
    the design dir's ``lock.json`` / ``decisions.md`` so tests can dirty them.
    """
    seat = tmp_path / "repo"
    seat.mkdir()
    git(seat, "init", "-q", "-b", "main")
    dd = f"three-pillars-docs/tp-designs/{slug}"
    commit(seat, {"README.md": "demo\n", "skills/a.py": "A = 1\n",
                  f"{dd}/lock.json": "{}\n", f"{dd}/decisions.md": "# decisions\n"}, "base")
    wt = tmp_path / "repo-wt" / slug
    git(seat, "worktree", "add", "-q", "-b", f"tp/{slug}", str(wt))
    return seat, wt


def agent_worktree(seat: Path, name: str = "agent-x", slug: str = SLUG) -> Path:
    """``<seat>/.claude/worktrees/<name>`` on ``candidate/<slug>/single``."""
    path = seat / ".claude" / "worktrees" / name
    git(seat, "worktree", "add", "-q", "-b", f"candidate/{slug}/single", str(path))
    return path


def porcelain(repo: Path) -> str:
    return git(repo, "worktree", "list", "--porcelain")


def branches(repo: Path, pattern: str = "tp-attempt/*") -> list[str]:
    return git(repo, "branch", "--list", "--format=%(refname:short)", pattern).split()


def task_row(files=("skills/a.py",), targets: str | None = None, *, unparsed=(),
             task_id: str = "1.1") -> dict:
    """An eligibility-shaped row from a **Targets** field (None = the field is missing):
    the keys ``task_verify.check`` reads."""
    parsed = task_scope.parse_targets(targets)
    return {"task_id": task_id, "files": list(files), "unparsed_files": list(unparsed),
            "test": parsed, "test_paths": list(parsed["files"])}
