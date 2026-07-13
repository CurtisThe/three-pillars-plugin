"""test_ci_local_stamp_config_gate.py — review.require_ci_local_stamp config gate
(Task 3.4, [G3] catalog fix — plugin-mode-parity).

Mirrors `gate_roster._require_review_proof`'s interpreter + OMIT-fold pattern
exactly (tp-merge/SKILL.md:67 precedent): a repo commits
`review.require_ci_local_stamp: false` to opt OUT of the ci_local_stamp
predicate entirely (OMITTED, not FAIL/blocking) so a consumer repo with no
`scripts/ci-local.sh` can land through /tp-merge. Before this fix there was no
config opt-out at all (`grep -rn require_ci_local skills/` == zero hits), so
the predicate permanently FAILed on every consumer repo — [G3], HARMFUL.

See also:
  test_gate_roster.py             — RosterEntry / render_roster unit tests
  test_gate_roster_integration.py — evaluate_gate roster wiring
  test_proof_gate_fold.py         — the _require_review_proof precedent this mirrors
"""
from __future__ import annotations

import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))


# ---------------------------------------------------------------------------
# _require_ci_local_stamp interpreter (mirrors _require_review_proof exactly)
# ---------------------------------------------------------------------------

def test_require_ci_local_stamp_default_true():
    from gate_roster import _require_ci_local_stamp
    assert _require_ci_local_stamp(None) is True
    assert _require_ci_local_stamp({}) is True
    assert _require_ci_local_stamp({"review": {}}) is True


def test_require_ci_local_stamp_non_dict_review_true():
    from gate_roster import _require_ci_local_stamp
    assert _require_ci_local_stamp({"review": "garbage"}) is True


def test_require_ci_local_stamp_explicit_false():
    from gate_roster import _require_ci_local_stamp
    assert _require_ci_local_stamp({"review": {"require_ci_local_stamp": False}}) is False


def test_require_ci_local_stamp_explicit_true():
    from gate_roster import _require_ci_local_stamp
    assert _require_ci_local_stamp({"review": {"require_ci_local_stamp": True}}) is True


# ---------------------------------------------------------------------------
# Wiring: evaluate_gate OMITs ci_local_stamp when the config opts out.
# ---------------------------------------------------------------------------

_RUNNERS = {
    "pr_state_fn": lambda url: {
        "mergeable": "MERGEABLE",
        "headRefOid": "deadbeefcafe",
        "statusCheckRollup": [],
    },
    "threads_fn": lambda url: [],
}

_BASE_CONFIG = {
    "review": {"expects_copilot": False, "require_human_approval": False,
               "require_review_proof": False},
    "ci": {"expects_github_checks": False},
}


def _roster_entry(outcome, name):
    entry = next((e for e in outcome.roster if e.name == name), None)
    assert entry is not None, f"no roster entry named {name!r}; roster={outcome.roster!r}"
    return entry


def test_ci_local_stamp_omitted_when_config_opts_out():
    """[G3] fix: review.require_ci_local_stamp: false OMITs the predicate — no
    scripts/ci-local.sh stamp is required to satisfy it."""
    from deterministic_gate import evaluate_gate

    config = {
        **_BASE_CONFIG,
        "review": {**_BASE_CONFIG["review"], "require_ci_local_stamp": False},
    }
    outcome = evaluate_gate(
        "https://example.com/pr/1", runners=dict(_RUNNERS), config=config,
    )
    entry = _roster_entry(outcome, "ci_local_stamp")
    assert entry.status == "OMITTED", (
        f"ci_local_stamp must be OMITTED when review.require_ci_local_stamp=false; "
        f"got {entry.status} ({entry.detail})"
    )
    assert "require_ci_local_stamp=false" in entry.detail


def test_ci_local_stamp_still_active_by_default_when_stamp_injected():
    """Regression: with NO opt-out configured, the strict default is unchanged —
    an injected stamp key still drives the predicate exactly as before this fix."""
    from deterministic_gate import evaluate_gate

    runners = dict(_RUNNERS)
    runners["stamp"] = {"schema": 1, "head_sha": "deadbeefcafe", "dirty": False}
    outcome = evaluate_gate(
        "https://example.com/pr/1", runners=runners, config=_BASE_CONFIG,
    )
    entry = _roster_entry(outcome, "ci_local_stamp")
    assert entry.status != "OMITTED", (
        f"ci_local_stamp must remain ACTIVE by default when a stamp is injected; "
        f"got {entry.status} ({entry.detail})"
    )


def test_ci_local_stamp_still_hermetic_inactive_by_default_no_stamp_no_optout():
    """Regression: with no opt-out AND no injected stamp/live-mode, the pre-existing
    hermetic-inactive OMIT reason is unchanged (byte-identical detail string)."""
    from deterministic_gate import evaluate_gate

    outcome = evaluate_gate(
        "https://example.com/pr/1", runners=dict(_RUNNERS), config=_BASE_CONFIG,
    )
    entry = _roster_entry(outcome, "ci_local_stamp")
    assert entry.status == "OMITTED"
    assert entry.detail == "<stamp> inactive (hermetic run — no stamp key injected)"
