"""Regression test: repo-root .gitignore ignores the new scratch base.

`.tp-scratch/` is the one scratch base for attempt and child-spawn worktrees
(scratch_root.py). The framework also seeds the rule into
`<git-common-dir>/info/exclude`, but a consumer repo's committed `.gitignore`
must carry it too so the scratch stays out of `git status` on a fresh clone
with no local exclude.

Pins the exact ignore line for `/.tp-scratch/` and the pre-existing
`.claude/worktrees/` line (agent isolation) that the new base must not replace.

Contract source: launch-role-precedence Task 3.3.

Run with: python -m pytest skills/_shared/test_scratch_root_gitignore.py -q
"""

import subprocess
from pathlib import Path

import scratch_root

NEW_LINE = "/.tp-scratch/"
LEGACY_LINE = ".claude/worktrees/"


def _repo_root() -> Path:
    """Locate the real repo root via git."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def _gitignore_lines() -> list:
    """The repo-root .gitignore, split into lines."""
    text = (_repo_root() / ".gitignore").read_text(encoding="utf-8")
    return text.splitlines()


def _init_repo_with_gitignore(tmp_path: Path, gitignore_text: str) -> Path:
    """Hermetic temp git repo seeded with the given .gitignore content."""
    subprocess.run(
        ["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True
    )
    (tmp_path / ".gitignore").write_text(gitignore_text, encoding="utf-8")
    return tmp_path


def _check_ignore(repo: Path, path: str) -> int:
    """Exit code of `git check-ignore -q <path>` (0 == ignored)."""
    result = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", path],
        capture_output=True,
        text=True,
    )
    return result.returncode


def test_scratch_root_ignore_line_is_pinned():
    """scratch_root.ignore_line() is the exact line .gitignore must carry."""
    assert scratch_root.ignore_line() == NEW_LINE


def test_new_scratch_base_line_present():
    """`/.tp-scratch/` is an exact line in the repo-root .gitignore."""
    lines = _gitignore_lines()
    assert NEW_LINE in lines, (
        f"Expected an exact line {NEW_LINE!r} in the repo-root .gitignore so "
        "attempt/child-spawn scratch never shows up in git status. "
        "Add it with a one-line comment."
    )


def test_legacy_agent_worktrees_line_still_present():
    """The `.claude/worktrees/` isolation rule is not removed by the new base."""
    lines = _gitignore_lines()
    assert LEGACY_LINE in lines, (
        f"Regression: expected the exact line {LEGACY_LINE!r} to remain in "
        ".gitignore — agent isolation still needs it."
    )


def test_tp_scratch_path_is_ignored_by_git(tmp_path):
    """A temp repo seeded with the real .gitignore ignores `.tp-scratch/x`."""
    repo = _init_repo_with_gitignore(tmp_path, "\n".join(_gitignore_lines()) + "\n")
    rc = _check_ignore(repo, ".tp-scratch/x")
    assert rc == 0, (
        "Expected `.tp-scratch/x` to be IGNORED (exit 0) by the real .gitignore "
        f"but got exit {rc}. Add {NEW_LINE!r} to .gitignore."
    )


def test_claude_worktrees_path_still_ignored_by_git(tmp_path):
    """Regression: `.claude/worktrees/` still ignored after the new rule."""
    repo = _init_repo_with_gitignore(tmp_path, "\n".join(_gitignore_lines()) + "\n")
    rc = _check_ignore(repo, ".claude/worktrees/agent-x/x")
    assert rc == 0, (
        "Regression: expected `.claude/worktrees/agent-x/x` to be IGNORED "
        f"(exit 0) but got exit {rc}."
    )
