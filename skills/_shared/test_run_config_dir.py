"""test_run_config_dir.py — a run's real config dir, read from its `claude` process environ.

design: fleet-watcher-reliability (Task 1.2). A classicai run launched from a personal seat
keeps its transcripts under the classicai profile, not the seat's `CLAUDE_CONFIG_DIR`, so
the only honest source is the run's own process: the deepest `claude` under the slug's run
window (the first is the Homelab launcher's wrapper) and its `/proc/<pid>/environ`.
`config_dir` answers that path or None, never raising; `project_dir` turns it into the
transcript directory and otherwise falls back to `design_run_observe.project_dir` exactly.

Fakes only: the tmux runner is `FakeTmux`, the process table a list and `/proc` a function.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_observe as dro  # noqa: E402
import run_config_dir as rcd  # noqa: E402
from test_design_run_tmux import FakeTmux  # noqa: E402

SLUG = "myrun"
# FakeTmux names a window's pane pid "p" + the window id; the run window is the lowest index.
TABLE = [("p@6", "1", "bash"),
         ("500", "p@6", "/usr/bin/claude --launcher-wrapper"),
         ("501", "500", "claude --model x /tp-run-full-design myrun")]


def _world(slug=SLUG):
    fake = FakeTmux()
    fake.sessions[slug] = [{"id": "@7", "index": 2, "dead": False, "cmd": "bash"},
                           {"id": "@6", "index": 1, "dead": False, "cmd": "bash"}]
    return fake


def _environ(**pairs):
    return "".join(f"{k}={v}\0" for k, v in pairs.items()).encode()


def _proc(tmp_path, wrapper_cfg="wrapper"):
    """A fake `/proc`: the wrapper's environ names another dir than the child's."""
    seen = []
    blobs = {"/proc/500/environ": _environ(HOME="/h", CLAUDE_CONFIG_DIR=str(tmp_path / wrapper_cfg)),
             "/proc/501/environ": _environ(HOME="/h", CLAUDE_CONFIG_DIR=str(tmp_path / "classicai"))}

    def read(path):
        seen.append(path)
        return blobs[path]
    return read, seen


def test_config_dir_is_the_deepest_claude_environ(tmp_path):
    read, seen = _proc(tmp_path)
    got = rcd.config_dir(SLUG, _world(), table=lambda: TABLE, read=read)
    assert got == str(tmp_path / "classicai")
    assert seen == ["/proc/501/environ"]  # the child, never the launcher's wrapper


def test_config_dir_accepts_a_plain_table(tmp_path):
    read, _ = _proc(tmp_path)
    assert rcd.config_dir(SLUG, _world(), table=TABLE, read=read) == str(tmp_path / "classicai")


def test_config_dir_none_when_the_environ_is_unreadable(tmp_path):
    def read(path):
        raise OSError("no /proc")
    assert rcd.config_dir(SLUG, _world(), table=lambda: TABLE, read=read) is None

    def denied(path):
        raise PermissionError(path)
    assert rcd.config_dir(SLUG, _world(), table=lambda: TABLE, read=denied) is None


def test_config_dir_none_without_a_window_or_a_claude(tmp_path):
    read, _ = _proc(tmp_path)
    assert rcd.config_dir("other", _world(), table=lambda: TABLE, read=read) is None  # no window
    idle = [("p@6", "1", "bash"), ("600", "p@6", "sleep 5")]
    assert rcd.config_dir(SLUG, _world(), table=lambda: idle, read=read) is None  # no claude
    assert rcd.config_dir(SLUG, _world(), table=lambda: None, read=read) is None  # ps unreadable
    assert rcd.config_dir(SLUG, None, table=lambda: TABLE, read=read) is None  # no tmux


def test_config_dir_none_without_the_key(tmp_path):
    for blob in (_environ(HOME="/h"), _environ(CLAUDE_CONFIG_DIR=""), b""):
        assert rcd.config_dir(SLUG, _world(), table=lambda: TABLE,
                              read=lambda path, blob=blob: blob) is None


def test_config_dir_never_raises(tmp_path):
    def broken(args):
        raise RuntimeError("tmux server went away")
    read, _ = _proc(tmp_path)
    assert rcd.config_dir(SLUG, broken, table=lambda: TABLE, read=read) is None

    def bad_table():
        raise ValueError("ps output unparseable")
    assert rcd.config_dir(SLUG, _world(), table=bad_table, read=read) is None


def test_project_dir_is_under_the_runs_own_config_dir(tmp_path):
    read, _ = _proc(tmp_path)
    wt = "/home/x/my_wt.1"
    got = rcd.project_dir(SLUG, wt, _world(), {"CLAUDE_CONFIG_DIR": str(tmp_path / "personal")},
                          table=lambda: TABLE, read=read)
    assert got == tmp_path / "classicai" / "projects" / "-home-x-my-wt-1"


def test_project_dir_resolves_a_relative_worktree(tmp_path, monkeypatch):
    read, _ = _proc(tmp_path)
    monkeypatch.chdir(tmp_path)
    rel = rcd.project_dir(SLUG, "rel", _world(), {}, table=lambda: TABLE, read=read)
    absolute = rcd.project_dir(SLUG, str(tmp_path / "rel"), _world(), {},
                               table=lambda: TABLE, read=read)
    assert rel == absolute and rel.parent == tmp_path / "classicai" / "projects"


def test_project_dir_falls_back_to_todays_resolution(tmp_path):
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "personal"), "PATH": "", "HOME": str(tmp_path)}
    wt = str(tmp_path / "wt")

    def unreadable(path):
        raise OSError("no /proc")
    expected = dro.project_dir(wt, env)
    assert expected.parent == tmp_path / "personal" / "projects"
    for world, table in ((_world(), lambda: TABLE),  # environ unreadable
                         (_world("elsewhere"), lambda: TABLE),  # no window for the slug
                         (_world(), lambda: [])):  # no claude
        assert rcd.project_dir(SLUG, wt, world, env, table=table, read=unreadable) == expected
