"""Tests for invariant_check.py CLI + grandfather entry verification (Tasks 3.3/3.4).

Task 3.3: Verify citation_liveness.py and test_citation_liveness.py are NOT in
  the grandfather list AND both files are < 500 lines / < 50k chars.

Task 3.4: CLI main() integration over temp-repo fixtures.
  exit 0: clean tree; exit 1: seeded out-of-range cite (one repair line per violation);
  --count: print active_count() and exit 0; exit 2: corrupt framework-check.sh.

Mirrors file_size_guard.py / hot_patch_check.py CLI shape; stdlib-only.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GRANDFATHER = REPO_ROOT / ".three-pillars" / "file-size-grandfather.txt"
SHARED = REPO_ROOT / "skills" / "_shared"

# ------------------------------------------------------------------ #
# Task 3.3 — grandfather entries removed; both files under cap
# ------------------------------------------------------------------ #

LINE_CAP = 500
CHAR_CAP = 50_000


def _grandfather_entries() -> list[str]:
    if not GRANDFATHER.is_file():
        return []
    return [
        ln.strip()
        for ln in GRANDFATHER.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def test_grandfather_citation_liveness_removed():
    """citation_liveness.py must NOT be in the grandfather list (entry is stale)."""
    entries = _grandfather_entries()
    assert "skills/_shared/citation_liveness.py" not in entries, (
        "citation_liveness.py is < 500 lines after the 3.1 carve — "
        "its grandfather entry is STALE and must be removed"
    )


def test_grandfather_test_citation_liveness_removed():
    """test_citation_liveness.py must NOT be in the grandfather list (entry is stale)."""
    entries = _grandfather_entries()
    assert "skills/_shared/test_citation_liveness.py" not in entries, (
        "test_citation_liveness.py is < 500 lines after the 3.1 split — "
        "its grandfather entry is STALE and must be removed"
    )


def test_citation_liveness_under_line_cap():
    """citation_liveness.py must be < 500 lines (no inv #34 violation)."""
    f = SHARED / "citation_liveness.py"
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    assert len(lines) < LINE_CAP, (
        f"citation_liveness.py has {len(lines)} lines, cap is {LINE_CAP}"
    )


def test_citation_liveness_under_char_cap():
    """citation_liveness.py must be < 50k chars."""
    f = SHARED / "citation_liveness.py"
    chars = len(f.read_text(encoding="utf-8", errors="replace"))
    assert chars < CHAR_CAP, (
        f"citation_liveness.py has {chars} chars, cap is {CHAR_CAP}"
    )


def test_test_citation_liveness_under_line_cap():
    """test_citation_liveness.py must be < 500 lines."""
    f = SHARED / "test_citation_liveness.py"
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    assert len(lines) < LINE_CAP, (
        f"test_citation_liveness.py has {len(lines)} lines, cap is {LINE_CAP}"
    )


def test_test_citation_liveness_under_char_cap():
    """test_citation_liveness.py must be < 50k chars."""
    f = SHARED / "test_citation_liveness.py"
    chars = len(f.read_text(encoding="utf-8", errors="replace"))
    assert chars < CHAR_CAP, (
        f"test_citation_liveness.py has {chars} chars, cap is {CHAR_CAP}"
    )


# ------------------------------------------------------------------ #
# Task 3.4 — invariant_check.py CLI
# ------------------------------------------------------------------ #

# Stub framework-check.sh with 5 active invariant headers.
_FC_5 = "\n".join(f"# {i}. Rule {i}" for i in range(1, 6))


def _make_cli_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Write a minimal fixture repo for CLI integration tests."""
    (tmp_path / "framework-check.sh").write_text(_FC_5 + "\n", encoding="utf-8")
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def _run_cli(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run invariant_check.py as a subprocess and return the result."""
    cli = SHARED / "invariant_check.py"
    return subprocess.run(
        [sys.executable, str(cli), "--repo-root", str(repo), *args],
        capture_output=True,
        text=True,
    )


def test_cli_exit_0_clean_tree(tmp_path):
    """main(): exit 0 on a clean fixture tree (no violations)."""
    repo = _make_cli_repo(tmp_path, {
        "SECURITY.md": "No invariant cites here.\n",
    })
    result = _run_cli(repo)
    assert result.returncode == 0, (
        f"expected exit 0 on clean tree, got {result.returncode}; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_cli_exit_1_with_violation(tmp_path):
    """main(): exit 1 with one repair line per violation on seeded out-of-range cite."""
    repo = _make_cli_repo(tmp_path, {
        "SECURITY.md": "see invariant #99 for details\n",
    })
    result = _run_cli(repo)
    assert result.returncode == 1, (
        f"expected exit 1 on violation, got {result.returncode}; "
        f"stdout={result.stdout!r}"
    )
    # Must emit at least one repair line mentioning 99
    assert "99" in result.stdout, (
        f"repair output must mention the cited number 99; stdout={result.stdout!r}"
    )
    # Repair line format: file:line: <class>: ...
    repair_lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(repair_lines) >= 1, "must emit at least one repair line"
    assert ":" in repair_lines[0], f"repair line must contain ':': {repair_lines[0]!r}"


def test_cli_count_prints_active_count(tmp_path):
    """main(--count): prints active_count() integer and exits 0."""
    repo = _make_cli_repo(tmp_path, {})
    result = _run_cli(repo, "--count")
    assert result.returncode == 0, (
        f"--count must exit 0; got {result.returncode}"
    )
    # Output must be an integer (active_count from the 5-header stub = 5)
    out = result.stdout.strip()
    assert out.isdigit(), f"--count output must be an integer; got {out!r}"
    assert int(out) == 5, f"stub has 5 active headers, expected 5; got {out!r}"


def test_cli_exit_2_corrupt_framework_check(tmp_path):
    """main(): exit 2 on a corrupt/unparseable framework-check.sh (fail-closed).

    Missing framework-check.sh causes parse_invariant_map to raise OSError,
    which propagates through run_citation_checks to _run_checks → exit 2.
    """
    # Do NOT write a framework-check.sh — parse_invariant_map will raise OSError.
    (tmp_path / "SECURITY.md").write_text(
        "see invariant #99 for details\n", encoding="utf-8"
    )
    result = _run_cli(tmp_path)
    assert result.returncode == 2, (
        f"missing framework-check.sh must exit 2 (fail-closed); "
        f"got {result.returncode}; stderr={result.stderr!r}"
    )
