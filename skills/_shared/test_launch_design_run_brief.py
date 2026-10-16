"""Launcher wiring: live pre-probe, seat brief, routing report, first message.

Reuses the `rig` fixture of test_launch_design_run.py; every tmux-touching step is
injected, so no test starts claude, touches real tmux, or pushes to a remote."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_brief as drb  # noqa: E402
import launch_design_run as ldr  # noqa: E402
from test_launch_design_run import _run, rig  # noqa: E402,F401

FIRST_LINE = "Seat (under operator delegation): read seat-brief.md and follow it"
ROUTING = "routing: base_url=http://h:1 haiku=strata profile=personal"


def _brief(rig):
    return os.path.join(rig["wt"], "three-pillars-docs", "tp-designs", "foo", "seat-brief.md")


@pytest.fixture
def spies(monkeypatch):
    calls = []
    monkeypatch.setattr(ldr.design_run_tmux, "live", lambda *a, **k: "")

    def opened(*a, **k):
        calls.append(("open",))
        return ldr.design_run_tmux.OpenResult(True, "design run launched in tmux window seat:2",
                                              "foo:1", "seat")
    monkeypatch.setattr(ldr.design_run_tmux, "open", opened)
    monkeypatch.setattr(ldr.design_run_brief, "commit_brief",
                        lambda wt, slug, path, *a, **k: calls.append(("commit", path)) or "")
    monkeypatch.setattr(ldr.design_run_routing, "wait_for_run",
                        lambda runner, slug, timeout, **k: calls.append(("wait", timeout)) or "77")
    monkeypatch.setattr(ldr.design_run_routing, "read_routing", lambda pid, **k: ROUTING)
    monkeypatch.setattr(ldr.design_run_send, "deliver",
                        lambda slug, line, runner=None, **k:
                        calls.append(("deliver", slug, line, k.get("ready_timeout")))
                        or "delivered")
    return calls


def test_live_run_refuses_before_any_side_effect(rig, spies, capsys, monkeypatch):
    monkeypatch.setattr(ldr.design_run_tmux, "live", lambda *a, **k: "claude")
    assert _run(rig, ["foo", "--skip-design"]) == 2
    cap = capsys.readouterr()
    assert "already live" in cap.err and "/tp-run-full-design" not in cap.out
    assert not os.path.exists(_brief(rig)) and spies == []


def test_live_run_refuses_outside_tmux_too(rig, spies, capsys, monkeypatch):
    monkeypatch.setattr(ldr.design_run_tmux, "live", lambda *a, **k: "claude")
    assert _run(rig, ["foo", "--skip-design"], TMUX=None) == 2
    cap = capsys.readouterr()
    assert "already live" in cap.err and "/tp-run-full-design" not in cap.out
    assert not os.path.exists(_brief(rig)) and spies == []


def test_idle_launch_writes_commits_opens_reports_and_delivers(rig, spies, capsys):
    assert _run(rig, ["foo", "--skip-design"]) == 0
    assert [c[0] for c in spies] == ["commit", "open", "wait", "deliver"]
    assert spies[0][1] == _brief(rig) and os.path.isfile(_brief(rig))
    assert spies[2] == ("wait", 90) and spies[3] == ("deliver", "foo", FIRST_LINE, 90)
    assert ROUTING in capsys.readouterr().out
    assert ldr.design_run_brief.FIRST_LINE == FIRST_LINE


def test_routing_unknown_when_claude_never_comes_up(rig, spies, capsys, monkeypatch):
    monkeypatch.setattr(ldr.design_run_routing, "wait_for_run", lambda *a, **k: None)
    assert _run(rig, ["foo", "--wait", "5"]) == 0
    assert "routing: unknown (claude not up after 5s)" in capsys.readouterr().out


def test_wait_bounds_taking_the_first_message_too(rig, spies):
    assert _run(rig, ["foo", "--wait", "60"]) == 0
    assert spies[-1] == ("deliver", "foo", FIRST_LINE, 60)


def test_wait_zero_skips_the_wait_and_prints_the_send_command(rig, spies, capsys):
    assert _run(rig, ["foo", "--wait", "0"]) == 0
    assert [c[0] for c in spies] == ["commit", "open"]
    out = capsys.readouterr().out
    assert "design_run_send.py foo" in out and FIRST_LINE in out


@pytest.mark.parametrize("outcome", ["unverified", "not-delivered", "tmux-error", "no-session"])
def test_undelivered_first_message_prints_the_command(rig, spies, capsys, monkeypatch, outcome):
    monkeypatch.setattr(ldr.design_run_send, "deliver", lambda *a, **k: outcome)
    assert _run(rig, ["foo"]) == 0
    out = capsys.readouterr().out
    assert outcome in out and "design_run_send.py foo" in out


def test_dry_run_names_the_brief_source_and_writes_nothing(rig, spies, capsys):
    assert _run(rig, ["foo", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "seat brief: template" in out and "TP_DESIGN_RUN=1" in out
    assert not os.path.exists(_brief(rig)) and spies == []


def test_brief_flag_uses_that_file(rig, spies, tmp_path):
    mine = tmp_path / "mine.md"
    mine.write_text("custom brief for {slug}\n", encoding="utf-8")
    assert _run(rig, ["foo", "--brief", str(mine)]) == 0
    assert open(_brief(rig), encoding="utf-8").read() == "custom brief for foo\n"


def test_brief_flag_replacing_the_design_dir_file_prints_a_warning(rig, spies, capsys, tmp_path):
    os.makedirs(os.path.dirname(_brief(rig)))
    with open(_brief(rig), "w", encoding="utf-8") as fh:
        fh.write("seat appended notes\n")
    mine = tmp_path / "mine.md"
    mine.write_text("custom brief for {slug}\n", encoding="utf-8")
    assert _run(rig, ["foo", "--brief", str(mine)]) == 0
    err = capsys.readouterr().err
    assert err.count("warning: replacing existing seat-brief.md") == 1


def test_missing_brief_file_is_refused_up_front(rig, spies, capsys):
    assert _run(rig, ["foo", "--brief", "/nonexistent/brief.md"]) == 2
    assert "brief" in capsys.readouterr().err and spies == []


def test_no_tmux_prints_manual_command_then_the_line_to_type(rig, spies, capsys):
    assert _run(rig, ["foo", "--model", "opus"], TMUX=None) == 2
    out = capsys.readouterr().out
    assert "claude --model opus" in out
    assert out.rstrip().endswith(f"then type: {FIRST_LINE}")
    assert os.path.isfile(_brief(rig)) and [c[0] for c in spies] == ["commit"]


def test_unwritable_brief_warns_and_skips_the_first_message(rig, spies, capsys, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(ldr.design_run_brief, "write_brief", boom)
    assert _run(rig, ["foo"]) == 0
    cap = capsys.readouterr()
    assert "seat brief not written" in cap.err
    assert "deliver" not in [c[0] for c in spies]


def test_explicit_local_flag_silences_the_garbage_tp_local_warning(rig, spies, capsys):
    assert _run(rig, ["foo", "--dry-run"], TP_LOCAL="garbage") == 0
    assert 'TP_LOCAL="garbage"' in capsys.readouterr().err
    assert _run(rig, ["foo", "--dry-run", "--no-local"], TP_LOCAL="garbage") == 0
    assert "TP_LOCAL" not in capsys.readouterr().err
