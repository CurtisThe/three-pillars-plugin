"""test_ci_local_stamp_config_gate.py — the ci_local_stamp activation rule (Task 2.2).

The stamp predicate is REQUIRED only on an explicit `review.require_ci_local_stamp:
true` OR a declared non-empty `ci.gate_command`; otherwise it is OMITTED with a
roster note naming how to enable it (part B §H1). Precedence, first match wins
(detailed-design §Interfaces `gate_roster._require_ci_local_stamp`):

  review.require_ci_local_stamp is False → False
  else review.require_ci_local_stamp is True → True
  else ci.gate_command is a non-empty string → True
  else False

This REPLACES the pre-2.2 default-on posture (mirroring `_require_review_proof`)
where a missing/absent config folded to True. The explicit opt-out
(`require_ci_local_stamp: false`) is still honored and still OMITs.

See also:
  test_gate_roster.py             — RosterEntry / render_roster unit tests
  test_gate_roster_integration.py — evaluate_gate roster wiring
  test_proof_gate_fold.py         — the _require_review_proof precedent
"""
from __future__ import annotations

import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))


# ---------------------------------------------------------------------------
# _require_ci_local_stamp activation rule (Task 2.2 precedence table)
# ---------------------------------------------------------------------------

def test_require_ci_local_stamp_default_off():
    """No explicit require AND no ci.gate_command → NOT required (default off)."""
    from gate_roster import _require_ci_local_stamp
    assert _require_ci_local_stamp(None) is False
    assert _require_ci_local_stamp({}) is False
    assert _require_ci_local_stamp({"review": {}}) is False


def test_require_ci_local_stamp_non_dict_review_false():
    """A non-dict `review` cannot carry an explicit true → falls to the command check."""
    from gate_roster import _require_ci_local_stamp
    assert _require_ci_local_stamp({"review": "garbage"}) is False


def test_require_ci_local_stamp_explicit_false_wins():
    """An explicit False OMITS the predicate EVEN when a command is declared
    (first match wins: `is False` short-circuits the command check)."""
    from gate_roster import _require_ci_local_stamp
    assert _require_ci_local_stamp({"review": {"require_ci_local_stamp": False}}) is False
    assert _require_ci_local_stamp({
        "review": {"require_ci_local_stamp": False},
        "ci": {"gate_command": "make ci"},
    }) is False


def test_require_ci_local_stamp_explicit_true_no_command():
    """An explicit True REQUIRES the predicate with NO command declared."""
    from gate_roster import _require_ci_local_stamp
    assert _require_ci_local_stamp({"review": {"require_ci_local_stamp": True}}) is True
    assert _require_ci_local_stamp({
        "review": {"require_ci_local_stamp": True},
        "ci": {},
    }) is True


def test_require_ci_local_stamp_command_declared():
    """A non-empty ci.gate_command REQUIRES the predicate with no explicit require;
    the explicit require key still wins both ways (claim g-h1-activation pins the
    full activation rule in this one node: explicit true → required with no
    command, explicit false → omitted even with a command declared)."""
    from gate_roster import _require_ci_local_stamp
    assert _require_ci_local_stamp({"ci": {"gate_command": "make ci"}}) is True, (
        "STAMP-ACTIVATION: declared gate command did not activate the stamp"
    )
    assert _require_ci_local_stamp({"review": {}, "ci": {"gate_command": "make ci"}}) is True, (
        "STAMP-ACTIVATION: empty review block suppressed the declared-command activation"
    )
    # Explicit true activates with NO command declared.
    assert _require_ci_local_stamp({"review": {"require_ci_local_stamp": True}}) is True, (
        "STAMP-ACTIVATION: explicit require true did not activate the stamp"
    )
    assert _require_ci_local_stamp({
        "review": {"require_ci_local_stamp": True}, "ci": {"gate_command": "  "},
    }) is True, "STAMP-ACTIVATION: explicit require true lost to a blank gate command"
    # Explicit false omits EVEN WITH a command declared (first match wins).
    assert _require_ci_local_stamp({
        "review": {"require_ci_local_stamp": False}, "ci": {"gate_command": "make ci"},
    }) is False, "STAMP-ACTIVATION: explicit require false did not override the command"
    # Default OFF: neither an explicit true nor a non-blank command → NOT required,
    # including a present review block with no require key.
    for cfg in ({}, {"review": {}}, {"review": {}, "ci": {}},
                {"review": {"expects_copilot": False}, "ci": {"gate_command": "   "}}):
        assert _require_ci_local_stamp(cfg) is False, (
            f"STAMP-ACTIVATION: default-off breached — required with no opt-in: {cfg!r}")


def test_require_ci_local_stamp_command_missing_null_or_blank_false():
    """A missing key, a null value, and a blank string all fold to NOT required."""
    from gate_roster import _require_ci_local_stamp
    assert _require_ci_local_stamp({"ci": {}}) is False
    assert _require_ci_local_stamp({"ci": {"gate_command": None}}) is False
    assert _require_ci_local_stamp({"ci": {"gate_command": ""}}) is False
    assert _require_ci_local_stamp({"ci": None}) is False


def test_require_ci_local_stamp_non_bool_require_ignores():
    """A non-bool require (0/1/\"false\") is not `is False`/`is True` → command decides."""
    from gate_roster import _require_ci_local_stamp
    # require=1 is not `is True` → falls to the (absent) command → False
    assert _require_ci_local_stamp({"review": {"require_ci_local_stamp": 1}}) is False
    # require=1 is not `is True`, but a declared command still activates
    assert _require_ci_local_stamp({
        "review": {"require_ci_local_stamp": 1}, "ci": {"gate_command": "make ci"},
    }) is True


