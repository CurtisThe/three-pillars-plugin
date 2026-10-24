"""Light and just-do-it runs close out in one dispatch (design light-run-ceremony-diet, task 1.8).

Oracle: example, per `skills/_shared/test-fragility.md`. Load-bearing literals only: no heading-text
equality, section counts or order pins.

Run with: python3 -m pytest test_light_closeout_doc.py -q (from this directory)
"""
from __future__ import annotations

from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]


def _sections(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if line.startswith("### "):
            out.append((line, []))
        elif line.startswith("#"):
            out.append((line, []))
        elif out:
            out[-1][1].append(line)
    return [(h, "\n".join(b)) for h, b in out]


def _closeout() -> list[tuple[str, str]]:
    return _sections((SKILL_DIR / "tier-5-closeout.md").read_text(encoding="utf-8"))


def test_light_justdoit_closeout_section_dispatches_both_skills_once():
    hits = [b for h, b in _closeout() if h.startswith("###") and "just-do-it" in h]
    assert hits, "no light / just-do-it closeout section"
    body = hits[0]
    for literal in ("tp-generator", "/tp-design-learn", "/tp-design-complete",
                    "generator-return", "BLOCKED"):
        assert literal in body, literal


def test_full_weight_step3_sections_remain():
    heads = [h for h, _ in _closeout() if "Step 3" in h]
    assert any("design-learn" in h for h in heads)
    assert any("/tp-design-complete {slug} --auto" in h for h in heads)


def test_skill_md_points_at_the_closeout_section():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "tier-5-closeout.md" in text
    assert "one closeout dispatch" in text
