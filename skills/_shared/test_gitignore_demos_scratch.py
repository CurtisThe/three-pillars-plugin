"""Regression test: .gitignore scratch-hatch for demos/scratch/ and *.tmp inside demos/.

Pins the rules that let demos/ stay tracked evidence while demos/scratch/ and *.tmp
inside demos/ stay gitignored as throwaway scratch. Runs in a hermetic temp git repo
seeded from the REAL repo-root .gitignore.

Contract source: spike-evidence-versioning Task 1.1.

Run with: python -m pytest skills/_shared/test_gitignore_demos_scratch.py -q
"""

import subprocess
import tempfile
from pathlib import Path


def _repo_root() -> Path:
    """Locate the real repo root via git."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def _make_temp_repo(gitignore_text: str) -> Path:
    """Create a hermetic temp git repo with the given .gitignore content."""
    tmpdir = Path(tempfile.mkdtemp())
    subprocess.run(["git", "init", "-b", "main", str(tmpdir)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmpdir), "config", "user.email", "test@example.com"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmpdir), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )
    gitignore = tmpdir / ".gitignore"
    gitignore.write_text(gitignore_text)
    return tmpdir


def _real_gitignore_text() -> str:
    """Read the actual repo-root .gitignore content."""
    root = _repo_root()
    return (root / ".gitignore").read_text(encoding="utf-8")


def _check_ignore(repo: Path, path: str) -> int:
    """Run git check-ignore and return the exit code."""
    result = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", path],
        capture_output=True,
        text=True,
    )
    return result.returncode


def test_demos_scratch_is_ignored_in_tp_designs():
    """demos/scratch/note.txt inside a tp-design IS ignored (throwaway hatch)."""
    repo = _make_temp_repo(_real_gitignore_text())
    rc = _check_ignore(repo, "three-pillars-docs/tp-designs/x/demos/scratch/note.txt")
    assert rc == 0, (
        "Expected three-pillars-docs/tp-designs/x/demos/scratch/note.txt to be IGNORED "
        f"(exit 0) but got exit {rc}. "
        "Add the scratch-hatch rule to .gitignore."
    )


def test_demos_tmp_is_ignored_in_tp_designs():
    """demos/run.tmp inside a tp-design IS ignored (throwaway hatch)."""
    repo = _make_temp_repo(_real_gitignore_text())
    rc = _check_ignore(repo, "three-pillars-docs/tp-designs/x/demos/run.tmp")
    assert rc == 0, (
        "Expected three-pillars-docs/tp-designs/x/demos/run.tmp to be IGNORED "
        f"(exit 0) but got exit {rc}. "
        "Add the *.tmp hatch rule to .gitignore."
    )


def test_demos_evidence_is_not_ignored_in_tp_designs():
    """demos/evidence.md inside a tp-design is NOT ignored (stays tracked evidence)."""
    repo = _make_temp_repo(_real_gitignore_text())
    rc = _check_ignore(repo, "three-pillars-docs/tp-designs/x/demos/evidence.md")
    assert rc != 0, (
        "Expected three-pillars-docs/tp-designs/x/demos/evidence.md to be NOT IGNORED "
        f"(exit non-zero) but got exit {rc}. "
        "The scratch-hatch must not block normal demos/ content."
    )


def test_demos_scratch_is_ignored_in_completed_designs():
    """demos/scratch/ inside a completed-tp-design IS also ignored."""
    repo = _make_temp_repo(_real_gitignore_text())
    rc = _check_ignore(repo, "three-pillars-docs/completed-tp-designs/x/demos/scratch/note.txt")
    assert rc == 0, (
        "Expected completed-tp-designs/x/demos/scratch/note.txt to be IGNORED "
        f"(exit 0) but got exit {rc}."
    )


def test_demos_tmp_is_ignored_in_completed_designs():
    """demos/*.tmp inside a completed-tp-design IS also ignored."""
    repo = _make_temp_repo(_real_gitignore_text())
    rc = _check_ignore(repo, "three-pillars-docs/completed-tp-designs/x/demos/run.tmp")
    assert rc == 0, (
        "Expected completed-tp-designs/x/demos/run.tmp to be IGNORED "
        f"(exit 0) but got exit {rc}."
    )


def test_demos_evidence_is_not_ignored_in_completed_designs():
    """demos/evidence.md inside a completed-tp-design is NOT ignored."""
    repo = _make_temp_repo(_real_gitignore_text())
    rc = _check_ignore(
        repo, "three-pillars-docs/completed-tp-designs/x/demos/evidence.md"
    )
    assert rc != 0, (
        "Expected completed-tp-designs/x/demos/evidence.md to be NOT IGNORED "
        f"(exit non-zero) but got exit {rc}."
    )


def test_orchestration_handoff_still_tracked():
    """Regression: orchestration/handoff.md carve-out still works (no regression)."""
    repo = _make_temp_repo(_real_gitignore_text())
    rc = _check_ignore(repo, "three-pillars-docs/tp-designs/orchestration/handoff.md")
    assert rc != 0, (
        "Regression: orchestration/handoff.md should NOT be ignored after scratch-hatch "
        f"changes. Got exit {rc}."
    )
