"""Tests for angles.build_prompt's test-fragility.md citation and finding-shape fields.

design: fragile-test-prevention (Task 9.3)

Every assertion here is structural: it parses the prompt's own grammar (code
spans, the shape line's braces, the balanced parens after a class marker)
rather than pinning exact wording, per `skills/_shared/test-fragility.md`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
_SHARED = Path(__file__).resolve().parents[2] / "_shared"
sys.path.insert(0, str(_SHARED))

import angles  # noqa: E402
import finding_fields  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_FRAGILITY_PATH = (_SHARED / "test-fragility.md").resolve()

assert TEST_FRAGILITY_PATH.is_file(), "fixture doc must exist for this test to mean anything"


def _code_spans(text: str) -> list[str]:
    return re.findall(r"`([^`]+)`", text)


def _resolves_to_test_fragility(span: str) -> bool:
    try:
        candidate = (REPO_ROOT / span).resolve()
    except (OSError, ValueError):
        return False
    return candidate == TEST_FRAGILITY_PATH


def _balanced_paren_entry(text: str, marker: str) -> str:
    """The text inside the balanced parens that immediately follow `marker`."""
    start = text.index(marker) + len(marker)
    depth = 1
    i = start
    while depth:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
        i += 1
    return text[start:i - 1]


def _prompt_for(angle: dict) -> str:
    return angles.build_prompt(angle, base="b0", head="h1", effort="high",
                                reply_path="/r/reply.md")


def _shape_line(prompt: str) -> str:
    for line in prompt.splitlines():
        if line.startswith("Each finding is"):
            return line
    raise AssertionError("no shape line found in prompt")


@pytest.mark.parametrize("angle", angles.DEFAULT_ANGLES, ids=[a["name"] for a in angles.DEFAULT_ANGLES])
def test_prompt_cites_test_fragility_doc(angle):
    prompt = _prompt_for(angle)
    spans = _code_spans(prompt)
    assert any(_resolves_to_test_fragility(s) for s in spans)


@pytest.mark.parametrize("angle", angles.DEFAULT_ANGLES, ids=[a["name"] for a in angles.DEFAULT_ANGLES])
def test_finding_shape_lists_origin_and_fragility_class(angle):
    shape = _shape_line(_prompt_for(angle))
    fields_segment = shape.split("{", 1)[1].split("}", 1)[0]
    assert re.search(r"\borigin\b", fields_segment)
    assert re.search(r"\bfragility_class\b", fields_segment)


@pytest.mark.parametrize("angle", angles.DEFAULT_ANGLES, ids=[a["name"] for a in angles.DEFAULT_ANGLES])
def test_enum_values_match_registry(angle):
    shape = _shape_line(_prompt_for(angle))
    origin_match = re.search(r"origin is one of \{([^}]*)\}", shape)
    fragility_match = re.search(r"fragility_class is one of \{([^}]*)\}", shape)
    assert origin_match is not None
    assert fragility_match is not None
    assert tuple(origin_match.group(1).split("|")) == finding_fields.ORIGINS
    assert tuple(fragility_match.group(1).split("|")) == finding_fields.FRAGILITY_CLASSES


@pytest.mark.parametrize("angle", angles.DEFAULT_ANGLES, ids=[a["name"] for a in angles.DEFAULT_ANGLES])
def test_class_t_entry_cites_test_fragility_doc(angle):
    shape = _shape_line(_prompt_for(angle))
    entry = _balanced_paren_entry(shape, "T (")
    spans = _code_spans(entry)
    assert any(_resolves_to_test_fragility(s) for s in spans)
