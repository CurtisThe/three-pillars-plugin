"""Tests for the tp-finalizer agent's model_policy row and agent surface.

design: fable-first-stops (Task 1.2). The finalizer is its own
`model_policy` role with a literal `fable` model source (never a default,
operator ruling 2026-09-26) and the Opus-xhigh fallback constant; the
shipped `agents/tp-finalizer.md` has no drift against the policy table and
resolves through `agent_ref`.
Run with: python3 -m pytest skills/_shared/test_finalizer_agent_policy.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_ref  # noqa: E402
import agent_variants as av  # noqa: E402
import model_policy as mp  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_agent_spec_resolves_to_finalizer_role_fable_high():
    assert mp.agent_spec("tp-finalizer") == {
        "role": "finalizer",
        "model": "fable",
        "effort": "high",
    }


def test_finalizer_fallback_is_opus_xhigh():
    assert mp.FINALIZER_FALLBACK == {"model": "opus", "effort": "xhigh"}


def test_role_agent_finalizer_is_tp_finalizer():
    assert mp.role_agent("finalizer") == "tp-finalizer"


def test_agent_alias_fable_is_fable():
    assert mp.agent_alias("fable") == "fable"


def test_agent_variants_reports_no_finalizer_drift():
    drift = av.check(REPO_ROOT)
    assert not [line for line in drift if "tp-finalizer" in line]


def test_agent_ref_resolves_tp_finalizer():
    ref = agent_ref.resolve("tp-finalizer", REPO_ROOT)
    assert ref.endswith(":tp-finalizer")
