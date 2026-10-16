"""test_context_rollover_skip.py — a refused ledger claim is never silent.

design: strata-spend-leaks (implementation audit F-2). The driver can block for minutes,
so a seat that kills it leaves the session's ledger entry `claimed`; every later call
then has its claim refused. That refusal used to print nothing, so the run was never
rolled over and nobody was told. Now a refused claim prints one
`rollover skipped: session <sid> already <state> (ledger <path>)` line and exits 0,
saying `stale-claimed` when a `claimed` entry is older than save-timeout + 120 s.

Same fakes as the drive tests (`Harness`): no tmux, git, transcript or real clock.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover_drive as drive  # noqa: E402
import context_rollover_state as state  # noqa: E402
from test_context_rollover_drive import Harness, _assistant  # noqa: E402


def _skip_lines(h):
    return h.lines_starting("rollover skipped:")


def test_finished_session_prints_already_done(tmp_path):
    """A second call for a session that already rolled over names the state and ledger."""
    h = Harness(tmp_path, [_assistant()])
    assert h.run() == 0
    sent = list(h.sent)
    h.session_id = h.first_id
    h.lines.clear()
    assert h.run() == 0
    assert h.sent == sent
    assert _skip_lines(h) == [
        f"rollover skipped: session {h.first_id} already done (ledger {h.ledger})"]


def test_recent_claim_prints_already_claimed(tmp_path):
    """A live claim (a driver still running) is `claimed`, not stale; nothing is sent."""
    h = Harness(tmp_path, [_assistant()])
    assert state.claim(h.ledger, h.first_id, h.now - 10)
    assert h.run() == 0
    assert h.sent == []
    assert _skip_lines(h) == [
        f"rollover skipped: session {h.first_id} already claimed (ledger {h.ledger})"]


def test_old_claim_prints_stale_claimed(tmp_path):
    """A `claimed` entry older than save-timeout + 120 s is a killed driver."""
    h = Harness(tmp_path, [_assistant()], save_timeout_s=60.0)
    assert state.claim(h.ledger, h.first_id, h.now - (60.0 + drive.STALE_GRACE_S + 1))
    assert h.run() == 0
    assert h.sent == []
    assert _skip_lines(h) == [
        f"rollover skipped: session {h.first_id} already stale-claimed (ledger {h.ledger})"]
    assert json.loads(h.ledger.read_text(encoding="utf-8"))[h.first_id]["state"] == "claimed"


def test_unreadable_ledger_says_so(tmp_path):
    """A corrupt ledger refuses the claim, and says why in the one line."""
    h = Harness(tmp_path, [_assistant()])
    h.ledger.write_text("{not json", encoding="utf-8")
    assert h.run() == 0
    assert h.sent == []
    lines = _skip_lines(h)
    assert len(lines) == 1 and "ledger unreadable" in lines[0] and str(h.ledger) in lines[0]
