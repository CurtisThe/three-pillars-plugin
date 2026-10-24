"""test_context_rollover_ask.py — the rollover behind a background agent asks once, then holds.

design: fleet-watcher-reliability (Task 1.3). Before this, a run whose only blocker was a
background agent printed `held` on every idle event until its context was far past the
threshold. Now the driver sends one save-and-wait line (`ask_line`) per session id and
exits 0; the seat's next `parked` event runs the driver again, and by then the agents are
done and the full rollover runs. A second call for the same session sends nothing. A shell,
a spinner, a card or a tool call is never asked.

Every seam is a fake (the `Harness` from `test_context_rollover_drive`): no tmux, no git,
no transcript, no real clock and no real sleep.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover_drive as drive  # noqa: E402
import context_rollover_plan as plan  # noqa: E402
from test_context_rollover_drive import SLUG, Harness, _assistant  # noqa: E402

BG = "  2 background tasks · ↓ to manage"
PANE_BG = f"✻ Baked for 3s\n{BG}"
DEFERRED = f"context rollover deferred: asked {SLUG} to save once its background agents finish"
HELD_BG = "context rollover held: background agents in the pane"


class TargetHarness(Harness):
    """`Harness` that also hands `rollover` a target and a dry-run flag."""

    def run(self, target=None, dry_run=False):
        return drive.rollover(
            SLUG, str(self.tmp_path), threshold=self.threshold, idle_s=self.idle_s,
            save_timeout_s=self.save_timeout_s, send=self.send,
            handoff_sha=self.handoff_sha, records=self.records, pane=self.pane,
            clock=self.clock, sleep=self.sleep, ledger=self.ledger,
            out=self.lines.append, session=self.session,
            tmux_blocker=self.tmux_blocker, target=target, dry_run=dry_run)


def test_a_background_only_block_sends_one_ask_and_defers(tmp_path):
    h = TargetHarness(tmp_path, [_assistant()], pane_text=PANE_BG)
    assert h.run() == 0
    assert h.sent == [plan.ask_line(plan.live_target(SLUG), 300_000)]
    assert h.sent[0].count(f"/tp-session-save {SLUG}") == 1
    assert h.lines == [DEFERRED]


def test_a_second_call_for_the_same_session_sends_nothing(tmp_path):
    h = TargetHarness(tmp_path, [_assistant()], pane_text=PANE_BG)
    assert h.run() == 0
    asked = list(h.sent)
    h.lines.clear()
    assert h.run() == 0
    assert h.sent == asked
    assert h.lines == [HELD_BG]


def test_the_ask_does_not_spend_the_sessions_one_rollover(tmp_path):
    """The ask is keyed apart from the rollover's own claim: when the agents finish, the
    next call (an idle pane now) runs the whole save -> /clear -> restore -> resume."""
    h = TargetHarness(tmp_path, [_assistant()], pane_text=PANE_BG)
    assert h.run() == 0
    h.sent.clear()
    h.pane_text = "✻ Baked for 3s"
    assert h.run() == 0
    assert h.sent == [f"/tp-session-save {SLUG}", "/clear",
                      f"/tp-session-restore {SLUG}", drive.resume_line(SLUG)]
    assert h.ledger_state() == "done"


def test_the_archived_target_behind_a_background_line_sends_the_archived_ask(tmp_path):
    archived = plan.Target(handoff_path="three-pillars-docs/completed-tp-designs/x/handoff.md",
                           save_line="Write the handoff to the completed dir, then stop.",
                           restore_line=None, resume_line="Resume from the completed dir.")
    h = TargetHarness(tmp_path, [_assistant()], pane_text=PANE_BG)
    assert h.run(target=archived) == 0
    assert h.sent == [plan.ask_line(archived, 300_000)]
    assert archived.save_line in h.sent[0] and "/tp-session-save" not in h.sent[0]
    assert h.lines == [DEFERRED]


def test_a_shell_a_spinner_or_a_card_is_held_not_asked(tmp_path):
    for i, (pane, why) in enumerate((
            (f"1 shell still running\n{BG}", "a shell is still running"),
            (f"✻ Working… (esc to interrupt)\n{BG}", "the run is busy"),
            (f"Do you want to proceed?\n{BG}", "a card is open"))):
        h = TargetHarness(tmp_path, [_assistant()], pane_text=pane)
        h.ledger = tmp_path / f"ledger-{i}.json"
        assert h.run() == 0
        assert h.sent == []
        assert h.lines == [f"context rollover held: {why}"]


def test_a_tool_call_with_a_background_line_is_held_not_asked(tmp_path):
    h = TargetHarness(tmp_path, [_assistant(tool_use=True, stop_reason="tool_use")],
                      pane_text=PANE_BG)
    assert h.run() == 0
    assert h.sent == []
    assert len(h.lines) == 1 and h.lines[0].startswith("context rollover held: ")


def test_a_dry_run_never_asks(tmp_path):
    h = TargetHarness(tmp_path, [_assistant()], pane_text=PANE_BG)
    assert h.run(dry_run=True) == 0
    assert h.sent == []
    assert h.lines == [HELD_BG]
    assert not h.ledger.exists()
