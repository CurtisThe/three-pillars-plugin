"""``audit_dispositions.mark`` — Behavior 11 on a real tmp repo.

design: review-convergence 6.2, detailed-design-pr-loop.md §D4.

The carry entry is only allowed to silence a round-1 finding while the audited file
has not moved since the audit. These cases run the real ``git diff --quiet
<audit_head> <head> -- <file>`` (no injected seam) against a fixture repo with an
``audit_head`` commit and a later head commit, so the three behaviours are measured
by git rather than asserted about it:

- file unchanged since ``audit_head``  -> dispositioned, not blocking;
- file changed since the audit         -> no disposition, still blocking;
- unchanged file but ``reproduction == "reproduced"`` -> still blocking.

The repo env is scrubbed (M23) so a hook-inherited ``GIT_DIR`` can never point these
calls at the ambient repository.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from task_scope import _git_env as clean_git_env  # noqa: E402  shipped scrub; git_env is dev-only

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_dispositions  # noqa: E402

_IDENTITY = {
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test",
}

TARGET = "skills/_shared/guard.py"
CLAIM = "guard rejects a path outside the design worktree"
SAME_CLAIM = "guard rejects a path outside the design worktree dir"


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), env=clean_git_env(**_IDENTITY),
                          capture_output=True, text=True, check=True).stdout


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path, *, change_target: bool) -> tuple[Path, str, str]:
    """Fixture repo: an ``audit_head`` commit, then a later head commit.

    With ``change_target`` the later commit edits the audited file; without it the
    later commit edits an unrelated file, so the audited file is unchanged.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _write(repo, TARGET, "def guard(path):\n    return True\n")
    _write(repo, "skills/_shared/other.py", "x = 1\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "audit head", cwd=repo)
    audit_head = _git("rev-parse", "HEAD", cwd=repo).strip()

    if change_target:
        _write(repo, TARGET, "def guard(path):\n    return path.is_absolute()\n")
    else:
        _write(repo, "skills/_shared/other.py", "x = 2\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "later head", cwd=repo)
    return repo, audit_head, _git("rev-parse", "HEAD", cwd=repo).strip()


def _carry(tmp_path: Path, audit_head: str) -> Path:
    path = tmp_path / audit_dispositions.CARRY
    path.write_text(json.dumps([{
        "file": TARGET,
        "area": "skills/_shared",
        "claim": CLAIM,
        "disposition": "fixed",
        "severity": "medium",
        "audit_head": audit_head,
        "line": [1, 2],
    }], indent=2) + "\n", encoding="utf-8")
    return path


def _finding(**over) -> dict:
    f = {
        "source": "code-review",
        "file": TARGET,
        "line_range": [1, 2],
        "summary": SAME_CLAIM,
        "verdict": "structural",
        "blocking": True,
    }
    f.update(over)
    return f


def _mark(tmp_path: Path, repo: Path, audit_head: str, head: str, **over) -> dict:
    out = audit_dispositions.mark([_finding(**over)], _carry(tmp_path, audit_head),
                                  cwd=repo, head=head, round_no=1)
    return out[0]


def test_unchanged_file_dispositiones_the_finding(tmp_path):
    repo, audit_head, head = _repo(tmp_path, change_target=False)
    assert audit_head != head
    marked = _mark(tmp_path, repo, audit_head, head)
    assert marked["dispositioned"] is True
    assert marked["blocking"] is False
    assert marked["verdict"] == "minor"
    assert audit_head[:12] in marked["disposition_note"]


def test_file_changed_since_audit_still_blocks(tmp_path):
    repo, audit_head, head = _repo(tmp_path, change_target=True)
    marked = _mark(tmp_path, repo, audit_head, head)
    assert "dispositioned" not in marked
    assert marked["blocking"] is True
    assert marked["verdict"] == "structural"


def test_reproduced_finding_still_blocks_although_file_unchanged(tmp_path):
    repo, audit_head, head = _repo(tmp_path, change_target=False)
    marked = _mark(tmp_path, repo, audit_head, head, reproduction="reproduced")
    assert "dispositioned" not in marked
    assert marked["blocking"] is True


def test_unresolvable_audit_head_fails_closed(tmp_path):
    """A diff git cannot run (unknown sha) is treated as changed: no disposition."""
    repo, _audit_head, head = _repo(tmp_path, change_target=False)
    marked = _mark(tmp_path, repo, "0000000000000000000000000000000000000000", head)
    assert "dispositioned" not in marked
    assert marked["blocking"] is True
