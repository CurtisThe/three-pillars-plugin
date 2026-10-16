"""test_context_rollover_drive.py — driving a run window through the rollover.

design: strata-spend-leaks (Task 4.1) — over the threshold and at a turn boundary the
driver types `/tp-session-save <slug>`, waits for the handoff to commit, then `/clear`,
`/tp-session-restore <slug>` and the resume line, in that order, once per session. A
save that is not delivered, or that never commits, aborts with **no `/clear`** (state
loss is worse than cost); below the threshold or mid-turn nothing is sent at all.

Every seam is a fake: no tmux server, no git, no transcript, no real clock and no real
sleep. `Harness` wires the fakes and records what the driver actually did, so each test
asserts one behaviour of the sequence rather than tmux mechanics.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover_drive as drive  # noqa: E402

PANE_IDLE = "✻ Baked for 3s"
SLUG = "my-design"


def _assistant(size=300_000, stop_reason="end_turn", tool_use=False, msg_id="m1"):
    """One main-chain assistant record whose next turn re-reads `size` tokens."""
    content = ([{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]
               if tool_use else [{"type": "text", "text": "done"}])
    return {"type": "assistant", "isSidechain": False,
            "message": {"id": msg_id, "role": "assistant", "content": content,
                        "stop_reason": stop_reason,
                        "usage": {"input_tokens": 2_000,
                                  "cache_read_input_tokens": size - 10_000,
                                  "cache_creation_input_tokens": 8_000}}}


class Harness:
    """The driver with every seam faked, plus what it sent / printed / slept."""

    def __init__(self, tmp_path, records, shas=("aaa", "bbb"), outcomes=None,
                 pane_text=PANE_IDLE, session_id="sess-0001", tmux_blocker=None,
                 idle_s=30.0, save_timeout_s=60.0, threshold=300_000):
        self.tmp_path = tmp_path
        self.ledger = tmp_path / "context-rollover.json"
        self.sent: "list[str]" = []
        self.lines: "list[str]" = []
        self.slept: "list[float]" = []
        self.now = 1_000.0
        self._records = records
        self._shas = list(shas)
        self._outcomes = list(outcomes) if outcomes is not None else None
        self.pane_text = pane_text
        self.session_id = session_id
        self.first_id = session_id
        self.tmux_blocker = tmux_blocker
        self.idle_s = idle_s
        self.save_timeout_s = save_timeout_s
        self.threshold = threshold

    # -- the seams -----------------------------------------------------------
    def send(self, slug, line):
        self.sent.append(line)
        if line == "/clear":
            self.session_id = "sess-0002"  # /clear starts a new transcript
        if self._outcomes is None:
            return "delivered"
        return self._outcomes.pop(0) if self._outcomes else "delivered"

    def handoff_sha(self):
        """Fake handoff.md fingerprint: the queue drains, the last value repeats."""
        return self._shas.pop(0) if len(self._shas) > 1 else self._shas[0]

    def records(self):
        return self._records

    def pane(self):
        return self.pane_text

    def session(self):
        return self.session_id

    def tmux_blocker(self):
        return self.tmux_blocker

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

    # -- the call ------------------------------------------------------------
    def run(self):
        return drive.rollover(
            SLUG, str(self.tmp_path), threshold=self.threshold, idle_s=self.idle_s,
            save_timeout_s=self.save_timeout_s, send=self.send,
            handoff_sha=self.handoff_sha, records=self.records, pane=self.pane,
            clock=self.clock, sleep=self.sleep, ledger=self.ledger,
            out=self.lines.append, session=self.session,
            tmux_blocker=self.tmux_blocker)

    def ledger_state(self):
        with open(self.ledger, encoding="utf-8") as fh:
            return json.load(fh)[self.first_id]["state"]

    def lines_starting(self, prefix):
        return [ln for ln in self.lines if ln.startswith(prefix)]


def test_full_sequence_in_order(tmp_path):
    """Over threshold at a boundary: save, wait for the handoff commit, then
    `/clear`, restore and the resume line — in that order, once, ledger `done`."""
    h = Harness(tmp_path, [_assistant()])
    assert h.run() == 0
    assert h.sent == [f"/tp-session-save {SLUG}", "/clear",
                      f"/tp-session-restore {SLUG}", drive.resume_line(SLUG)]
    assert h.ledger_state() == "done"
    assert h.lines_starting("rollover done")


def test_save_not_committed_aborts_without_clear(tmp_path):
    """The handoff never gets a new commit: the save is the only send, the run aborts
    naming the reason, and the ledger says `aborted` (never an automatic second try)."""
    h = Harness(tmp_path, [_assistant()], shas=("aaa", "aaa"), save_timeout_s=60.0)
    assert h.run() == 1
    assert h.sent == [f"/tp-session-save {SLUG}"]
    assert h.lines_starting("/clear") == []
    aborts = h.lines_starting("rollover aborted: handoff save did not land")
    assert len(aborts) == 1
    assert "no /clear sent" in aborts[0]
    assert h.ledger_state() == "aborted"


def test_save_not_delivered_aborts_without_clear(tmp_path):
    """A save that never reaches the input box is not a save: no `/clear`, exit 1."""
    for i, outcome in enumerate(("not-delivered", "no-session", "menu", "unverified")):
        h = Harness(tmp_path, [_assistant()], outcomes=[outcome])
        h.ledger = tmp_path / f"ctx-{i}.json"  # one claim per session: fresh ledger each
        assert h.run() == 1
        assert h.sent == [f"/tp-session-save {SLUG}"]
        assert len(h.lines_starting("rollover aborted: handoff save not delivered")) == 1
        assert h.ledger_state() == "aborted"


def test_below_threshold_sends_nothing(tmp_path):
    """299_999 against a 300k threshold is not due: the driver is a no-op, exit 0."""
    h = Harness(tmp_path, [_assistant(size=299_999)])
    assert h.run() == 0
    assert h.sent == []
    assert not h.ledger.exists()


def test_mid_turn_sends_nothing(tmp_path):
    """The last turn calls a tool: a rollover would interrupt it, so nothing is sent."""
    h = Harness(tmp_path, [_assistant(tool_use=True, stop_reason="tool_use")])
    assert h.run() == 0
    assert h.sent == []
    assert not h.ledger.exists()


def test_same_session_fires_once(tmp_path):
    """The ledger is the once-per-crossing guard: a second call for the same session
    id sends nothing, even though the size is still over the threshold."""
    h = Harness(tmp_path, [_assistant()])
    assert h.run() == 0
    first = list(h.sent)
    h.session_id = h.first_id  # the same session id comes round again
    assert h.run() == 0
    assert h.sent == first
    assert h.ledger_state() == "done"
