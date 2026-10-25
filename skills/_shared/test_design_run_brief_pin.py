"""The launcher's `--local-mode` reaches the brief (followups-1024 item 8).

The brief's routing line names the pinned mode when the launch passed a mode flag and
claims no pin when it did not; both forbid a run-set mode."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_brief as drb  # noqa: E402
import launch_design_run as ldr  # noqa: E402

MODES = ("wait", "fallback", "exclusive")


def _brief_path(wt: str) -> str:
    return os.path.join(wt, "three-pillars-docs", "tp-designs", "foo", "seat-brief.md")


@pytest.mark.parametrize("mode", MODES)
def test_pinned_mode_is_named_in_the_routing_line(mode):
    assert f"`TP_LOCAL_MODE={mode}`" in drb.busy_line(mode)


def test_pinned_mode_keeps_the_base_wait_or_fallback_policy():
    assert drb.busy_line("exclusive").startswith(drb.BUSY_LINES["wait"])
    assert drb.busy_line("fallback").startswith(drb.BUSY_LINES["fallback"])


def test_both_pinned_and_unpinned_forbid_a_run_set_mode():
    for line in (drb.busy_line("wait"), drb.busy_line(None)):
        assert "never set, export or prefix `TP_LOCAL_MODE`" in line, line


def test_mode_flag_wins_over_the_seat_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TP_LOCAL_MODE", "fallback")
    monkeypatch.setattr(drb, "commit_brief", lambda *a, **k: "")
    wt, root = str(tmp_path / "wt"), str(tmp_path / "repo")
    args = SimpleNamespace(slug="foo", brief=None, local_mode="wait")
    assert ldr._write_brief(args, wt, root) is not None
    text = open(_brief_path(wt), encoding="utf-8").read()
    assert drb.busy_line("wait") in text
    assert drb.BUSY_LINES["fallback"] not in text


def test_no_mode_flag_claims_no_pin(tmp_path, monkeypatch):
    monkeypatch.setenv("TP_LOCAL_MODE", "wait")
    line = drb.busy_line()
    assert line.startswith(drb.BUSY_LINES["wait"])
    assert "`TP_LOCAL_MODE`" in line and "TP_LOCAL_MODE=" not in line
    monkeypatch.setattr(drb, "commit_brief", lambda *a, **k: "")
    wt, root = str(tmp_path / "wt2"), str(tmp_path / "repo2")
    args = SimpleNamespace(slug="foo", brief=None, local_mode=None)
    assert ldr._write_brief(args, wt, root) is not None
    text = open(_brief_path(wt), encoding="utf-8").read()
    assert drb.busy_line() in text and "TP_LOCAL_MODE=" not in text
