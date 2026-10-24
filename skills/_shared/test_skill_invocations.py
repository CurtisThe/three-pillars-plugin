"""test_skill_invocations.py — Task 1.11: `skill_invocations.invocations` reads structured spans only.

design: living-doc-fragments, Task 1.11. Oracle: example. Every case writes its own markdown; no real
SKILL.md is read here, so nothing pins skill prose (skills/_shared/test-fragility.md §1-2).
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

pytest.importorskip("skill_spans")  # dev-only; a plugin copy keeps skill_invocations but not this module
import skill_invocations as si  # noqa: E402

TP = "$TP_ROOT/skills/_shared/tool.py"


def _md(tmp_path, text: str):
    path = tmp_path / "SKILL.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_invocations_read_only_structured_spans(tmp_path):
    path = _md(tmp_path, "\n".join([
        "---",
        "description: python3 skills/_shared/tool.py in frontmatter is skipped",
        "---",
        "",
        "Prose that says python3 skills/_shared/tool.py bare-in-prose never counts.",
        "See `skills/_shared/tool.py` for details, and `python3 skills/_shared/other.py nope`.",
        "",
        'Run `python3 "$TP_ROOT"/skills/_shared/tool.py validate a.md --flag` first.',
        "",
        "```bash",
        'cd /tmp && python3 "$TP_ROOT"/skills/_shared/tool.py run b.md | tee out.txt',
        "python3 skills/_shared/other.py skip",
        "```",
        "",
        "```",
        "python3 skills/_shared/tool.py plain-fence --x",
        "```",
        "",
    ]))
    assert si.invocations(path, "tool.py") == [
        ["python3", TP, "validate", "a.md", "--flag"],
        ["python3", TP, "run", "b.md"],
        ["python3", "skills/_shared/tool.py", "plain-fence", "--x"],
    ]


def test_placeholders_are_filled_from_a_mapping(tmp_path):
    path = _md(tmp_path, 'Run `python3 "$TP_ROOT"/skills/_shared/tool.py validate '
                         'three-pillars-docs/changes/{design-name}.md --base origin/{base} --other {unknown}`.\n')
    argv = si.invocations(path, "tool.py", fill={"design-name": "demo", "base": "master"})
    assert argv == [["python3", TP, "validate", "three-pillars-docs/changes/demo.md",
                     "--base", "origin/master", "--other", "{unknown}"]]
    assert si.invocations(path, "tool.py")[0][3] == "three-pillars-docs/changes/{design-name}.md"


def test_root_prefix_is_resolved_when_a_root_is_given(tmp_path):
    path = _md(tmp_path, 'Run `python3 "${TP_ROOT}"/skills/_shared/tool.py x` or `python3 "$TP_ROOT"/skills/_shared/tool.py y`.\n')
    got = si.invocations(path, "tool.py", root="/r")
    assert [c[1] for c in got] == ["/r/skills/_shared/tool.py"] * 2


def test_an_unsplittable_span_is_skipped_not_raised(tmp_path):
    path = _md(tmp_path, '`python3 skills/_shared/tool.py "open quote` and `python3 skills/_shared/tool.py ok`.\n')
    assert si.invocations(path, "tool.py") == [["python3", "skills/_shared/tool.py", "ok"]]
