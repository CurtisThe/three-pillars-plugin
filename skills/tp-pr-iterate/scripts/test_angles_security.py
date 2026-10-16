"""angles.security_angle — the security lens entry (review-convergence 4.1).

design: review-convergence (detailed-design-security.md, Phase 4)

Assertions are structural, per `skills/_shared/test-fragility.md`: the bar is
compared against the imported `trust_boundary.SECURITY_BAR` constant (the one
shared text), never a duplicated literal, so rewording the bar cannot break this
test while a dropped bar still fails it.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import angles  # noqa: E402
import trust_boundary  # noqa: E402

SURFACES = [{"surface": "credentials", "path": "a.py", "line": 7,
             "text": "token = os.environ['GH_TOKEN']", "removed": False}]


def test_angle_name_is_the_security_constant():
    assert angles.SECURITY_ANGLE == "security"
    assert angles.security_angle(Path("b.md"), SURFACES)["name"] == angles.SECURITY_ANGLE


def test_role_is_confirmer_and_model_is_opus():
    """A confirmer on literal `opus`: it signs the proof and is never a cheap finder."""
    entry = angles.security_angle(Path("b.md"), SURFACES)
    assert entry["role"] == "confirmer"
    assert entry["model"] == "opus"


def test_prompt_carries_brief_path_and_shared_bar():
    prompt = angles.security_angle(Path("b.md"), SURFACES)["prompt"]
    assert "b.md" in prompt
    assert trust_boundary.SECURITY_BAR in prompt


def test_prompt_lists_the_surfaces_the_detector_found():
    prompt = angles.security_angle(Path("b.md"), SURFACES)["prompt"]
    assert "credentials a.py" in prompt


def test_prompt_with_no_surfaces_still_carries_the_bar():
    """Round 1 appends the angle whatever the detector found, so the empty case works."""
    entry = angles.security_angle(Path("briefs/SECURITY.md"), [])
    assert trust_boundary.SECURITY_BAR in entry["prompt"]
    assert "briefs/SECURITY.md" in entry["prompt"]


def test_entry_passes_the_angle_validation_floor():
    """The entry is a valid angle for `load_angles`/`dispatch_model` unchanged."""
    entry = angles.security_angle(Path("b.md"), SURFACES)
    assert angles.tier(entry) == "claude"
    assert angles._validate(dict(entry), set())["model"] == "opus"
