"""Topology and driver docs point to strata-finders.md (local-role-routing 6.9)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

import skill_text  # noqa: E402

SKILLS = Path(__file__).resolve().parents[2]
TOPOLOGY = (SKILLS / "tp-pr-iterate" / "round-topology.md").read_text(encoding="utf-8")
ITERATE = (SKILLS / "tp-pr-iterate" / "SKILL.md").read_text(encoding="utf-8")
RUN_FULL = skill_text.read_skill_text("tp-run-full-design")


def _step(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i : text.index(end, i)]


def test_topology_step2_names_round_angles():
    step = _step(TOPOLOGY, "2. **Orchestrator: angle fan-out.**", "3. **Round tail.**")
    assert "finder_round.round_angles" in step
    assert "strata-finders.md" in step


def test_topology_step3_names_opus_check():
    step = _step(TOPOLOGY, "3. **Round tail.**", "\n## ")
    assert "opus-check" in step
    assert "strata-finders.md" in step


def test_both_drivers_point_to_strata_finders():
    assert "strata-finders.md" in ITERATE
    assert "strata-finders.md" in RUN_FULL


def test_run_full_pointer_in_tier7_section():
    m = re.search(r"^## Tier 7 .*?(?=^## )", RUN_FULL, re.S | re.M)
    assert m and "strata-finders.md" in m.group(0)
