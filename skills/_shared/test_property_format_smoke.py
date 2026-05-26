"""Round-trip + idempotence + count tests for the six Notion property-format transforms.

The PUBLIC three-pillars substrate never serializes Notion properties (no Notion
knowledge in public substrate). This module is documentation-as-test: it asserts the
six `property_format.TRANSFORMS` entries (`number_raw`, `datetime_iso`,
`select_with_emoji`, `relation_uuid_array`, `person_uuid_array`, `checkbox_bool` —
these address the v3-audit gotchas number-raw, datetime-int, select-with-emoji,
relation-as-url-array-string, person-as-uuid-array-string, checkbox-as-YES-NO; see
`property_format.py`'s docstring for the mapping) each round-trip and are idempotent.
The private plugin's `notion-format-smoke` CI imports `property_format.TRANSFORMS`
to verify its writer matches this public reference, anchoring the format count at
six in a single place.

See: three-pillars-docs/completed-tp-designs/substrate-test-harness/detailed-design.md §Interfaces

Run with: pytest skills/_shared/test_property_format_smoke.py -q
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Module under test lives alongside this file.
sys.path.insert(0, str(Path(__file__).parent))

from property_format import CANONICAL_EXAMPLES, TRANSFORMS  # noqa: E402


def _flatten(transforms: dict) -> list[tuple[str, object, object]]:
    """Yield (name, forward, inverse) triples for parametrize."""
    return [(name, fwd, inv) for name, (fwd, inv) in transforms.items()]


@pytest.mark.parametrize("name,forward,inverse", _flatten(TRANSFORMS))
def test_round_trip(name: str, forward, inverse) -> None:
    """inverse(forward(input)) == input for the canonical input."""
    canonical_input, _ = CANONICAL_EXAMPLES[name]
    assert inverse(forward(canonical_input)) == canonical_input


@pytest.mark.parametrize("name,forward,inverse", _flatten(TRANSFORMS))
def test_idempotence(name: str, forward, inverse) -> None:
    """forward(inverse(payload)) == payload for the canonical payload."""
    _, canonical_payload = CANONICAL_EXAMPLES[name]
    assert forward(inverse(canonical_payload)) == canonical_payload


def test_anchored_count() -> None:
    """The six-transform contract is the single source of truth.

    Adding a seventh requires coordinated update with the private plugin's
    `notion-format-smoke` CI. Anchors v3 audit M2 and v4 audit clarification 3.
    """
    assert len(TRANSFORMS) == 6


def test_anchored_count_boundary_low(monkeypatch: pytest.MonkeyPatch) -> None:
    """If TRANSFORMS shrinks to 5, the count assertion fires."""
    import property_format
    shrunk = {k: v for k, v in list(TRANSFORMS.items())[:5]}
    monkeypatch.setattr(property_format, "TRANSFORMS", shrunk)
    assert len(property_format.TRANSFORMS) == 5
    with pytest.raises(AssertionError):
        assert len(property_format.TRANSFORMS) == 6


def test_anchored_count_boundary_high(monkeypatch: pytest.MonkeyPatch) -> None:
    """If TRANSFORMS grows to 7, the count assertion fires."""
    import property_format
    grown = dict(TRANSFORMS)
    grown["dummy_seventh"] = (lambda x: x, lambda x: x)
    monkeypatch.setattr(property_format, "TRANSFORMS", grown)
    assert len(property_format.TRANSFORMS) == 7
    with pytest.raises(AssertionError):
        assert len(property_format.TRANSFORMS) == 6


def test_standalone_importable() -> None:
    """`property_format` imports cleanly from stdlib + project-local code only.

    Guards the private plugin's import contract — if `property_format.py`
    accidentally pulls in pytest, jsonschema, or orchestrator modules at
    import time, the private plugin's CI breaks silently.
    """
    module_dir = Path(__file__).parent
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import property_format; assert hasattr(property_format, 'TRANSFORMS'); "
            "assert len(property_format.TRANSFORMS) == 6",
        ],
        cwd=str(module_dir),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"standalone import failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
