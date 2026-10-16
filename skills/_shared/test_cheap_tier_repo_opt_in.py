"""test_cheap_tier_repo_opt_in.py — this repo opts in; the shipped defaults are on too.

design: none (just-do-it, operator 2026-09-30: "start using the GPU more sooner").

The framework repo's own `.three-pillars/config.json` turns on EVERY cheap-tier slot
EXCEPT `handoff`, which stays on Opus (operator 2026-10-07: "the handoff being opus is
probably necessary"). Operator 2026-10-06 ("I want all. Save tokens.") turned on the
kept-off `pr_fix_reproducer` / `classifier_judge`; both stay inert
until their own gates hold: the classifier's eval verdict file, an in-loop spawn site) and
makes its design runs carry `--cheap-tier` (`cheap_tier.default_run_flag`). The plugin ships no repo config, and
operator 2026-10-07 shipped a rung on every `SLOTS[...].default` but `handoff` — so an
empty config loads the same 11 slots this repo names explicitly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import cheap_tier  # noqa: E402
import launch_design_run as ldr  # noqa: E402

CONFIG = _SHARED.parents[1] / ".three-pillars" / "config.json"
OPTED_IN = {"task": "sonnet-xhigh", "runbook": "code", "base_sync_splice": "local-xhigh",
            "history_line": "local-medium",
            "docs_draft": "local-medium",
            "pr_fix_reproducer": "local-xhigh", "classifier_judge": "local-medium"}


SHIPPED_ON = {s: row.default for s, row in cheap_tier.SLOTS.items()  # every slot but handoff
              if row.default is not None}


def test_shipped_defaults_are_every_slot_but_handoff():
    assert SHIPPED_ON == {s: row.rungs[0] for s, row in cheap_tier.SLOTS.items()
                          if s != "handoff"}
    assert cheap_tier.load_slots({"schema_version": 1}) == SHIPPED_ON
    assert ldr.default_cheap_tier({"schema_version": 1}) == "on"


def test_each_opted_in_rung_is_the_local_first_rung_the_table_allows():
    for slot, rung in OPTED_IN.items():
        rungs = cheap_tier.SLOTS[slot].rungs
        assert rung == ("local-medium" if "local-medium" in rungs else rungs[0]), slot


def test_this_repo_opts_in():
    if not CONFIG.is_file():  # a plugin install ships no repo config
        pytest.skip("no .three-pillars/config.json in this tree")
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert cheap_tier.load_slots(raw) == {**SHIPPED_ON, **OPTED_IN}
    assert set(cheap_tier.load_slots(raw)) == set(cheap_tier.SLOTS) - {"handoff"}  # all but handoff (Opus)
    assert ldr.default_cheap_tier(raw) == "on"  # #202: ab ran a redundant Opus shadow arm (seed ab-real-path-is-opus-arm)
