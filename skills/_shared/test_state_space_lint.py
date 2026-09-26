"""Tests for skills/_shared/state_space_lint.py (warn-only)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from state_space_lint import (  # noqa: E402
    count_loci,
    extract_section,
    lint,
    main,
    questions_missing_flip,
)

FULL = """# D

## Problem
x

## State space
### Loci
- Launcher — caller knows
- Receiver — callee detects
### Dimensions
- **Guard**: a x · b y → leading a (High)
### Assumptions
- A holds — check: grep
### Flip evidence
- bypass path flips a
### Questions
- Q1 [Guard] where? — flips: a
- Defaults (no flip): Other = b

## Constraints
- c
"""

COMPACT = """## State space
### Loci
- One — why
- Two — why
### Dimensions
- **Guard**: a x · b y → leading a (Med)
### Flip evidence
- something
"""

ONE_LOCUS = """## State space
### Loci
- Only — why
### Dimensions
- **Guard**: a · b → leading a (Low)
- extra bullet not a locus
"""

NO_FLIP = """## State space
### Loci
- One
- Two
### Questions
- Q1 [Guard] where?
- Q2 [Scope] what? — flips:
- q3 [Order] which? — FLIPS: b
- Defaults (no flip): X = a
"""


def test_extract_section_body_and_stops_at_next_h2():
    sec = extract_section(FULL)
    assert sec is not None
    assert "### Loci" in sec
    assert "## Constraints" not in sec and "- c" not in sec


def test_extract_section_absent():
    assert extract_section("# D\n\n## Problem\nx\n") is None


def test_extract_section_ignores_fenced_block():
    text = "## Problem\n```markdown\n## State space\n### Loci\n- a\n```\n"
    assert extract_section(text) is None


def test_count_loci_only_under_loci():
    assert count_loci(extract_section(FULL)) == 2
    assert count_loci(extract_section(ONE_LOCUS)) == 1


def test_questions_missing_flip():
    missing = questions_missing_flip(extract_section(NO_FLIP))
    assert len(missing) == 2
    assert any("Q1" in m for m in missing)
    assert any("Q2" in m for m in missing)


def test_lint_clean_full_and_compact():
    assert lint(FULL) == []
    assert lint(COMPACT) == []


def test_lint_one_locus():
    warns = lint(ONE_LOCUS)
    assert len(warns) == 1
    assert "fewer than 2 loci" in warns[0]


def test_lint_missing_flip_one_warning_each():
    assert len(lint(NO_FLIP)) == 2


def test_lint_no_section_is_clean():
    assert lint("# D\n\n## Problem\nx\n") == []


def test_main_directory_with_warnings(tmp_path, capsys):
    (tmp_path / "design.md").write_text(ONE_LOCUS, encoding="utf-8")
    assert main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("WARN state-space: ")
    assert "fewer than 2 loci" in out


def test_main_file_clean(tmp_path, capsys):
    p = tmp_path / "x.md"
    p.write_text(FULL, encoding="utf-8")
    assert main([str(p)]) == 0
    assert capsys.readouterr().out == ""


def test_main_no_section(tmp_path, capsys):
    (tmp_path / "design.md").write_text("# D\n", encoding="utf-8")
    assert main([str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""


def test_main_missing_path(tmp_path, capsys):
    assert main([str(tmp_path / "nope")]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1 and out[0].startswith("WARN state-space: ")


def test_main_non_utf8_warns_and_exits_zero(tmp_path, capsys):
    (tmp_path / "design.md").write_bytes(b"## State space\n\xff\xfe bad \x80\n### Loci\n- a\n- b\n")
    assert main([str(tmp_path)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1 and out[0].startswith("WARN state-space: cannot read ")
    assert str(tmp_path / "design.md") in out[0]
