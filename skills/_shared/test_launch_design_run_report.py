"""test_launch_design_run_report.py — the launch report reads the real child and confirms
delivery from the transcript.

design: design-run-launch-fixes (Task 1.4; Evidence 2026-10-09: both readouts raced the child)

Every tmux, process-table, environ, clock and sleep call is injected: no test starts claude,
touches a real tmux server or sleeps.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_brief as drb  # noqa: E402
import design_run_delivery as drd  # noqa: E402
import design_run_routing as drr  # noqa: E402
import design_run_send as drs  # noqa: E402
import design_run_tmux as drt  # noqa: E402
import launch_design_run as ldr  # noqa: E402
import test_design_run_send as tsend  # noqa: E402
from test_design_run_routing import Clock  # noqa: E402
from test_launch_design_run import _run, rig  # noqa: E402,F401
from test_launch_design_run_brief import spies  # noqa: E402,F401

LINE = tsend.LINE
SHELL = ("900", "1", "bash")  # the run window's pane process
WRAPPER = ("901", "900", "claude --model sonnet /tp-run-full-design foo")  # Homelab launcher
CHILD = ("902", "901", "/opt/claude/bin/claude --model sonnet /tp-run-full-design foo")
ENVIRONS = {
    "901": b"PATH=/bin\0CLAUDE_CONFIG_DIR=/p/aris\0",
    "902": (b"ANTHROPIC_BASE_URL=http://127.0.0.1:3457\0ANTHROPIC_DEFAULT_HAIKU_MODEL=strata\0"
            b"CLAUDE_CONFIG_DIR=/p/aris\0CLAUDE_LAUNCHER_OWNED=ANTHROPIC_BASE_URL,TP_LOCAL\0"),
}
CHILD_ROUTING = "routing: base_url=http://127.0.0.1:3457 haiku=strata profile=aris"
OWNED = {"CLAUDE_LAUNCHER_OWNED": "ANTHROPIC_BASE_URL,TP_LOCAL"}

ECHOED = f"> {LINE}\n\n✻ Working…\n│ > │\n"
GHOSTED = f"> {LINE}\n│ > \x1b[2mTry \"fix the lint\"\x1b[0m │\n"
WRAPPED = "> Seat (under operator delegation): read seat-brief.md and\n  follow it\n│ > │\n"
INSIDE = f"> {LINE}\n│ > {LINE} │\n"  # an earlier copy above, this one still unsent


def read(path):
    """A fake `/proc/<pid>/environ` reader over ENVIRONS."""
    pid = path.split("/")[2]
    if pid not in ENVIRONS:
        raise FileNotFoundError(path)
    return ENVIRONS[pid]


class Tmux(tsend.FakeTmux):
    """The send fake (canned frames, the last repeats) plus the run window's live pane 900."""

    def __call__(self, args):
        if list(args)[0] == "list-panes":
            self.calls.append(list(args))
            return 0, "0 900"
        return super().__call__(args)


def _wait(tables, timeout=30, **kw):
    """`wait_for_run` over successive `ps` tables (the last repeats); returns (pid, clock)."""
    clock, seq = Clock(), list(tables)

    def table():
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return drr.wait_for_run(Tmux([tsend.EMPTY]), "foo", timeout, table=table, clock=clock,
                            sleep=clock.sleep, **kw), clock


def _launch_report(tmux, tables, env=None, wait=30.0):
    """The whole launch report on `tmux` (the shipped template as the written brief); returns
    the first-message outcome."""
    clock, seq = Clock(), list(tables)

    def table():
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return drd.report("foo", tmux, wait, brief=(drb.TEMPLATE, "template"), env=env or {},
                      table=table, read=read, clock=clock, sleep=clock.sleep)


# --- routing: the deepest claude, waited on until the launcher has set its route --------------

def test_routing_reads_the_deepest_claude_not_the_launcher_wrapper():
    """(a) the first `claude` under the pane is the launcher wrapper: no route in its environ."""
    pid, _ = _wait([[SHELL, WRAPPER, CHILD]])
    assert drr.read_routing(pid, read=read).startswith(CHILD_ROUTING)
    assert drt.find_run_pid("900", [SHELL, WRAPPER, CHILD], deepest=True) == "902"


def test_report_prints_the_child_routing(capsys):
    _launch_report(Tmux([tsend.EMPTY]), [[SHELL, WRAPPER, CHILD]], env=OWNED)
    assert any(ln.startswith(CHILD_ROUTING) for ln in capsys.readouterr().out.splitlines())


def test_child_appearing_on_the_third_poll_is_the_one_read(capsys):
    """(b) polls 1-2 see only the wrapper; the seat had a launcher, so the wait goes on until the
    chosen pid carries CLAUDE_LAUNCHER_OWNED."""
    early = [SHELL, WRAPPER]
    pid, clock = _wait([early, early, [SHELL, WRAPPER, CHILD]], owned=True, read=read)
    assert pid == "902" and len(clock.slept) == 2
    _launch_report(Tmux([tsend.EMPTY]), [early, early, [SHELL, WRAPPER, CHILD]], env=OWNED)
    assert any(ln.startswith(CHILD_ROUTING) for ln in capsys.readouterr().out.splitlines())


