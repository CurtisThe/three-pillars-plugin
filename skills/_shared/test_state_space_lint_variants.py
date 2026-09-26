"""Variant-markdown and fail-open tests for state_space_lint.py (PR #154 review)."""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from state_space_lint import count_loci, extract_section, lint, main  # noqa: E402

MAP = """## State space
### Loci
- One — why
- Two — why
### Questions
- Q1 [Guard] where? — flips: a
"""


def test_bom_before_first_line_heading(tmp_path, capsys):
    bad = "﻿## State space\n### Loci\n- Only\n"
    (tmp_path / "design.md").write_bytes(bad.encode("utf-8"))
    assert main([str(tmp_path)]) == 0
    assert "fewer than 2 loci (1)" in capsys.readouterr().out
    assert lint(bad) == ["fewer than 2 loci (1) under ### Loci"]


def test_heading_case_insensitive():
    assert lint(MAP.replace("## State space", "## State Space")) == []
    assert "fewer than 2 loci" in lint("## STATE SPACE\n### loci\n- a\n")[0]


def test_star_bullets_and_bold_questions():
    text = "## State space\n### Loci\n* A\n* B\n### Questions\n- **Q1** [G] where?\n"
    assert count_loci(extract_section(text)) == 2
    warns = lint(text)
    assert len(warns) == 1 and "Q1" in warns[0]


def test_dash_without_space_and_rule_are_not_loci():
    text = "## State space\n### Loci\n- A\n-B\n---\n"
    assert count_loci(extract_section(text)) == 1


def test_zero_loci_when_subsection_missing():
    assert lint("## State space\n### Dimensions\n- x\n") == ["fewer than 2 loci (0) under ### Loci"]


def test_fenced_example_inside_section_not_counted():
    text = MAP.replace("### Questions", "```markdown\n### Loci\n- F1\n- F2\n- F3\n```\n### Questions")
    assert count_loci(extract_section(text)) == 2
    one = "## State space\n### Loci\n- Only\n```\n### Loci\n- F1\n- F2\n```\n"
    assert "fewer than 2 loci (1)" in lint(one)[0]


def test_unterminated_fence_earlier_does_not_hide_section():
    text = "## Problem\nstray ``` here\n```\nno close\n\n" + MAP.replace("- Two — why\n", "")
    warns = lint(text)
    assert warns == ["fewer than 2 loci (1) under ### Loci"]


def test_wrapped_question_continuation_carries_flip():
    text = MAP.replace("- Q1 [Guard] where? — flips: a", "- Q1 [Guard] a long\n  question — flips: a")
    assert lint(text) == []


def test_wrap_does_not_borrow_next_bullets_flip():
    text = MAP.replace("- Q1 [Guard] where? — flips: a", "- Q1 [G] no target\n- Q2 [H] x — flips: b")
    warns = lint(text)
    assert len(warns) == 1 and "Q1" in warns[0]


def test_duplicate_sections_warns_and_lints_first():
    warns = lint(MAP + "\n## State space\n### Loci\n- X\n")
    assert warns[0].startswith("2 ## State space sections")
    assert len(warns) == 1


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_unreadable_parent_dir_warns_and_exits_zero(tmp_path, capsys):
    locked = tmp_path / "locked"
    (locked / "sub").mkdir(parents=True)
    locked.chmod(0)
    try:
        assert main([str(locked / "sub")]) == 0
    finally:
        locked.chmod(0o755)
    assert capsys.readouterr().out.startswith("WARN state-space: cannot read ")


def test_unencodable_output_is_replaced(tmp_path, monkeypatch):
    (tmp_path / "design.md").write_text(
        "## State space\n### Loci\n- A\n### Questions\n- Q1 café → x\n", encoding="utf-8")
    buf = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(buf, encoding="ascii"))
    assert main([str(tmp_path)]) == 0
    sys.stdout.flush()
    assert b"WARN state-space: question lacks a flips: target: - Q1 caf?" in buf.getvalue()


def test_lint_bug_fails_open(tmp_path, capsys, monkeypatch):
    import state_space_lint
    (tmp_path / "design.md").write_text(MAP, encoding="utf-8")
    monkeypatch.setattr(state_space_lint, "lint", lambda _t: 1 / 0)
    assert main([str(tmp_path)]) == 0
    assert "lint error" in capsys.readouterr().out


def test_backtick_line_inside_tilde_fence_does_not_close_it():
    text = "## Notes\n~~~markdown\n```bash\n~~~\n\n## State space\n### Loci\n- only one\n```text\nx\n```\n"
    assert lint(text) == ["fewer than 2 loci (1) under ### Loci"]


def test_four_backtick_quote_of_template_is_masked():
    quoted = "````markdown\n## State space\n### Loci\n- quoted\n```\ninner\n```\n````\n\n"
    warns = lint("## Background\n" + quoted + MAP)
    assert warns == []  # the quoted template is masked; the real map is clean


def test_closer_with_info_string_does_not_close():
    text = "## A\n```\n```md\nstill code\n```\n\n" + MAP.replace("- Two — why\n", "")
    assert lint(text) == ["fewer than 2 loci (1) under ### Loci"]


def test_main_survives_stripped_docstrings(tmp_path):
    import subprocess
    (tmp_path / "design.md").write_text("## State space\n### Loci\n- A\n", encoding="utf-8")
    lint_py = Path(__file__).resolve().parent / "state_space_lint.py"
    r = subprocess.run([sys.executable, "-OO", str(lint_py), str(tmp_path)],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0 and "fewer than 2 loci" in r.stdout


def test_unclosed_opener_does_not_blind_later_fences():
    text = ("## A\nstray ```\n```\n\n## State space\n### Loci\n- A\n~~~markdown\n## Not a heading\n~~~\n"
            "- B\n")
    assert lint(text) == []


def test_list_item_fence_indented_four_spaces_is_masked():
    quoted = "- Template example:\n\n    ```markdown\n    ## State space\n    ### Loci\n    - x\n    ```\n\n"
    assert lint("## Notes\n" + quoted + MAP) == []


def test_bare_backtick_line_inside_longer_fence_does_not_close_it():
    text = "## A\n````\n```\n## State space\n### Loci\n- fake\n````\n\n" + MAP
    assert lint(text) == []


def test_bare_backtick_line_inside_tilde_fence_does_not_close_it():
    text = "## A\n~~~\n```\n## State space\n### Loci\n- fake\n~~~\n\n" + MAP
    assert lint(text) == []


def test_info_string_line_inside_fence_does_not_close_it():
    text = "## A\n```\n```md\n## State space\n### Loci\n- fake\n```\n\n" + MAP
    assert lint(text) == []
