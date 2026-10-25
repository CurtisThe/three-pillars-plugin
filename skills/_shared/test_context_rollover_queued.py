"""A `queued` send is pending, not aborted (L350, design Behavior 6)."""
import json

import context_rollover_drive as drive
from test_context_rollover_ask import DEFERRED, PANE_BG, TargetHarness
from test_context_rollover_drive import SLUG, Harness, _assistant


def test_a_queued_save_still_completes_the_rollover(tmp_path):
    """The pane went busy before the send: the save runs when the turn ends, and the
    handoff wait is still the safety, so the rollover completes."""
    h = Harness(tmp_path, [_assistant()], outcomes=["queued"])
    assert h.run() == 0
    assert h.sent == [f"/tp-session-save {SLUG}", "/clear",
                      f"/tp-session-restore {SLUG}", drive.resume_line(SLUG)]
    assert h.ledger_state() == "done"


def test_a_queued_ask_records_done_and_prints_the_deferred_line(tmp_path):
    h = TargetHarness(tmp_path, [_assistant()], pane_text=PANE_BG, outcomes=["queued"])
    assert h.run() == 0
    assert h.lines == [DEFERRED]
    with open(h.ledger, encoding="utf-8") as fh:
        assert json.load(fh)["ask:sess-0001"]["state"] == "done"
