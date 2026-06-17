"""Regression test: .gitignore carve-out for the durable orchestration handoff.

Pins the git check-ignore ordering that lets orchestration/handoff.md be tracked
while all other tp-designs/*/handoff.md files stay gitignored. Runs in a hermetic
temp git repo seeded from the REAL repo-root .gitignore — so any regression in the
shipped file (e.g. an inline comment breaking the negation pattern) fails this test.

Contract source: orchestrator-identity (three-pillars-docs/tp-designs/
orchestrator-identity/design.md, Task 3.1).

Run with: python -m pytest skills/_shared/test_gitignore_orchestration_handoff.py -q
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
    return (root / ".gitignore").read_text()


def test_orchestration_handoff_tracked_real_gitignore():
    """orchestration/handoff.md is NOT ignored when using the real .gitignore.

    This test guards against regressions in the shipped .gitignore file itself —
    e.g. an inline comment after the negation pattern that breaks git's matching
    (git .gitignore does NOT support inline/trailing comments).
    """
    repo = _make_temp_repo(_real_gitignore_text())
    result = subprocess.run(
        [
            "git", "-C", str(repo), "check-ignore",
            "three-pillars-docs/tp-designs/orchestration/handoff.md",
        ],
        capture_output=True,
        text=True,
    )
    # exit 1 means NOT ignored — the path would be tracked (the exception wins).
    # Note: git check-ignore plain form (no -v) gives a reliable exit code.
    assert result.returncode != 0, (
        f"Expected orchestration/handoff.md to be NOT ignored (exit non-zero) "
        f"but got exit {result.returncode}. stdout={result.stdout!r}\n"
        f"HINT: check for inline comments on the negation line in .gitignore — "
        f"git does not support trailing comments and treats them as part of the pattern."
    )


def test_per_design_handoff_ignored_real_gitignore():
    """A regular per-design handoff.md IS ignored when using the real .gitignore."""
    repo = _make_temp_repo(_real_gitignore_text())
    result = subprocess.run(
        [
            "git", "-C", str(repo), "check-ignore",
            "three-pillars-docs/tp-designs/some-design/handoff.md",
        ],
        capture_output=True,
        text=True,
    )
    # exit 0 means IS ignored — the general rule wins
    assert result.returncode == 0, (
        f"Expected some-design/handoff.md to be ignored (exit 0) "
        f"but got exit {result.returncode}. stdout={result.stdout!r}"
    )


def test_inline_comment_on_negation_breaks_tracking():
    """MUTATION: inline comment on the negation line causes the path to be ignored.

    This test documents the exact failure mode that Fix 1 corrects: appending
    '# comment' to the '!...handoff.md' line makes git treat the whole thing
    (including the comment text) as the pattern, so the negation no longer matches
    the actual path and the file becomes wrongly ignored.

    This test passes when the mutation IS present (the broken state), proving that
    the mutation-test infrastructure actually detects the bug class.
    """
    real_text = _real_gitignore_text()
    # Inject the broken inline-comment form on the negation line
    broken_text = real_text.replace(
        "!three-pillars-docs/tp-designs/orchestration/handoff.md\n",
        "!three-pillars-docs/tp-designs/orchestration/handoff.md  # inline-comment-mutation\n",
    )
    repo = _make_temp_repo(broken_text)
    result = subprocess.run(
        [
            "git", "-C", str(repo), "check-ignore",
            "three-pillars-docs/tp-designs/orchestration/handoff.md",
        ],
        capture_output=True,
        text=True,
    )
    # With the inline comment present the negation doesn't match the path, so git
    # ignores the file (exit 0). This confirms the mutation is detectable.
    assert result.returncode == 0, (
        f"Expected the MUTATED (broken) gitignore to IGNORE the file (exit 0), "
        f"meaning the inline-comment breaks the negation. "
        f"Got exit {result.returncode} — mutation test infrastructure may be broken."
    )
