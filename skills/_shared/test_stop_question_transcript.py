"""test_stop_question_transcript.py — the Stop hook's transcript fallback (check C5).

design: seat-escalate-first Phase 3 check. When the payload lacks `last_assistant_message`,
the hook joins the text of the turn's trailing assistant lines (a message split over a text
line and a tool_use line still yields its text); a `user` line starts the turn over.
Reuses `test_stop_question_hook`'s fixtures; explicit env, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stop_question_hook as hook  # noqa: E402
from test_stop_question_hook import Q, SEAT, _assistant, _base, _payload, _transcript  # noqa: E402

TOOL_USE = {"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]}}
USER = {"type": "user", "message": {"content": "hi"}}


def _run(tmp_path, *lines):
    base = _base(tmp_path)
    payload = _payload(base, transcript_path=str(_transcript(tmp_path, *lines)))
    del payload["last_assistant_message"]
    return hook.run(payload, env=SEAT)


def test_a_trailing_tool_use_line_does_not_hide_the_question_text(tmp_path):
    out, rc = _run(tmp_path, USER, _assistant(Q), TOOL_USE)
    assert rc == 0 and "/tp-escalate" in out


def test_the_text_blocks_of_trailing_assistant_lines_are_joined(tmp_path):
    out, rc = _run(tmp_path, USER, _assistant("Two ways forward.\nWhich option?\n"),
                   _assistant("1. Rebase\n2. Merge\n"))
    assert rc == 0 and "Which option?" in out


def test_a_question_from_before_the_last_user_line_is_not_read(tmp_path):
    out, rc = _run(tmp_path, _assistant(Q), USER, _assistant("Done. Tests pass."))
    assert (out, rc) == ("", 0)


def test_a_transcript_with_no_assistant_text_allows(tmp_path):
    assert _run(tmp_path, USER, TOOL_USE) == ("", 0)
