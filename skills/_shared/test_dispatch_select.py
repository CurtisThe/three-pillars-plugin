"""Tests for dispatch_select.enforce_floor — the gate-role floor.

design: run-throughput (Task 3.5, Part A §Floors). `enforce_floor(role, agent,
config=None)` never raises: a non-gate role is unchanged with no note; an
unknown agent is unchanged with a `floor-unchecked` note; an effort below the
floor (or, for `impl-audit`/`certify`, a non-`PINNED` model) substitutes
`role_agent(role)` with a `floor-substituted` note; `review`'s model is never
substituted — only its effort is floored, and a configured non-`PINNED`
`models.review` is kept with a `floor-note`. The CLI `floor --role R --agent
A [--root .]` prints one JSON object `{agent, note}` and always exits 0.
Run with: python3 -m pytest skills/_shared/test_dispatch_select.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dispatch_select as ds  # noqa: E402

_MODULE_PATH = Path(__file__).resolve().parent / "dispatch_select.py"


# --- non-gate role: unchanged, no note ---------------------------------------

def test_non_gate_role_unchanged_no_note():
    assert ds.enforce_floor("reader", "general-purpose") == ("general-purpose", None)


# --- unknown agent: floor-unchecked -------------------------------------------

def test_unknown_agent_is_floor_unchecked():
    agent, note = ds.enforce_floor("review", "general-purpose")
    assert agent == "general-purpose"
    assert note == "floor-unchecked: general-purpose not in model_policy.AGENTS"


# --- effort below floor: floor-substituted ------------------------------------

def test_effort_below_floor_substitutes_impl_audit():
    assert ds.enforce_floor("impl-audit", "tp-readonly-auditor") == (
        "tp-impl-auditor",
        "floor-substituted: tp-readonly-auditor → tp-impl-auditor",
    )


def test_effort_below_floor_substitutes_review():
    # Q2: the review floor is high (round 1 runs the xhigh -deep variant above it).
    agent, note = ds.enforce_floor("review", "tp-task-worker-local-medium")
    assert agent == "tp-review-confirmer"
    assert note == "floor-substituted: tp-task-worker-local-medium → tp-review-confirmer"


def test_review_finder_agent_keeps_medium_under_review_floor():
    # M65: `floor --role review --agent tp-review-confirmer-medium` printed the base agent.
    assert ds.enforce_floor("review", "tp-review-confirmer-medium") == (
        "tp-review-confirmer-medium",
        None,
    )


def test_review_finder_cli_keeps_medium_agent():
    import json
    import subprocess
    out = subprocess.run(
        [sys.executable, str(_MODULE_PATH), "floor", "--role", "review",
         "--agent", "tp-review-confirmer-medium"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert json.loads(out) == {"agent": "tp-review-confirmer-medium", "note": None}


def test_already_at_floor_is_unchanged_no_note():
    assert ds.enforce_floor("impl-audit", "tp-impl-auditor") == ("tp-impl-auditor", None)


# --- model below PINNED (impl-audit/certify only): floor-substituted ---------

def test_model_below_pinned_substitutes_certify():
    agent, note = ds.enforce_floor("certify", "tp-task-worker-sonnet-xhigh")
    assert agent == "tp-certifier"
    assert note == "floor-substituted: tp-task-worker-sonnet-xhigh → tp-certifier"


# --- review: model never substituted, only effort floored -------------------

def test_review_configured_non_pinned_model_kept_with_floor_note():
    agent, note = ds.enforce_floor(
        "review", "tp-review-confirmer", {"models": {"review": "sonnet"}}
    )
    assert agent == "tp-review-confirmer"
    assert note == "floor-note: models.review=sonnet (configured)"


def test_review_default_model_no_note():
    assert ds.enforce_floor("review", "tp-review-confirmer") == (
        "tp-review-confirmer",
        None,
    )


# --- CLI: prints {agent, note}, never raises ---------------------------------

def test_cli_floor_prints_agent_and_note(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(_MODULE_PATH), "floor",
         "--role", "impl-audit", "--agent", "tp-readonly-auditor",
         "--root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload == {
        "agent": "tp-impl-auditor",
        "note": "floor-substituted: tp-readonly-auditor → tp-impl-auditor",
    }


def test_cli_floor_unknown_role_and_agent_still_exits_zero(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(_MODULE_PATH), "floor",
         "--role", "no-such-role", "--agent", "no-such-agent",
         "--root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload == {"agent": "no-such-agent", "note": None}
