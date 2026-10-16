"""test_local_dispatch_no_repair.py — no in-place repair, prose guard (run-throughput 2.11).

design: run-throughput (attempt-integrity, amendment 2, dd §A2 / §Tests). Content checks
only: `local-dispatch.md` names the rule, `agents/tp-worker.md` points to it, and no step
anywhere in `local-dispatch.md` tells the dispatcher to edit an attempt it has checked.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DISPATCH = (HERE / "local-dispatch.md").read_text(encoding="utf-8")
TP_WORKER_MD = ROOT / "agents" / "tp-worker.md"


def _section(text: str, head: str, nxt: str) -> str:
    start = text.index(head)
    end = text.find(nxt, start + len(head))
    return text[start:end if end != -1 else len(text)]


def test_attempt_integrity_section_exists_and_names_the_rule():
    sec = _section(DISPATCH, "### Attempt integrity", "\n## 3.")
    for needle in ("edited-after-pass", "never edits", "flag: post-pass"):
        assert needle in sec, needle


def test_attempt_integrity_section_names_the_two_post_pass_outcomes():
    sec = _section(DISPATCH, "### Attempt integrity", "\n## 3.")
    assert "FAIL" in sec and "discard" in sec and "decisions.md" in sec


def test_tp_worker_points_at_the_section():
    if not TP_WORKER_MD.is_file():
        pytest.skip("agents/tp-worker.md not in this install")
    text = TP_WORKER_MD.read_text(encoding="utf-8")
    assert "local-dispatch.md" in text and "Attempt integrity" in text


def test_no_step_tells_the_dispatcher_to_edit_a_checked_attempt():
    for needle in re.findall(r"amend|commit in|repair", DISPATCH, re.I):
        assert needle.lower() == "repair"  # only the "never an in-place repair" mention


def test_dispatch_doc_stays_under_cap():
    # strata-session-isolation 5.2: re-pinned 260 → 275 (child-spawn wiring)
    assert len(DISPATCH.splitlines()) <= 275