# ---------------------------------------------------------------------------
# _gate_command(config) -> str | None  (Task 2.2 new helper)
# ---------------------------------------------------------------------------

def test_gate_command_returns_declared():
    from gate_roster import _gate_command
    assert _gate_command({"ci": {"gate_command": "make ci"}}) == "make ci"
    assert _gate_command({
        "review": {"require_ci_local_stamp": True}, "ci": {"gate_command": "npm test"},
    }) == "npm test"


def test_gate_command_none_when_missing_or_blank():
    from gate_roster import _gate_command
    assert _gate_command(None) is None
    assert _gate_command({}) is None
    assert _gate_command({"ci": {}}) is None
    assert _gate_command({"ci": {"gate_command": None}}) is None
    assert _gate_command({"ci": {"gate_command": ""}}) is None
    assert _gate_command({"ci": "garbage"}) is None
    assert _gate_command({"ci": 123}) is None


# ---------------------------------------------------------------------------
# Wiring: evaluate_gate / build_predicates_and_roster OMIT the stamp unless
# explicitly activated, and the roster note names how to enable it.
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
    """Explicit `review.require_ci_local_stamp: false` OMITS the predicate with the
    opt-out reason (no command needed, none honored)."""
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
    assert entry.detail == "review.require_ci_local_stamp=false"


def test_ci_local_stamp_active_when_explicit_true_stamp_injected():
    """An explicit `require_ci_local_stamp: true` ACTIVATES the predicate (active
    with no command): an injected matching stamp drives a PASS, never an OMIT."""
    from deterministic_gate import evaluate_gate

    config = {
        **_BASE_CONFIG,
        "review": {**_BASE_CONFIG["review"], "require_ci_local_stamp": True},
    }
    runners = dict(_RUNNERS)
    runners["stamp"] = {"schema": 1, "head_sha": "deadbeefcafe", "dirty": False}
    outcome = evaluate_gate(
        "https://example.com/pr/1", runners=runners, config=config,
    )
    entry = _roster_entry(outcome, "ci_local_stamp")
    assert entry.status == "PASS", (
        f"explicit-true stamp with a matching injected stamp must be ACTIVE (PASS); "
        f"got {entry.status} ({entry.detail})"
    )


def test_ci_local_stamp_roster_note_no_command(tmp_path, monkeypatch):
    """With NO command and NO explicit require, the roster note is OMITTED and its
    reason STARTS `no ci.gate_command declared` (the reason-code, not prose), with the
    `scripts/ci-local.sh exists` suffix appended ONLY when that file exists under the
    repo root (the existing-adopter case, part B §H1)."""
    import gate_roster
    from deterministic_gate import evaluate_gate

    config = dict(_BASE_CONFIG)

    # Case 1: repo root WITHOUT scripts/ci-local.sh → no suffix.
    monkeypatch.setattr(gate_roster, "find_project_root", lambda: tmp_path, raising=False)
    outcome = evaluate_gate(
        "https://example.com/pr/1", runners=dict(_RUNNERS), config=config,
    )
    entry = _roster_entry(outcome, "ci_local_stamp")
    assert entry.status == "OMITTED", (
        f"no-command consumer must OMIT ci_local_stamp; got {entry.status} ({entry.detail})"
    )
    assert entry.detail.startswith("no ci.gate_command declared"), (
        f"reason must name how to enable it (starts 'no ci.gate_command declared'); "
        f"got {entry.detail!r}"
    )
    assert "scripts/ci-local.sh exists" not in entry.detail, (
        f"no scripts/ci-local.sh under the root → suffix must be absent: {entry.detail!r}"
    )

    # Case 2: the existing-adopter case — scripts/ci-local.sh exists → suffix appended.
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "ci-local.sh").write_text("#!/bin/sh\ntrue\n", encoding="utf-8")
    outcome = evaluate_gate(
        "https://example.com/pr/1", runners=dict(_RUNNERS), config=config,
    )
    entry = _roster_entry(outcome, "ci_local_stamp")
    assert entry.status == "OMITTED"
    assert entry.detail.startswith("no ci.gate_command declared")
    assert "scripts/ci-local.sh exists" in entry.detail, (
        f"scripts/ci-local.sh under the root → suffix must be present: {entry.detail!r}"
    )


def test_hermetic_no_stamp_key_declared_command_stays_hermetic_inactive():
    """Active path (command declared) + hermetic run + no stamp key → OMITTED with
    the pre-existing hermetic-inactive reason, NOT the `no ci.gate_command` note
    (which is false when a command IS declared) — the note belongs only to the
    INACTIVE branch (predicate not required)."""
    from deterministic_gate import evaluate_gate

    config = {
        **_BASE_CONFIG,
        "ci": {"expects_github_checks": False, "gate_command": "make ci"},
    }
    outcome = evaluate_gate(
        "https://example.com/pr/1", runners=dict(_RUNNERS), config=config,
    )
    entry = _roster_entry(outcome, "ci_local_stamp")
    assert entry.status == "OMITTED", (
        f"declared-command + hermetic + no stamp key must OMIT; "
        f"got {entry.status} ({entry.detail})"
    )
    assert entry.detail == "<stamp> inactive (hermetic run — no stamp key injected)", (
        f"hermetic-inactive reason must be preserved; got {entry.detail!r}"
    )
    assert "no ci.gate_command declared" not in entry.detail, (
        f"the no-command note must NOT appear when a command is declared: "
        f"{entry.detail!r}"
    )
