"""test_design_run_tmux_close.py — close spares hand-linked windows; seat-side index.

design: design-run-launch-defaults (Behavior 7, Behavior 3's seat-side index)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_tmux as drt  # noqa: E402
from test_design_run_tmux import FakeTmux  # noqa: E402


class IndexedTmux(FakeTmux):
    """FakeTmux where a linked window takes the next free index in the session it is
    linked into (tmux's real behaviour), and `list-windows` shows that index."""

    def __init__(self):
        super().__init__()
        self.link_index = {}  # (session, window id) -> index in that session

    def _link_window(self, args):
        wid, dest = self._arg(args, "-s"), self._arg(args).rstrip(":").lstrip("=")
        rc, out = super()._link_window(args)
        if rc == 0:
            used = [w["index"] for w in self.sessions[dest]]
            used += [i for (s, _), i in self.link_index.items() if s == dest]
            self.link_index[(dest, wid)] = max(used, default=0) + 1
        return rc, out

    def _list_windows(self, args):
        name, fmt = self._arg(args).lstrip("="), self._arg(args, "-F")
        rows = []
        for w in self._scan(name):
            idx = self.link_index.get((name, w["id"]), w["index"])
            rows.append(fmt.replace("#{window_id}", w["id"])
                        .replace("#{window_index}", str(idx)))
        return (0, "\n".join(rows))


def _world():
    fake = IndexedTmux()
    fake.sessions["seat"] = [{"id": "@0", "index": 1, "dead": False, "cmd": "bash"}]
    fake.sessions["other"] = [{"id": "@9", "index": 5, "dead": False, "cmd": "bash"}]
    return fake


def test_close_spares_a_window_hand_linked_in_from_another_session():
    fake = _world()
    res = drt.open("myrun", "sleep 100", link_into="seat", runner=fake)
    run_wid = fake.sessions["myrun"][0]["id"]
    fake.links.setdefault("myrun", set()).add("@9")  # hand-linked in from `other`
    assert res.ok
    msg = drt.close("myrun", runner=fake, env={})
    assert "closed session myrun" in msg
    assert "myrun" not in fake.sessions
    assert "@9" in {w["id"] for w in fake.sessions["other"]}
    assert run_wid not in {w["id"] for w in fake._scan("seat")}  # the seat link went too
    assert [c[2] for c in fake.sub("kill-window")] == [run_wid]


def test_close_kills_only_the_lowest_index_window_by_id():
    fake = _world()
    fake.sessions["myrun"] = [{"id": "@7", "index": 2, "dead": False, "cmd": "bash"},
                              {"id": "@6", "index": 1, "dead": False, "cmd": "bash"}]
    drt.close("myrun", runner=fake, env={})
    assert fake.sub("kill-window") == [["kill-window", "-t", "@6"]]
    assert fake.sub("kill-session") == [["kill-session", "-t", "=myrun"]]


def test_tmux_set_without_tmux_pane_leaves_the_session_open():
    fake = _world()
    drt.open("myrun", "sleep 100", runner=fake)
    msg = drt.close("myrun", runner=fake, env={"TMUX": "x"})
    assert "left open" in msg and "myrun" in fake.sessions
    assert not fake.sub("kill-window") and not fake.sub("kill-session")


def test_outside_tmux_closes():
    fake = _world()
    drt.open("myrun", "sleep 100", runner=fake)
    assert "closed session myrun" in drt.close("myrun", runner=fake, env={})
    assert "myrun" not in fake.sessions


def test_open_names_the_seat_side_target():
    fake = _world()
    fake.sessions["seat"].append({"id": "@4", "index": 2, "dead": False, "cmd": "bash"})
    res = drt.open("myrun", "sleep 100", link_into="seat", runner=fake)
    wid = fake.sessions["myrun"][0]["id"]
    assert res.ok and res.linked_to == "seat"
    assert fake.link_index[("seat", wid)] == 3
    assert "seat:3" in res.message and "myrun:1" not in res.message
    assert res.target == "myrun:1"


def test_open_message_falls_back_to_slug_side_when_index_unreadable():
    fake = _world()
    real = fake._list_windows
    fake._list_windows = lambda a: (0, "") if "#{window_index}" in a[-1] else real(a)
    res = drt.open("myrun", "sleep 100", link_into="seat", runner=fake)
    assert res.ok and res.linked_to == "seat" and "myrun:1" in res.message