def test_a_child_that_never_settles_is_reported_as_pending():
    pid, clock = _wait([[SHELL, WRAPPER]], timeout=7, owned=True, read=read)
    assert pid == "901" and clock.t <= 7 and len(clock.slept) > 1
    line = drr.read_routing(pid, read=read, owned=True)
    assert line.startswith("routing: base_url=unset haiku=unset profile=aris")
    assert "routing: pending" in line


def test_without_a_launcher_in_the_seat_env_the_first_find_is_final(capsys):
    pid, clock = _wait([[SHELL, WRAPPER]], owned=False, read=read)
    assert pid == "901" and clock.slept == []
    assert "pending" not in drr.read_routing(pid, read=read)
    _launch_report(Tmux([tsend.EMPTY]), [[SHELL, WRAPPER], [SHELL, WRAPPER, CHILD]], env={})
    assert "routing: base_url=unset haiku=unset profile=aris" in capsys.readouterr().out


def test_direct_run_base_url_unset_is_not_waited_on():
    """A direct run has no base url; the launcher marker alone says the route is final."""
    direct = b"CLAUDE_CONFIG_DIR=/p/aris\0CLAUDE_LAUNCHER_OWNED=CLAUDE_CONFIG_DIR\0"
    pid, clock = _wait([[SHELL, WRAPPER, CHILD]], owned=True, read=lambda path: direct)
    assert pid == "902" and clock.slept == []
    assert drr.read_routing(pid, read=lambda path: direct, owned=True).startswith(
        "routing: base_url=unset haiku=unset profile=aris")


def test_an_unreadable_environ_is_not_waited_on():
    def no_proc(path):
        raise FileNotFoundError(path)
    pid, clock = _wait([[SHELL, WRAPPER]], owned=True, read=no_proc)
    assert pid == "901" and clock.slept == []


def test_the_launch_passes_the_seat_launcher_marker_to_the_wait(rig, spies, monkeypatch):
    seen = []
    monkeypatch.setattr(ldr.design_run_routing, "wait_for_run",
                        lambda runner, slug, timeout, **k: seen.append(k.get("owned")) or "77")
    assert _run(rig, ["foo"]) == 0
    assert _run(rig, ["foo"], CLAUDE_LAUNCHER_OWNED="TP_LOCAL") == 0
    assert seen == [False, True]


# --- delivery: confirmed from the transcript, never from an unsent box ------------------------

def test_in_transcript_needs_the_text_above_an_empty_or_ghost_box():
    for frame in (ECHOED, GHOSTED, WRAPPED):
        assert drs.in_transcript(frame, LINE), frame
    for frame in (tsend.FULL, INSIDE, tsend.EMPTY, f"> {LINE}\n✻ Working…\n"):
        assert not drs.in_transcript(frame, LINE), frame


@pytest.mark.parametrize("after", [ECHOED, GHOSTED, WRAPPED])
@pytest.mark.parametrize("checks", [[tsend.FULL, tsend.FULL], ["✻ Starting…\n"]],
                         ids=["not-delivered", "unverified"])
def test_brief_above_an_empty_box_is_reported_delivered(capsys, checks, after):
    """(c) the TUI took the Enter late (seen 2026-10-09): the transcript shows the brief."""
    tmux = Tmux([tsend.EMPTY, *checks, after])
    assert _launch_report(tmux, [[SHELL, WRAPPER, CHILD]], env=OWNED) == "delivered"
    assert "first message" not in capsys.readouterr().out


@pytest.mark.parametrize("stuck", [tsend.FULL, INSIDE])
def test_brief_still_inside_the_box_stays_not_delivered(capsys, stuck):
    tmux = Tmux([tsend.EMPTY, tsend.FULL, stuck])
    assert _launch_report(tmux, [[SHELL, WRAPPER, CHILD]], env=OWNED, wait=20) == "not-delivered"
    assert "first message not-delivered; send it with:" in capsys.readouterr().out
    assert tmux.keys().count(["Enter"]) == 2  # confirming types nothing


# --- the brief line -----------------------------------------------------------------------------

@pytest.mark.parametrize("extra,source", [([], "template"), (["--brief"], "--brief")])
def test_report_names_the_brief_source_and_its_blob(rig, spies, capsys, tmp_path, extra, source):
    """(d) the seat sees which brief the run was told to follow (delegated authority)."""
    if extra:
        mine = tmp_path / "mine.md"
        mine.write_text("custom brief for {slug}\n", encoding="utf-8")
        extra = [*extra, str(mine)]
    assert _run(rig, ["foo", "--skip-design", *extra]) == 0
    path = os.path.join(rig["wt"], "three-pillars-docs", "tp-designs", "foo", "seat-brief.md")
    line = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("seat brief:"))
    blob = subprocess.run(["git", "hash-object", path], capture_output=True, text=True,
                          check=True).stdout.strip()
    shown = line.split("blob ", 1)[1].rstrip(")")
    assert path in line and source in line
    assert len(shown) >= 7 and blob.startswith(shown)
