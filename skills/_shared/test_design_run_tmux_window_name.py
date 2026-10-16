"""Tests for the run window's name (design-run-launch-fixes Task 1.9).

`open` names the run window `<slug>` and turns `automatic-rename` off for it, for a new
session and for a resumed one; a failing tmux call there never fails the open.
/tp-post-merge tells the seat to close the run from the seat session.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import design_run_tmux as drt
from fake_tmux_fixture import FakeTmux

POST_MERGE = Path(__file__).resolve().parents[1] / "tp-post-merge" / "SKILL.md"


def _named(t, wid, slug):
    return (["set-option", "-w", "-t", wid, "automatic-rename", "off"] in t.calls
            and ["rename-window", "-t", wid, slug] in t.calls)


def test_open_new_session_names_window_and_turns_automatic_rename_off():
    t = FakeTmux()
    res = drt.open("slug-a", "cmd", link_into="seat", runner=t)
    assert res.ok
    win = t.sessions["slug-a"][0]
    assert _named(t, win["id"], "slug-a")
    assert win["name"] == "slug-a" and win["options"]["automatic-rename"] == "off"


def test_open_resumed_session_renames_window_and_turns_automatic_rename_off():
    t = FakeTmux()
    t.sessions["slug-a"] = [{"id": "@7", "index": 1, "dead": True, "cmd": "old",
                             "name": "bash"}]
    res = drt.open("slug-a", "cmd", link_into="seat", runner=t, children=lambda pid: [])
    assert res.ok
    assert t.sub("respawn-window")
    assert _named(t, "@7", "slug-a")
    assert t.sessions["slug-a"][0]["name"] == "slug-a"


def test_open_survives_failing_naming_calls():
    class Failing(FakeTmux):
        def _set_option(self, args):
            return (1, "no such option")

        def _rename_window(self, args):
            return (1, "no such window")

    t = Failing()
    t.sessions["seat"] = [{"id": "@1", "index": 1, "dead": False, "cmd": "", "name": "seat"}]
    res = drt.open("slug-a", "cmd", link_into="seat", runner=t)
    assert res.ok and res.linked_to == "seat"


def test_post_merge_tells_the_seat_to_close_from_the_seat_session():
    body = " ".join(POST_MERGE.read_text(encoding="utf-8").split())
    assert "design_run_tmux.py close" in body
    assert "from the seat" in body
