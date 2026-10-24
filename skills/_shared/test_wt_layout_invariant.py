"""Invariant 51: the real shipped tree scans clean and framework-check.sh wires the scan."""
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import wt_layout_scan  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
FC = REPO_ROOT / "framework-check.sh"
_needs_fc = pytest.mark.skipif(
    not FC.is_file(), reason="reads framework-check.sh (dev-repo only)")


def test_real_tree_scans_clean():
    assert wt_layout_scan.main([str(REPO_ROOT / "skills"), str(REPO_ROOT / "agents")]) == 0


@_needs_fc
def test_inv51_block_is_fail_closed():
    text = FC.read_text(encoding="utf-8")
    assert "\n# 51. " in text
    block = text[text.index("\n# 51. "):].split('if [[ "$ERRORS" -gt 0 ]]')[0].split("\n# 52. ")[0]
    assert "wt_layout_scan.py" in block
    assert "fail " in block
    assert "warn" not in block


@_needs_fc
def test_inv51_is_active():
    from invariant_map import parse_invariant_map

    assert parse_invariant_map(FC)[51].status == "active"
