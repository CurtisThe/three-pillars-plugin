"""The /tp-design design.md template stamps floor 3 and passes the floor validator
(consumer-repo-parity 9.3, converted in 24.5; floor 3 + Forge behaviour in
forge-interface 2.1).

`skills/tp-design/SKILL.md` step 7 carries the canonical `design.md` template. The
template is read as parsed code spans (skill_spans), assembled into a design.md,
and run through the shipped floor validator (`validate_design_floor`) and
`floor_sections`: a drafted design must stamp floor 3 and be accepted, and the
validator must flag it once the Consumer-repo section is dropped, or once a forge
surface is named without the Forge behaviour section. Path/script
references in the SKILL.md are covered by skill_refs (invariant 46). No assert
here reads the SKILL.md's wording, headings or lines.
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
_SKILL_MD = _SHARED.parent / "tp-design" / "SKILL.md"


def _import(name: str):
    if str(_SHARED) not in sys.path:
        sys.path.insert(0, str(_SHARED))
    return pytest.importorskip(name)


def _template_lines() -> list[str]:
    """The step-7 template, rebuilt from the code spans: the contiguous run of
    fenced lines opening at the `---` frontmatter fence."""
    skill_spans = _import("skill_spans")
    spans = list(skill_spans.code_spans(_SKILL_MD.read_text(encoding="utf-8")))
    start = next(i for i, (_, text, _) in enumerate(spans) if text == "---")
    out, last = [], spans[start][0]
    for lineno, text, _ in spans[start:]:
        if lineno - last > 2:
            break
        out.append(text)
        last = lineno
    return out


def _drafted_design(drop_consumer_section: bool = False,
                    drop_forge_section: bool = False) -> str:
    """A design.md as the skill drafts it: the template with its placeholders filled."""
    text = "\n\n".join(_template_lines()) + "\n"
    text = text.replace("<class from step 5b>", "full").replace("<Design Name>", "Demo")
    text = text.replace("- ...", "- a concrete, fully specified item for this slot")
    if drop_consumer_section:
        floor = _import("floor_sections")
        head = f"## {floor.CONSUMER_REPO_SECTION}"
        before, _, rest = text.partition(head)
        text = before + "## Open Questions" + rest.partition("## Open Questions")[2]
    if drop_forge_section:
        floor = _import("floor_sections")
        before, _, rest = text.partition(f"## {floor.FORGE_SECTION}")
        text = before + "## Open Questions" + rest.partition("## Open Questions")[2]
    return text


def _validate(tmp_path: Path, text: str) -> tuple[int, str]:
    vdf = _import("validate_design_floor")
    (tmp_path / "design.md").write_text(text, encoding="utf-8")
    err = io.StringIO()
    with redirect_stderr(err):
        code = vdf.main(["validate_design_floor.py", str(tmp_path)])
    return code, err.getvalue()


def test_template_stamps_floor_three():
    """The drafted design.md carries floor 3 through the shipped floor parser."""
    floor = _import("floor_sections")
    assert floor.floor_version(_drafted_design()) == 3


def test_template_requires_and_passes_consumer_section(tmp_path):
    """The floor-2 requirement set includes the Consumer-repo section, and the
    drafted design passes the validator."""
    floor = _import("floor_sections")
    assert floor.CONSUMER_REPO_SECTION in floor.extra_required(_drafted_design())
    code, err = _validate(tmp_path, _drafted_design())
    assert code == 0, err


def test_validator_flags_design_without_consumer_section(tmp_path):
    """Negative: the same stamped design minus the section is BLOCKED."""
    floor = _import("floor_sections")
    code, err = _validate(tmp_path, _drafted_design(drop_consumer_section=True))
    assert code == 1
    assert floor.CONSUMER_REPO_SECTION in err


def test_drafted_design_naming_a_forge_surface_requires_forge_section(tmp_path):
    """Floor 3: a drafted design that names a forge surface lists Forge behaviour in
    `extra_required`; the template carries the section, so the drafted design passes,
    and dropping the section is BLOCKED."""
    floor = _import("floor_sections")
    named = _drafted_design() + "\nThe flow posts a PR comment on the review.\n"
    assert floor.FORGE_SECTION in floor.extra_required(named)
    code, err = _validate(tmp_path, named)
    assert code == 0, err
    dropped = _drafted_design(drop_forge_section=True) + "\nThe flow posts a PR comment.\n"
    code, err = _validate(tmp_path, dropped)
    assert code == 1
    assert floor.FORGE_SECTION in err


def test_unnamed_drafted_design_does_not_require_forge_section():
    """No forge surface named -> only the Consumer-repo section is required."""
    floor = _import("floor_sections")
    assert floor.FORGE_SECTION not in floor.extra_required(
        _drafted_design(drop_forge_section=True))


def test_write_class_stamps_only_weight_class(tmp_path):
    """impl-audit F9: `weight_class.write_class` writes only the `weight-class` key,
    so the floor stamp must be written directly (the template carries it)."""
    weight_class = _import("weight_class")
    design = tmp_path / "design.md"
    design.write_text("# Design: demo\n", encoding="utf-8")
    weight_class.write_class(design, "full")
    fm = weight_class.parse_frontmatter(design.read_text(encoding="utf-8"))
    assert fm.get("weight-class") == "full" and "floor" not in fm


def test_skill_refs_clean():
    """The SKILL.md this module covered resolves every reference (invariant 46)."""
    skill_refs = _import("skill_refs")
    report = skill_refs.check(_SHARED.parents[1], [_SKILL_MD])
    assert report.issues == []
