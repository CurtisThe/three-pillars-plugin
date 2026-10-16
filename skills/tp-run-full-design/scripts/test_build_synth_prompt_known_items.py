"""Tests for build_synth_prompt known items (review-convergence 9.2).

Carried per-phase-check findings render as KNOWN input for the synthesizer, so
it never re-raises one as a new find. Design: review-convergence; see
skills/_shared/test-fragility.md — assert the exact rendered lines and block
placement, not a substring soup of the whole prompt.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_synth_prompt import build_synth_prompt  # noqa: E402

HEADING = "## Known items (per-phase check)"


def _args(slot="impl-audit"):
    r1 = [{"member": "council-ada", "verdict": "pass-with-notes", "findings": []}]
    return (["a.md"], r1, None, slot)


def _carry(design_dir: Path, items: list) -> None:
    (design_dir / "phase-check-carry.json").write_text(
        json.dumps({"items": items}), encoding="utf-8")


UNFIXED = {"phase": "3", "id": "f1", "file": "skills/x.py", "line_range": "10-12",
           "summary": "producer writes one key, consumer reads another",
           "blocking": True, "status": "unfixed"}
DISPUTED = {"phase": "5", "id": "f2", "file": "skills/y.py", "line_range": "4-4",
            "summary": "cache wedge hides the drift", "blocking": False,
            "status": "disputed", "reason": "reproducer does not reproduce"}


def test_carry_items_render_as_known(tmp_path):
    # Red fixture: a design dir whose phase-check-carry.json carries two items.
    _carry(tmp_path, [UNFIXED, DISPUTED])
    out = build_synth_prompt(*_args(), design_dir=tmp_path)
    lines = out.splitlines()
    assert HEADING in lines
    i = lines.index(HEADING)
    assert ("- [phase 3] f1 skills/x.py:10-12 — producer writes one key, "
            "consumer reads another (unfixed)") in lines
    assert ("- [phase 5] f2 skills/y.py:4-4 — cache wedge hides the drift "
            "(disputed) — disputed: reproducer does not reproduce") in lines
    # The block says the items are KNOWN, not new finds.
    assert "KNOWN" in "\n".join(lines[i:i + 3])
    # The block sits before "## Round 1 — independent verdicts".
    assert i < lines.index("## Round 1 — independent verdicts")


def test_no_carry_file_means_no_block(tmp_path):
    out = build_synth_prompt(*_args(), design_dir=tmp_path)
    assert HEADING not in out


def test_design_dir_none_means_no_block():
    out = build_synth_prompt(*_args())
    assert HEADING not in out
