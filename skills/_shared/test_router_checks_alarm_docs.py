"""Part 3: the router_checks docstring and cheap-tier.md name both alarm kinds and both exit-1 causes."""
from __future__ import annotations

from pathlib import Path

import router_checks

ROOT = Path(__file__).resolve().parents[2]
CHEAP_TIER = ROOT / "skills" / "tp-run-full-design" / "cheap-tier.md"


def test_docstring_names_both_alarm_kinds():
    doc = router_checks.__doc__
    assert "alarm=" in doc
    assert "alarm=ratio" in doc and "main_thread_strata" in doc


def test_cheap_tier_names_both_alarm_kinds_at_tier_1_and_tier_5():
    exit_lines = [ln for ln in CHEAP_TIER.read_text(encoding="utf-8").splitlines()
                  if "exit 1" in ln and ("never gates" in ln or "never a gate" in ln)]
    assert len(exit_lines) >= 2
    for ln in exit_lines:
        assert "alarm=ratio" in ln and "main_thread_strata" in ln
