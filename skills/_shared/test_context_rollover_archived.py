"""test_context_rollover_archived.py — rolling over a run whose design dir Tier 5.6 archived.

design: fleet-watcher-reliability (Task 1.3). A finished-but-unmerged run can reach 488k
context after `/tp-design-complete` moved `tp-designs/<slug>/` to `completed-tp-designs/`,
and `/tp-session-save` refuses without the live dir. The archived target saves by asking for
the handoff at the completed-dir path, waits for THAT file to change before `/clear`, and
resumes from it with no restore line. A run with no design dir at all is `unavailable`
(a seed-only run, a slug mismatch), never a blind `/clear`.

Every seam is a fake except the `real_seams` case, which uses a temp worktree and a fake
tmux runner.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover_drive as drive  # noqa: E402
import context_rollover_plan as plan  # noqa: E402
from test_context_rollover_ask import TargetHarness  # noqa: E402
from test_context_rollover_drive import SLUG, _assistant  # noqa: E402

DOCS = "three-pillars-docs"
DONE_DIR = f"{DOCS}/completed-tp-designs/{SLUG}"


def _archived(tmp_path):
    (tmp_path / DONE_DIR).mkdir(parents=True)
    return plan.target(str(tmp_path), SLUG)


class WatchedHarness(TargetHarness):
    """Records the handoff fingerprint at the moment `/clear` is typed."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = False
        self.polls_after_save = 0
        self.current = "aaa"
        self.sha_at_clear = "never sent"

    def send(self, slug, line):
        self.saved = self.saved or line != "/clear"
        if line == "/clear":
            self.sha_at_clear = self.current
        return super().send(slug, line)

    def handoff_sha(self):
        if self.saved:
            self.polls_after_save += 1
            self.current = "aaa" if self.polls_after_save < 4 else "bbb"  # lands later
        return self.current


def test_the_archived_sequence_is_save_clear_resume_with_no_restore(tmp_path):
    target = _archived(tmp_path)
    h = WatchedHarness(tmp_path, [_assistant()])
    assert h.run(target=target) == 0
    assert h.sent == [target.save_line, "/clear", target.resume_line]
    assert not any(line.startswith("/tp-session-") for line in h.sent)
    assert DONE_DIR in h.sent[0] and DONE_DIR in h.sent[-1]
    assert h.ledger_state() == "done"


def test_clear_is_sent_only_after_the_completed_handoff_changed(tmp_path):
    target = _archived(tmp_path)
    h = WatchedHarness(tmp_path, [_assistant()])
    assert h.run(target=target) == 0
    assert h.sha_at_clear == "bbb"
    assert h.polls_after_save >= 4


def test_a_handoff_that_never_changes_aborts_without_clear(tmp_path):
    target = _archived(tmp_path)
    h = TargetHarness(tmp_path, [_assistant()], shas=("aaa", "aaa"))
    assert h.run(target=target) == 1
    assert h.sent == [target.save_line]
    assert h.lines_starting("rollover aborted: handoff save did not land")
    assert h.ledger_state() == "aborted"


def test_the_handoff_fingerprint_reads_the_completed_dir(tmp_path):
    handoff = tmp_path / DONE_DIR / "handoff.md"
    handoff.parent.mkdir(parents=True)
    assert drive._handoff_sha(str(tmp_path), SLUG) is None
    handoff.write_text("# handoff\n", encoding="utf-8")
    first = drive._handoff_sha(str(tmp_path), SLUG)
    assert first is not None
    handoff.write_text("# handoff 2\n", encoding="utf-8")
    assert drive._handoff_sha(str(tmp_path), SLUG) not in (None, first)


def _real_seams(tmp_path, monkeypatch, sent):
    monkeypatch.setattr(drive.drt, "_tmux_runner", lambda _env: lambda args: (0, ""))
    lines = []
    seams = drive.real_seams(SLUG, str(tmp_path), {"PATH": ""}, out=lines.append)
    seams.update(send=lambda slug, line: sent.append(line) or "delivered", out=lines.append)
    return seams, lines


def test_a_worktree_with_no_design_dir_is_unavailable(tmp_path, monkeypatch):
    (tmp_path / DOCS).mkdir()  # a real checkout: the docs tree is there, this slug's dirs are not
    sent = []
    seams, lines = _real_seams(tmp_path, monkeypatch, sent)
    assert seams["target"] is None
    assert seams["tmux_blocker"] == f"no design dir for {SLUG}"
    assert drive.rollover(SLUG, str(tmp_path), **seams) == 0
    assert lines == [f"context rollover unavailable: no design dir for {SLUG}"]
    assert sent == []


def test_real_seams_hands_over_the_target_for_a_live_or_archived_dir(tmp_path, monkeypatch):
    (tmp_path / DOCS / "tp-designs" / SLUG).mkdir(parents=True)
    seams, _lines = _real_seams(tmp_path, monkeypatch, [])
    assert seams["target"] == plan.target(str(tmp_path), SLUG)
    assert seams["tmux_blocker"] is None
