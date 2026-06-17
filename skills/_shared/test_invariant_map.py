"""Tests for invariant_map — canonical map parsed from framework-check.sh headers.

design: invariant-citation-coherence
"""

from __future__ import annotations

from pathlib import Path

import invariant_map
from invariant_map import (
    Invariant,
    active_count,
    parse_invariant_map,
    valid_numbers,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK_CHECK = REPO_ROOT / "framework-check.sh"


# ------------------------------------------------------------------ #
# Parse against the real framework-check.sh — 38/38/{1..38} today
# (invariant-citation-coherence appended inv #38).
# ------------------------------------------------------------------ #


def test_parse_real_framework_check():
    m = parse_invariant_map(FRAMEWORK_CHECK)
    # Today there are exactly 38 active header keys (inv #38 appended).
    assert len(m) == 38
    assert active_count(m) == 38
    assert valid_numbers(m) == set(range(1, 39))


def test_map_values_are_invariant_dataclass():
    m = parse_invariant_map(FRAMEWORK_CHECK)
    one = m[1]
    assert isinstance(one, Invariant)
    assert one.number == 1
    assert one.status == "active"
    assert one.title  # non-empty


def test_no_sidecar_path_read():
    # The design drops the JSON sidecar entirely; it must not exist and must
    # not be required for parsing.
    sidecar = REPO_ROOT / "skills" / "_shared" / "invariant_map.json"
    assert not sidecar.exists()
    # Parsing succeeds from headers alone.
    assert len(parse_invariant_map(FRAMEWORK_CHECK)) == 38


# ------------------------------------------------------------------ #
# Retirement-gap synthetic: inject a retired header into a temp copy.
# ------------------------------------------------------------------ #


def _write_synthetic(tmp_path: Path, extra_lines: str) -> Path:
    original = FRAMEWORK_CHECK.read_text(encoding="utf-8")
    synthetic = tmp_path / "framework-check.sh"
    synthetic.write_text(original + "\n" + extra_lines + "\n", encoding="utf-8")
    return synthetic


def test_retirement_gap_synthetic(tmp_path):
    # Inject a retired header at number 99 (in-range, present, but retired).
    synthetic = _write_synthetic(tmp_path, "# 99. [RETIRED] An old, withdrawn rule")
    m = parse_invariant_map(synthetic)

    # 99 is a valid (present) header number.
    assert 99 in valid_numbers(m)
    assert m[99].status == "retired"
    assert m[99].title == "An old, withdrawn rule"

    # active_count excludes the retired one — still 38 active.
    assert active_count(m) == 38
    # But the total set of header numbers grew by one.
    assert len(valid_numbers(m)) == 39


def test_active_header_synthetic_increments_active_count(tmp_path):
    # A non-retired injected header DOES count toward active_count.
    synthetic = _write_synthetic(tmp_path, "# 99. A brand new active rule")
    m = parse_invariant_map(synthetic)
    assert 99 in valid_numbers(m)
    assert m[99].status == "active"
    assert active_count(m) == 39


def test_retired_marker_requires_exact_position(tmp_path):
    # "[RETIRED]" appearing later in the title (not right after the dot) does
    # NOT retire the invariant — the marker must follow "# N. ".
    synthetic = _write_synthetic(
        tmp_path, "# 99. Some rule that mentions [RETIRED] mid-title"
    )
    m = parse_invariant_map(synthetic)
    assert m[99].status == "active"
    assert active_count(m) == 39
