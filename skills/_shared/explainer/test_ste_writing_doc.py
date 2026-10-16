"""test_ste_writing_doc.py — the STE-80 style guide states the lint's numbers and words.

Covers explainer-agent plan Task 3.4: "Assert ste-writing.md names each
threshold number from ste_lint (25, 20, 30 words; 20 % passive; 10 % soft
misses), contains every word in ste_lint.BANNED, and states the honesty rule
("every claim cites evidence"; never "safe to merge")."

The numbers, the banned entries and the pr-brief section ids are read from the
shipped registries (ste_lint's public int constants and BANNED,
explain_envelope.REQUIRED_SECTIONS), never copied here, so a change to the
lint fails this test until the guide follows it
(skills/_shared/test-fragility.md §2, fix 4). A threshold counts as stated
when one guide line names its constant in backticks and gives its value.

The guide is found from this file's own path: it ships in skills/_shared
beside the explainer package, so no repo doc tree is read.
"""
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import explain_envelope  # noqa: E402
import ste_lint  # noqa: E402

GUIDE = _SHARED_DIR / "ste-writing.md"


def _thresholds() -> dict:
    """ste_lint's public int constants: its thresholds, by name."""
    return {name: value for name, value in vars(ste_lint).items()
            if name.isupper() and not name.startswith("_")
            and type(value) is int}


def _guide_text() -> str:
    assert GUIDE.is_file(), f"missing style guide: {GUIDE}"
    return GUIDE.read_text(encoding="utf-8")


def _normalized(text: str) -> str:
    return " ".join(text.split()).lower()


def test_lint_exposes_its_thresholds_as_constants():
    assert _thresholds(), "ste_lint has no public int threshold constants"


@pytest.mark.parametrize("name", sorted(_thresholds()))
def test_guide_states_each_threshold_by_constant_and_value(name):
    value = _thresholds()[name]
    number = re.compile(rf"(?<![\d.]){value}(?![\d.])")
    lines = [ln for ln in _guide_text().splitlines() if f"`{name}`" in ln]
    assert lines, f"ste-writing.md never names `{name}`"
    assert any(number.search(ln) for ln in lines), (
        f"ste-writing.md names `{name}` but not its value {value}")


@pytest.mark.parametrize("entry", ste_lint.BANNED)
def test_guide_lists_every_banned_entry(entry):
    assert f"`{entry}`" in _guide_text(), (
        f"ste-writing.md does not list the banned entry `{entry}`")


@pytest.mark.parametrize("section_id",
                         explain_envelope.REQUIRED_SECTIONS["pr-brief"])
def test_guide_lists_every_pr_brief_section(section_id):
    assert f"`{section_id}`" in _guide_text(), (
        f"ste-writing.md does not list the pr-brief section `{section_id}`")


def test_guide_states_the_honesty_rule():
    text = _normalized(_guide_text())
    assert "every claim cites evidence" in text
    assert '"safe to merge"' in text
