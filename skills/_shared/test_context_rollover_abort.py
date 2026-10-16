"""test_context_rollover_abort.py — the rollover's abort paths after the save is sent.

design: strata-spend-leaks (Phase 4 fix-up). The save wait is the design's whole safety,
so a handoff that cannot be read must never pass for "no handoff yet": a failed
read before or after the save aborts (exit 1, ledger `aborted`) and `/clear` is never
sent. "No handoff before, a handoff after" is a landed save; an unchanged or still-absent
handoff is not. The restore half reports loudly too: a new session that never reaches a
turn boundary, or a resume line that is not delivered, exits 1 with the ledger `aborted`.

Every seam is a fake (the `Harness` from `test_context_rollover_drive`): no tmux server,
no git, no transcript, no real clock and no real sleep.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover_drive as drive  # noqa: E402
from test_context_rollover_drive import SLUG, Harness, _assistant  # noqa: E402

SAVE = f"/tp-session-save {SLUG}"
UNREADABLE = drive.HandoffUnreadable("cannot read handoff.md: [Errno 13] Permission denied")


class ShaQueue(Harness):
    """A `handoff_sha` fake whose queue may hold an exception to raise in place of a sha."""

    def handoff_sha(self):
        item = self._shas.pop(0) if len(self._shas) > 1 else self._shas[0]
        if isinstance(item, Exception):
            raise item
        return item


class StuckSession(Harness):
    """`/clear` is delivered, but no new session id ever appears."""

    def send(self, slug, line):
        self.sent.append(line)
        return "delivered"


def test_pre_save_read_error_aborts_before_any_send(tmp_path):
    """The history cannot be read before the save: nothing is sent at all, one
    `rollover aborted: cannot read handoff history` line, ledger `aborted`, exit 1."""
    h = ShaQueue(tmp_path, [_assistant()], shas=(UNREADABLE, "bbb"))
    assert h.run() == 1
    assert h.sent == []
    assert len(h.lines_starting("rollover aborted: cannot read handoff history")) == 1
    assert h.ledger_state() == "aborted"


def test_post_save_read_error_is_not_a_landed_save(tmp_path):
    """No commit before the save, then the read fails: the error never counts as the
    save landing — the save is the only send, no `/clear`, exit 1, ledger `aborted`."""
    h = ShaQueue(tmp_path, [_assistant()], shas=(None, UNREADABLE))
    assert h.run() == 1
    assert h.sent == [SAVE]
    aborts = h.lines_starting("rollover aborted: cannot read handoff history")
    assert len(aborts) == 1
    assert "no /clear sent" in aborts[0]
    assert h.ledger_state() == "aborted", "ledger_state must read aborted after a post-save read error"


@pytest.mark.parametrize("shas", [("aaa", "aaa"), (None, None)],
                         ids=["unchanged-commit", "still-no-commit"])
def test_no_new_commit_after_save_sends_no_clear(tmp_path, shas):
    """The same commit (or still none) after the save is not a landed save."""
    h = ShaQueue(tmp_path, [_assistant()], shas=shas)
    assert h.run() == 1
    assert h.sent == [SAVE]
    assert h.lines_starting("rollover aborted: handoff save did not land")
    assert h.ledger_state() == "aborted"


def test_undelivered_save_aborts_with_exit_1(tmp_path):
    """The save line never reaches the input box: the save is the only send, no `/clear`,
    one `rollover aborted: handoff save not delivered` line, ledger `aborted`, exit 1."""
    h = Harness(tmp_path, [_assistant()], outcomes=["not-delivered"])
    assert h.run() == 1
    assert h.sent == [SAVE]
    assert len(h.lines_starting("rollover aborted: handoff save not delivered")) == 1
    assert h.ledger_state() == "aborted"


def test_first_commit_after_save_is_a_landed_save(tmp_path):
    """No commit before, a commit after: the one success shape — the full sequence runs."""
    h = ShaQueue(tmp_path, [_assistant()], shas=(None, "bbb"))
    assert h.run() == 0
    assert h.sent == [SAVE, "/clear", f"/tp-session-restore {SLUG}", drive.resume_line(SLUG)]
    assert h.ledger_state() == "done"


def test_new_session_wait_timeout_reports_incomplete(tmp_path):
    """The restore is sent but no new session reaches a boundary before the deadline:
    `rollover incomplete:`, no resume line, ledger `aborted`, exit 1 (fake clock only)."""
    h = StuckSession(tmp_path, [_assistant()])
    assert h.run() == 1
    assert h.sent == [SAVE, "/clear", f"/tp-session-restore {SLUG}"]
    assert len(h.lines_starting("rollover incomplete:")) == 1
    assert h.ledger_state() == "aborted"
    assert h.now - 1_000.0 < 3_600  # the fake clock advanced; nothing really slept


def test_resume_line_not_delivered_is_loud(tmp_path):
    """The resume line does not reach the input box: exit 1, ledger `aborted`, one line."""
    h = Harness(tmp_path, [_assistant()],
                outcomes=["delivered", "delivered", "delivered", "not-delivered"])
    assert h.run() == 1
    assert h.sent == [SAVE, "/clear", f"/tp-session-restore {SLUG}", drive.resume_line(SLUG)]
    assert len(h.lines_starting("rollover aborted: resume line not delivered")) == 1
    assert h.ledger_state() == "aborted"


def test_real_handoff_sha_distinguishes_error_from_no_handoff(tmp_path):
    """The real seam reads the gitignored file on disk (session-save never commits it):
    an absent file is None, a written file is a fingerprint, a rewrite is a new one, and a
    read failure raises `HandoffUnreadable` instead of passing for "no handoff yet"."""
    handoff = tmp_path / "three-pillars-docs" / "tp-designs" / SLUG / "handoff.md"
    assert drive._handoff_sha(str(tmp_path), SLUG) is None
    handoff.parent.mkdir(parents=True)
    handoff.write_text("# handoff 1\n", encoding="utf-8")
    first = drive._handoff_sha(str(tmp_path), SLUG)
    assert first is not None
    assert drive._handoff_sha(str(tmp_path), SLUG) == first
    handoff.write_text("# handoff 2\n", encoding="utf-8")
    assert drive._handoff_sha(str(tmp_path), SLUG) not in (None, first)

    handoff.unlink()
    handoff.mkdir()  # a directory where the file should be: a read error, not "absent"
    with pytest.raises(drive.HandoffUnreadable):
        drive._handoff_sha(str(tmp_path), SLUG)
