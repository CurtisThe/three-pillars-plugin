"""test_context_rollover_plan.py — what a rollover saves into, and when background agents hold it.

design: fleet-watcher-reliability (Task 1.3). A run's rollover target is decided by which
design dir exists: `tp-designs/<slug>/` is a live run (save with `/tp-session-save`),
`completed-tp-designs/<slug>/` is a run Tier 5.6 already archived (the save line asks for
the handoff at the completed-dir path, because `/tp-session-save` refuses without the live
dir), and neither is no target at all. `only_background` is the one question that turns a
`held` into an ask: the classifier says `background`, and with the background lines taken
out the pane and transcript are at a turn boundary.

Pure: real temp dirs for `target`, plain strings for panes; no tmux, git or clock.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover_drive as drive  # noqa: E402
import context_rollover_plan as plan  # noqa: E402
from test_context_rollover_drive import SLUG, _assistant  # noqa: E402

DOCS = "three-pillars-docs"
LIVE_HANDOFF = f"{DOCS}/tp-designs/{SLUG}/handoff.md"
DONE_HANDOFF = f"{DOCS}/completed-tp-designs/{SLUG}/handoff.md"
HEADINGS = ("Phase", "Decisions", "State", "Next", "Open Questions", "Carried Forward")
BG = "  2 background tasks · ↓ to manage"


def _dir(root, kind):
    (root / DOCS / kind / SLUG).mkdir(parents=True)


@pytest.mark.parametrize("with_design_md", [False, True], ids=["bare-dir", "design.md"])
def test_a_live_design_dir_is_the_live_target(tmp_path, with_design_md):
    _dir(tmp_path, "tp-designs")
    if with_design_md:
        (tmp_path / DOCS / "tp-designs" / SLUG / "design.md").write_text("x", encoding="utf-8")
    assert plan.target(str(tmp_path), SLUG) == plan.Target(
        handoff_path=LIVE_HANDOFF, save_line=f"/tp-session-save {SLUG}",
        restore_line=f"/tp-session-restore {SLUG}", resume_line=drive.resume_line(SLUG))


def test_an_archived_design_dir_is_the_archived_target(tmp_path):
    _dir(tmp_path, "completed-tp-designs")
    got = plan.target(str(tmp_path), SLUG)
    assert got.handoff_path == DONE_HANDOFF
    assert got.restore_line is None
    assert DONE_HANDOFF in got.save_line and DONE_HANDOFF in got.resume_line
    assert all(h in got.save_line for h in HEADINGS)
    assert "stop" in got.save_line.lower()
    assert "/tp-session-save" not in got.save_line  # that skill refuses without the live dir
    assert "\n" not in got.save_line and "\n" not in got.resume_line  # typed as one line


def test_the_live_dir_wins_when_both_exist(tmp_path):
    _dir(tmp_path, "tp-designs")
    _dir(tmp_path, "completed-tp-designs")
    assert plan.target(str(tmp_path), SLUG).handoff_path == LIVE_HANDOFF


def test_neither_dir_is_no_target(tmp_path):
    (tmp_path / DOCS).mkdir()
    assert plan.target(str(tmp_path), SLUG) is None
    assert plan.target(str(tmp_path / "nowhere"), SLUG) is None


def _only_background(records, pane):
    return plan.only_background(records, pane, 30.0)


def test_only_background_is_true_for_an_end_turn_and_a_background_line():
    assert _only_background([_assistant()], f"✻ Baked for 3s\n{BG}") is True
    assert _only_background([_assistant()], BG) is True  # nothing else in the pane at all


@pytest.mark.parametrize("pane", [
    f"1 shell still running\n{BG}",
    f"✻ Working… (esc to interrupt)\n{BG}",
    f"Do you want to proceed?\n{BG}",
    "✻ Baked for 3s",
    None,
], ids=["shell", "busy", "card", "idle-no-background", "unreadable"])
def test_only_background_is_false_when_something_else_holds_the_pane(pane):
    assert _only_background([_assistant()], pane) is False


def test_only_background_strips_the_count_line_with_the_classifiers_own_test():
    """A reply naming background agents above the harness count line is prose: it stays
    in the pane and is not a blocker, so the ask still goes out (one classifier, r2)."""
    reply = "⏺ Spawned the 2 background agents; waiting as asked."
    assert _only_background([_assistant()], f"{reply}\n{BG}") is True


def test_only_background_is_false_when_the_last_turn_calls_a_tool():
    records = [_assistant(tool_use=True, stop_reason="tool_use")]
    assert _only_background(records, f"✻ Baked for 3s\n{BG}") is False


def test_the_live_ask_names_the_size_the_save_line_and_to_wait():
    live = plan.live_target(SLUG)
    line = plan.ask_line(live, 412000)
    assert "412000" in line
    assert live.save_line in line and live.save_line == f"/tp-session-save {SLUG}"
    assert "wait" in line.lower()
    assert "\n" not in line


def test_the_archived_ask_names_the_completed_handoff_and_never_the_skill(tmp_path):
    _dir(tmp_path, "completed-tp-designs")
    archived = plan.target(str(tmp_path), SLUG)
    line = plan.ask_line(archived, 412000)
    assert "412000" in line and archived.save_line in line
    assert DONE_HANDOFF in line
    assert "/tp-session-save" not in line
    assert "wait" in line.lower()
