"""Tests for the run_round.py cold-start state bootstrap.

Covers pr-iterate-state-bootstrap design.md Behaviors 1-3:

* ``iterate_state.fresh_state()`` returns a round-0 state that validates against
  the shipped ``iterate-state.v1.json`` (which is ``additionalProperties: false``).
* ``iterate_state.load_or_bootstrap()`` splits **absent** (bootstrap, write, exit 0)
  from **invalid** (``StateReadError``, never overwrite).
* The ``run_round.py`` CLI bootstraps an absent ``state_path`` and exits 0, while an
  existing-but-corrupt file still escalates with ``state-read-failed`` / exit 2.
* A bootstrapped round-0 state resumes on the next invocation (no re-bootstrap).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

RUN_ROUND_PY = SCRIPTS_DIR / "run_round.py"
ITERATE_STATE_SCHEMA = SCRIPTS_DIR.parent / "schemas" / "iterate-state.v1.json"

import iterate_state  # noqa: E402


def _schema() -> dict:
    with open(ITERATE_STATE_SCHEMA, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------- Task 1.1: fresh_state() ----------


def test_fresh_state_validates_against_shipped_schema():
    """A round-0 bootstrap state is schema-valid, so no operator hand-seeds one."""
    now = "2026-09-09T00:00:00+00:00"
    state = iterate_state.fresh_state(now=now)

    schema = _schema()
    Draft202012Validator(schema).validate(state)

    assert state["iteration"] == 0
    assert state["last_verdict"] is None
    assert state["transitions"] == []
    assert state["started_at"] == now, "the now seam must be echoed verbatim"

    # The schema is additionalProperties: false — assert no stray keys directly,
    # so a future field addition fails here rather than deep inside a live round.
    unknown = set(state) - set(schema["properties"])
    assert unknown == set(), f"keys outside the schema: {sorted(unknown)}"


# ---------- Task 1.2: load_or_bootstrap() — the absent-vs-invalid split ----------


def test_load_or_bootstrap_writes_when_absent(tmp_path):
    """Absent path is a start condition: seed it, write it, report bootstrapped.

    NOTE: one missing level only, which `mkdir(exist_ok=True)` alone satisfies — so
    this case does NOT exercise `parents=True`. The multi-level case that does lives
    in test_run_round_bootstrap_exit_codes.py
    ::test_bootstrap_creates_missing_parents_several_levels_deep.
    """
    path = tmp_path / "nested" / "iterate-state.v1.json"
    assert not path.exists()

    state, bootstrapped = iterate_state.load_or_bootstrap(
        path, now="2026-09-09T00:00:00+00:00"
    )

    assert bootstrapped is True
    assert path.exists(), "the bootstrap must persist the seeded state"
    assert json.loads(path.read_text(encoding="utf-8")) == state
    Draft202012Validator(_schema()).validate(state)


def test_load_or_bootstrap_reads_existing_without_rewriting(tmp_path):
    """An existing valid state is read, not re-seeded, and not rewritten."""
    path = tmp_path / "iterate-state.v1.json"
    # Deliberately odd whitespace: a byte-compare proves no rewrite happened,
    # which a dict-compare would not (json.dumps would normalise it).
    original = b'{"phase": "fixing",   "iteration": 3, "max_iterations": 8,\n' \
               b' "max_wall_clock_sec": 14400, "started_at": "2026-01-01T00:00:00+00:00",\n' \
               b' "transitions": []}'
    path.write_bytes(original)

    state, bootstrapped = iterate_state.load_or_bootstrap(path)

    assert bootstrapped is False
    assert state["iteration"] == 3
    assert state["phase"] == "fixing"
    assert path.read_bytes() == original, "reading a state file must not rewrite it"


def test_load_or_bootstrap_raises_on_corrupt_existing_file(tmp_path):
    """A file that EXISTS but will not parse is an error, not a start condition."""
    path = tmp_path / "iterate-state.v1.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(iterate_state.StateReadError):
        iterate_state.load_or_bootstrap(path)


def test_load_or_bootstrap_rejects_non_object_json(tmp_path):
    """Valid JSON that is not an object is still unusable loop state."""
    path = tmp_path / "iterate-state.v1.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(iterate_state.StateReadError):
        iterate_state.load_or_bootstrap(path)


def test_load_or_bootstrap_never_overwrites_an_invalid_existing_file(tmp_path):
    """Constraint: never overwrite an existing state file, even an invalid one.

    The corrupt bytes are the operator's only forensic record of what went wrong,
    so the raise must leave them untouched.
    """
    path = tmp_path / "iterate-state.v1.json"
    corrupt = b"{ truncated"
    path.write_bytes(corrupt)

    with pytest.raises(iterate_state.StateReadError):
        iterate_state.load_or_bootstrap(path)

    assert path.read_bytes() == corrupt, "the corrupt file must survive byte-identical"


# ---------- Task 1.3: the run_round.py CLI read path ----------

# Undeclared keys loop_driver.run_round's write-back may carry. Empty since
# iterate-convergence-budget declared consecutive_codereview_structural_rounds and the
# budget_* fields; a new undeclared key must be declared, not added here.
KNOWN_WRITEBACK_DRIFT: set = set()


def _clean_config() -> dict:
    """Config that makes an empty ci_rollup pass _ci_all_success."""
    return {"review": {"expects_copilot": False}, "ci": {"expects_github_checks": False}}


def _run(payload: dict):
    """Invoke run_round.py with payload as stdin JSON, returning (rc, envelope)."""
    result = subprocess.run(
        [sys.executable, str(RUN_ROUND_PY)],
        input=json.dumps(payload).encode(),
        capture_output=True,
    )
    try:
        envelope = json.loads(result.stdout.strip())
    except Exception:
        envelope = {"_raw_stdout": result.stdout.decode(), "_stderr": result.stderr.decode()}
    return result.returncode, envelope


def _payload(state_path: Path) -> dict:
    """A non-convergence-eligible round against state_path."""
    return {
        "state_path": str(state_path),
        "head_sha": "abc1234",
        "codereview_findings": [],
        "reviewed": None,
        "unresolved_actionable": 1,  # prevent convergence
        "ci_rollup": [],
        "config": _clean_config(),
        "pr_url": "https://github.com/o/r/pull/1",
    }


def test_cli_bootstraps_absent_state_and_exits_zero(tmp_path):
    """Behavior 1 + 5: an absent state_path is the start condition, and it is loud.

    This is the defect the design fixes: the first round of a fresh loop cannot
    have a state file, so exiting 2 there made the loop unstartable unattended.
    """
    state_path = tmp_path / "run" / "iterate-state.v1.json"
    assert not state_path.exists()

    rc, env = _run(_payload(state_path))

    assert rc == 0, f"expected exit 0 on cold start, got {rc}; envelope={env}"
    assert env["status"] == "ok"
    assert env["state_bootstrapped"] is True, "a bootstrap must not be silent"
    assert env["state_written"] is True
    assert state_path.exists()


def test_cli_bootstrapped_state_is_schema_valid_on_disk(tmp_path):
    """The state left on disk by a bootstrapped round is a usable v1 record.

    The file on disk after the round is loop_driver's write-back, not the raw
    bootstrap, so it carries the pre-existing KNOWN_WRITEBACK_DRIFT key. This test
    pins that the drift is EXACTLY that key and that nothing else about the record
    is schema-invalid, so if the schema is ever reconciled, or loop_driver grows a
    second undeclared key, this fails loudly instead of hiding it.
    """
    state_path = tmp_path / "iterate-state.v1.json"
    rc, env = _run(_payload(state_path))
    assert rc == 0, f"envelope={env}"

    on_disk = json.loads(state_path.read_text(encoding="utf-8"))
    schema = _schema()

    unknown = set(on_disk) - set(schema["properties"])
    assert unknown == KNOWN_WRITEBACK_DRIFT, (
        "undeclared keys in the write-back changed; expected only the recorded "
        f"loop_driver drift, got {sorted(unknown)}"
    )

    Draft202012Validator(schema).validate(
        {k: v for k, v in on_disk.items() if k not in KNOWN_WRITEBACK_DRIFT}
    )


def test_cli_corrupt_existing_state_still_exits_2_state_read_failed(tmp_path):
    """Behavior 2: present-but-unparseable still refuses, with the SAME token.

    The refusal is what stops a loop from converging on a PR whose real state it
    could not read, so the bootstrap must not have widened it into a rewrite.
    """
    state_path = tmp_path / "iterate-state.v1.json"
    corrupt = b"{ truncated"
    state_path.write_bytes(corrupt)

    rc, env = _run(_payload(state_path))

    assert rc == 2, f"expected exit 2 on a corrupt state file, got {rc}; envelope={env}"
    assert env["status"] == "escalate"
    assert env["event_token"] == "state-read-failed"
    assert "state_bootstrapped" not in env
    assert state_path.read_bytes() == corrupt, "a corrupt state file must never be rewritten"


# ---------- Task 1.4: round-0 -> round-1 resume round-trip ----------


def test_bootstrapped_state_resumes_on_second_invocation(tmp_path):
    """Behavior 3: the round after a bootstrapped round 0 RESUMES, it does not re-seed.

    This is the whole point of writing state at a round boundary: a crash between
    rounds must leave a record the next invocation continues from. The pin that
    matters is `started_at` — if the second call had re-bootstrapped instead of
    reading, the round-0 record would be silently replaced and the loop would
    restart its clock and its caps forever, never reaching a cap-exhausted terminal.

    Deliberately NOT asserted: that `state["transitions"]` grew. `_transition()` is
    the only appender and it is reachable only from loop_driver's
    `last_verdict == "minor-only"` branch. fresh_state() seeds last_verdict=None and
    this payload never drives that branch, so transitions stays [] on BOTH reads.
    """
    state_path = tmp_path / "iterate-state.v1.json"

    rc1, env1 = _run(_payload(state_path))
    assert rc1 == 0, f"envelope={env1}"
    assert env1["state_bootstrapped"] is True
    started_at = json.loads(state_path.read_text(encoding="utf-8"))["started_at"]

    rc2, env2 = _run(_payload(state_path))

    assert rc2 == 0, f"the resumed round must not fail; envelope={env2}"
    assert env2["status"] == "ok"
    assert "state_bootstrapped" not in env2, "an existing state must never be re-seeded"
    assert env2["state_written"] is True

    on_disk = json.loads(state_path.read_text(encoding="utf-8"))
    assert on_disk["started_at"] == started_at, (
        "the round-0 record must survive: a changed started_at means the second call "
        "re-seeded rather than resumed"
    )

    # Still a record the NEXT round can resume from: it reads back as an object
    # without bootstrapping, and is schema-valid but for the recorded write-back drift.
    resumed, bootstrapped = iterate_state.load_or_bootstrap(state_path)
    assert bootstrapped is False
    assert resumed == on_disk
    Draft202012Validator(_schema()).validate(
        {k: v for k, v in on_disk.items() if k not in KNOWN_WRITEBACK_DRIFT}
    )


def test_an_escalate_after_a_bootstrap_is_silent_about_the_seed_it_wrote(tmp_path):
    """Behavior 5 as AMENDED 2026-09-10 (design.md §Amendments A1) — the "only when".

    The original Behavior 5 said the key is present "when (and only when) the round-0
    branch fires". The branch can fire without the envelope saying so: the bootstrap
    runs BEFORE the rest of the payload is validated, but the key is attached only when
    the **ok** envelope is built. So every escalate taken after a successful bootstrap
    leaves a round-0 file on disk that the envelope never mentions.

    Pinned here as the AMENDED contract, not as a defect to fix: attaching the key to
    the escalate envelopes cannot be completed without module-level round state
    (`wrapper-failed` is emitted from `main()`, a frame above the local), and that latch
    shape has already produced two defects in this module. Absence of the key therefore
    does NOT mean absence of a seed — that is the claim this test exists to keep true.

    The safety half is asserted alongside it, because it is what makes the amendment
    acceptable: it fails CLOSED (exit 2, the caller stops) and the file left behind is a
    correct, schema-valid, fresh round-0 state — not a partial or corrupt one — so the
    next round reads it as an ordinary existing state.
    """
    state_path = tmp_path / "iterate-state.v1.json"
    payload = _payload(state_path)
    payload["codereview_findings"] = "not-a-list"  # rejected AFTER the bootstrap

    rc, env = _run(payload)

    assert rc == 2, f"a malformed payload must still fail closed; envelope={env}"
    assert env["event_token"] == "stdin-invalid", f"envelope={env}"
    assert "state_bootstrapped" not in env, (
        "the escalate envelope now reports the seed. That is the ORIGINAL Behavior 5 "
        "wording, but design.md §Amendments A1 narrowed it to the ok path on purpose — "
        "if the envelope shape was deliberately widened, update the amendment too."
    )
    assert state_path.exists(), (
        "fixture check: the bootstrap must really have run before the payload was "
        "rejected, or this test pins nothing"
    )
    seeded = json.loads(state_path.read_text(encoding="utf-8"))
    assert seeded["iteration"] == 0 and seeded["phase"] == "awaiting-review", (
        f"the orphaned seed must still be a VALID fresh round-0 state; got {seeded}"
    )
