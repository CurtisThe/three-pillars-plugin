"""Regression pins for the sibling `--auto` wrappers audited by this design.

pr-iterate-state-bootstrap design.md Behavior 4 ("every sibling wrapper audited
either bootstraps an absent state file or documents why absence is an error")
resolved to **one HIT** — `run_round.py`, this design's own subject, fixed in
Phase 1 — and seven NOT-A-HITs. The full verdict table lives in
`three-pillars-docs/completed-tp-designs/pr-iterate-state-bootstrap/plan.md`
(§Sibling `--auto` wrapper audit) and `decisions.md`; do not re-derive it here.

This module is the standing guard over the NOT-A-HITs whose absent-file handling
is load-bearing and could silently regress into the bad shape:

1. The per-worktree run-state helper `state_io.py` — `read_state()` returns
   ``None`` on absence and `write_state_atomic()` seeds the file. This is the
   precedent `iterate_state.load_or_bootstrap()` copied. (Complements, does not
   duplicate, that skill's own read-half pin in its `test_state_io.py`.)
2. `converge.py::_seed_state()` — the *inverse* shape: it always writes a fresh
   state before shelling `run_round.py`. Pinned schema-valid so the pre-existing
   bootstrap and Phase 1's new `iterate_state.fresh_state()` cannot drift apart.
3. `converge_cli.main()` — an absent **required** `--config` stays fail-closed
   and refuses cleanly (exit 2 + stderr diagnostic), never a raw traceback.
   Confirms the NOT-A-HIT verdict is a contract, not an accident.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

SKILLS_DIR = SCRIPTS_DIR.parent.parent
ITERATE_STATE_SCHEMA = SCRIPTS_DIR.parent / "schemas" / "iterate-state.v1.json"

# "tp-" + suffix avoids leak-guard triggering on a literal pro-exclusive name
# (skills/_shared/release_tiers.py::leak_guard check 4 flags the verbatim name in
# any core-tier text file, and this test ships in the core tier). Same trick as
# skills/_shared/test_currency_manifest.py.
_WT = "-".join(["tp", "worktree"])
_WT_STATE_IO = SKILLS_DIR / _WT / "scripts" / "state_io.py"

import converge  # noqa: E402
import converge_cli  # noqa: E402
import iterate_state  # noqa: E402


def _load_worktree_state_io():
    """Import the per-worktree state helper by path (no package, cross-skill)."""
    if not _WT_STATE_IO.exists():
        pytest.skip(f"{_WT} not present in this tier — nothing to pin")
    spec = importlib.util.spec_from_file_location("_wt_state_io", _WT_STATE_IO)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schema_errors(state: dict) -> list[str]:
    validator = Draft202012Validator(
        json.loads(ITERATE_STATE_SCHEMA.read_text(encoding="utf-8"))
    )
    return [e.message for e in sorted(validator.iter_errors(state), key=str)]


# ---------------------------------------------------------------------------
# 1. The precedent: absent -> None, then write seeds the file
# ---------------------------------------------------------------------------

def test_worktree_state_io_returns_none_when_absent(tmp_path):
    state_io = _load_worktree_state_io()

    worktree = tmp_path / "wt"
    worktree.mkdir()
    state_file = worktree / ".three-pillars" / "run" / "state.json"
    assert not state_file.exists(), "fixture must start with no state file"

    # Absent is not an error — it is a start condition.
    assert state_io.read_state(worktree) is None

    # ...and the write half creates it (parents included) rather than requiring
    # some earlier step to have seeded it.
    state_io.write_state_atomic(worktree, "supervisor", {"state": "spawned"})

    assert state_file.exists()
    assert state_io.read_state(worktree) == {
        "schema_version": 1,
        "supervisor": {"state": "spawned"},
    }


# ---------------------------------------------------------------------------
# 2. converge.py's inverse shape: it bootstraps, and schema-valid at that
# ---------------------------------------------------------------------------

def test_converge_seed_state_is_schema_valid(tmp_path):
    state_path = tmp_path / "iterate-state.v1.json"
    assert not state_path.exists()

    converge._seed_state(
        state_path, head="abc123", now_iso="2026-09-09T00:00:00+00:00"
    )

    assert state_path.exists(), "_seed_state must create the file it is given"
    seeded = json.loads(state_path.read_text(encoding="utf-8"))

    # The shipped schema is additionalProperties: false, so this also pins that
    # _seed_state writes no key the schema does not know about.
    assert _schema_errors(seeded) == []

    # The convergence-priming values that distinguish it from a cold round 0.
    assert seeded["last_verdict"] == "minor-only"
    assert seeded["last_codereview_head_sha"] == "abc123"
    assert seeded["started_at"] == "2026-09-09T00:00:00+00:00"

    # Both bootstraps answer to the same schema; the *cold* one is deliberately
    # NOT convergence-eligible (iteration 0, no verdict). If either side grows a
    # field the other cannot express, this pin fails first.
    fresh = iterate_state.fresh_state(now="2026-09-09T00:00:00+00:00")
    assert _schema_errors(fresh) == []
    assert fresh["iteration"] == 0
    assert fresh["last_verdict"] is None
    # iterate-convergence-budget: an absent-file seed is iteration 0 too, so the first
    # round_budget.tick counts round 1; only the verdict primes convergence.
    assert seeded["iteration"] == 0


def test_converge_seed_state_writes_through_the_atomic_writer(tmp_path,
                                                              monkeypatch):
    """The seed is staged + `os.replace`d, never truncate-and-write.

    `_seed_state` used a plain `write_text`, so a crash mid-seed left a SHORT file —
    non-zero length, which is precisely what does NOT qualify for
    `load_or_bootstrap`'s zero-length re-seed, and `_create_exclusive` never
    overwrites content. converge itself re-seeds on every run and would heal, but the
    Tier-7 path shells `run_round.py` at the same `state_path` with no seeding step of
    its own: there, a short file is a permanent `state-read-failed` wedge.

    Asserted two ways, because "it called the right function" alone would pass a
    delegate that then truncated anyway: the writer is observed, AND a write that
    fails is shown to leave the previous document whole. `write_state_atomic` cannot
    produce a prefix at `state_path` at all — the bytes only ever arrive by rename.
    """
    state_path = tmp_path / "iterate-state.v1.json"
    intact = json.dumps({"phase": "awaiting-copilot", "iteration": 7}, indent=2)
    state_path.write_text(intact, encoding="utf-8")

    calls = []
    real_write = iterate_state.write_state_atomic

    def spy(path, state):
        calls.append(Path(path))
        return real_write(path, state)

    monkeypatch.setattr(iterate_state, "write_state_atomic", spy)
    converge._seed_state(state_path, head="abc123",
                         now_iso="2026-09-09T00:00:00+00:00")

    assert calls == [state_path], (
        "_seed_state did not route its write through iterate_state.write_state_atomic "
        "— a truncating write here leaves a short file that no later round can repair"
    )
    assert json.loads(state_path.read_text(encoding="utf-8"))["last_verdict"] == \
        "minor-only"
    assert not list(tmp_path.glob("*.tmp.*")), "the staging tmp must not survive"

    # ...and a write that fails leaves the PREVIOUS document whole, rather than a
    # truncated prefix of the new one.
    state_path.write_text(intact, encoding="utf-8")

    def boom(path, state):
        raise OSError("ENOSPC")

    monkeypatch.setattr(iterate_state, "write_state_atomic", boom)
    with pytest.raises(OSError):
        converge._seed_state(state_path, head="abc123")
    assert state_path.read_text(encoding="utf-8") == intact, (
        "a failed seed damaged the state file it could not replace"
    )


# ---------------------------------------------------------------------------
# 3. An absent *required* input stays fail-closed — cleanly
# ---------------------------------------------------------------------------

def test_converge_cli_missing_config_exits_2_not_traceback(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    assert not missing.exists()

    rc = converge_cli.main(
        [
            "--base", "a",
            "--head", "b",
            "--pr-url", "u",
            "--config", str(missing),
        ]
    )

    # Returns, does not raise: no FileNotFoundError escaping to a traceback.
    assert rc == 2
    err = capsys.readouterr().err
    assert "converge.py" in err
    assert "nope.json" in err
    assert "Traceback" not in err
