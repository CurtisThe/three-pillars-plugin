"""Example tests for design_run_resume_run (design: fleet-windows-reboot-resume, Task 1.4).

Every outside effect is an injected fake (in-memory tmux with numeric pane pids, process
table, environ reader, recording `deliver`, fake clock, list as print sink). No test signals a
real PID or reads the real /proc or `ps`.
"""
import functools
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import context_rollover_state as crs  # noqa: E402
import design_run_command as drc  # noqa: E402
import design_run_observe as dro  # noqa: E402
import design_run_resume_run as rr  # noqa: E402
import design_run_routing as route  # noqa: E402
import design_run_send  # noqa: E402
import design_run_tmux as drt  # noqa: E402
from fake_tmux_fixture import FakeTmux  # noqa: E402

SLUG = "my-design"
SID_A = "11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SID_B = "22222222-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
PANE, CLAUDE = 4242, 9999  # the run window's group leader, and the deepest claude under it
TABLE = [("4242", "1", "-bash"), ("9999", "4242", "claude --resume x --model m")]
CONTINUE = ("Seat (under operator delegation): the machine restarted and this session was "
            "resumed; check git status and the plan, then continue from where the run stopped")


class PaneTmux(FakeTmux):
    """FakeTmux whose every pane reports the numeric pid PANE."""

    def _pane(self, w, fmt):
        dead = "1" if w["dead"] else "0"
        return fmt.replace("#{pane_dead}", dead).replace("#{pane_pid}", str(PANE))

    def _display_message(self, args):
        if args[-1] == "#{pane_pid}":
            return (0, str(PANE)) if self._find(self._arg(args))[1] else self._stale(args)
        return super()._display_message(args)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Rig:
    def __init__(self, tmp_path):
        self.env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "profile"), "HOME": str(tmp_path / "home"),
                    "PATH": "", "TMUX": "1"}
        self.wt = tmp_path / "wt" / SLUG
        self.wt.mkdir(parents=True)
        self.fake = PaneTmux()
        self.fake.sessions["seat"] = [{"id": "@0", "index": 1, "dead": False, "cmd": "bash"}]
        self.lines, self.delivered, self.busy, self.outcome = [], [], "", design_run_send.DELIVERED
        self.clock = Clock()

    def transcript(self, sid, mtime):
        pdir = dro.project_dir(str(self.wt), self.env)
        pdir.mkdir(parents=True, exist_ok=True)
        path = pdir / f"{sid}.jsonl"
        path.write_text("{}\n")
        os.utime(path, (mtime, mtime))
        return path

    def fleet_worker(self):
        run = self.wt / ".three-pillars" / "run"
        run.mkdir(parents=True)
        (run / "run.pid").write_text("123\n")
        (run / "state.json").write_text(json.dumps({"supervisor": {"pid": 123}}))
        return run

    def deliver(self, slug, line, runner, **kw):
        self.delivered.append((slug, line, runner, kw))
        return self.outcome

    def environ(self, path):
        if path.endswith("/environ"):
            return b"CLAUDE_CONFIG_DIR=/p/work\0ANTHROPIC_BASE_URL=http://r\0"
        return b"claude\0--resume\0x\0"

    def resume(self, **over):
        kw = dict(session=None, wait=5, env=self.env, cmd_builder=lambda sid: f"CMD {sid}",
                  runner=self.fake, live_fn=lambda slug, runner: self.busy, table=TABLE,
                  read=self.environ, has_proc=lambda: True, deliver_fn=self.deliver,
                  clock=self.clock, sleep=self.clock.sleep, tp_root="/opt/tp",
                  fresh_cmd="python3 /x/launch_design_run.py my-design",
                  out=self.lines.append, err=self.lines.append)
        kw.update(over)
        return rr.resume(SLUG, str(self.wt), **kw)

    def opened(self):
        return self.fake.sub("new-session") + self.fake.sub("respawn-window")

    def has(self, text):
        return [ln for ln in self.lines if text in ln]


def pid_of(run):
    return (run / "run.pid").read_text(encoding="utf-8")


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def test_success_opens_the_resume_command_and_reports(rig):
    rig.transcript(SID_A, 1000)
    rig.transcript(SID_B, 3000)
    rig.fleet_worker()
    def build(sid):
        return drc.resume_window_command(SLUG, str(rig.wt), sid, model="sonnet")

    assert rig.resume(cmd_builder=build) == 0
    want = drc.resume_window_command(SLUG, str(rig.wt), SID_B, model="sonnet")
    assert [c[-1] for c in rig.fake.sub("new-session")] == [want]  # the newest sid, verbatim
    assert "seat" in rig.fake.links and rig.fake.links["seat"]  # linked into the launching session
    rows = [ln for ln in rig.lines if ln.startswith("resumed ")]
    assert rows == [f"resumed {SLUG}: session {SID_B} (last written 1970-01-01T00:50:00Z)"]
    transcript = dro.project_dir(str(rig.wt), rig.env) / f"{SID_B}.jsonl"
    rearm = f"re-arm: python3 /opt/tp/skills/_shared/design_run_watch.py {SLUG}"
    assert rig.lines.count(rearm) == 1
    assert any(ln.startswith("routing: base_url=http://r") for ln in rig.lines)  # the claude child
    for point in (f"/proc/{CLAUDE}/environ", f"/proc/{CLAUDE}/cwd", str(transcript)):
        assert len(rig.has(point)) == 1
    assert rig.has(f"/proc/{CLAUDE}/cwd")[0].count(str(rig.wt)) == 1
    order = [rig.lines.index(rows[0]), rig.lines.index(rig.has("run state")[0]),
             rig.lines.index(rearm)]
    assert order == sorted(order)


def test_named_session_resumes_that_sid(rig):
    rig.transcript(SID_A, 1000)
    rig.transcript(SID_B, 3000)
    assert rig.resume(session=SID_A) == 0
    assert rig.fake.sub("new-session")[0][-1] == f"CMD {SID_A}"


def test_an_ended_session_is_respawned_in_place(rig):
    rig.transcript(SID_A, 1000)
    rig.fake.sessions[SLUG] = [{"id": "@7", "index": 1, "dead": True, "cmd": "old"}]
    assert rig.resume() == 0
    assert rig.fake.sub("respawn-window") == [["respawn-window", "-k", "-t", "@7", f"CMD {SID_A}"]]
    assert not rig.fake.sub("new-session")


def test_a_live_run_is_refused_and_nothing_opens(rig):
    rig.transcript(SID_A, 1000)
    rig.busy = "claude"
    assert rig.resume() == 2
    assert rig.has(drt.live_message(SLUG, "claude")) and not rig.opened() and not rig.delivered


def test_no_transcript_prints_the_fresh_command_and_opens_nothing(rig):
    assert rig.resume() == 2
    assert rig.has(f"no session to resume for {SLUG}")
    assert rig.lines.count("python3 /x/launch_design_run.py my-design") == 1
    assert not rig.opened() and not rig.delivered


def test_unknown_session_names_the_dir_and_opens_nothing(rig):
    rig.transcript(SID_A, 1000)
    assert rig.resume(session="nope-1") == 2
    assert rig.has(str(dro.project_dir(str(rig.wt), rig.env)))
    assert "python3 /x/launch_design_run.py my-design" in rig.lines
    assert not rig.opened() and not rig.delivered


def test_the_pane_pid_is_written_never_the_claude_pid(rig):
    rig.transcript(SID_A, 1000)
    run = rig.fleet_worker()
    assert rig.resume() == 0
    assert pid_of(run) == f"{PANE}\n"
    assert json.loads((run / "state.json").read_text(encoding="utf-8"))["supervisor"]["pid"] == PANE
    assert str(CLAUDE) not in pid_of(run)
    assert rig.has("run state refreshed") and not rig.has("not refreshed")


def test_a_plain_run_is_never_given_a_run_dir(rig):
    rig.transcript(SID_A, 1000)
    assert rig.resume() == 0
    assert not (rig.wt / ".three-pillars").exists()
    assert not rig.has("run state refreshed")


def test_wait_zero_skips_the_wait_the_continue_line_and_the_refresh(rig):
    rig.transcript(SID_A, 1000)
    run = rig.fleet_worker()

    def no_wait(*a, **k):
        raise AssertionError("must not wait at --wait 0")

    assert rig.resume(wait=0, wait_fn=no_wait) == 0
    assert not rig.delivered
    assert pid_of(run) == "123\n"
    manual = design_run_send.manual_command(SLUG, rr.CONTINUE_LINE)
    assert [ln for ln in rig.lines if manual in ln]
    state = rig.has("run state not refreshed (--wait 0)")
    assert len(state) == 1 and rr.refresh_command(SLUG, str(rig.wt)) in state[0]


def test_claude_never_up_skips_the_refresh_and_the_continue_line(rig):
    rig.transcript(SID_A, 1000)
    run = rig.fleet_worker()
    assert rig.resume(wait=3, table=[("4242", "1", "-bash")]) == 0
    assert "routing: unknown (claude not up after 3s)" in rig.lines
    assert not rig.delivered and pid_of(run) == "123\n"
    assert rig.has("run state not refreshed") and rig.has(
        design_run_send.manual_command(SLUG, rr.CONTINUE_LINE))


def test_the_fixed_continue_line_goes_through_deliver(rig):
    rig.transcript(SID_A, 1000)
    assert rig.resume() == 0
    assert rr.CONTINUE_LINE == CONTINUE
    [(slug, line, runner, kw)] = rig.delivered
    assert (slug, line, runner) == (SLUG, CONTINUE, rig.fake) and kw["ready_timeout"] == 5
    assert not rig.has("send it with")


def test_an_undelivered_continue_line_prints_the_manual_command(rig):
    rig.transcript(SID_A, 1000)
    rig.outcome = design_run_send.NOT_DELIVERED
    assert rig.resume() == 0
    [row] = rig.has("not-delivered")
    assert design_run_send.manual_command(SLUG, CONTINUE) in row


def test_a_claimed_ledger_entry_warns_exactly_once_and_a_finished_one_not_at_all(rig):
    rig.transcript(SID_A, 1000)
    ledger = rig.fleet_worker() / "context-rollover.json"
    assert crs.claim(ledger, SID_A, now=1.0)
    assert rig.resume() == 0
    assert len(rig.has("no rollover will fire")) == 1
    assert crs.finish(ledger, SID_A, "done")
    rig.lines.clear()
    assert rig.resume(open_fn=functools.partial(drt.open, children=lambda pid: [])) == 0
    assert not rig.has("no rollover will fire")


def test_no_tmux_prints_the_manual_command_and_opens_nothing(rig):
    rig.transcript(SID_A, 1000)
    assert rig.resume(runner=None) == 2
    assert f"CMD {SID_A}" in rig.lines and not rig.fake.calls and not rig.delivered


def test_a_failed_open_prints_the_manual_command(rig):
    rig.transcript(SID_A, 1000)
    boom = lambda *a, **k: drt.OpenResult(False, "tmux new-session failed: boom")  # noqa: E731
    assert rig.resume(open_fn=boom) == 2
    assert rig.has("boom") and f"CMD {SID_A}" in rig.lines and not rig.delivered


def test_no_proc_marks_the_refresh_and_the_routing_readout_unavailable(rig):
    rig.transcript(SID_A, 1000)
    run = rig.fleet_worker()

    def no_read(path):
        raise OSError("no /proc")

    assert rig.resume(has_proc=lambda: False, read=no_read) == 0
    assert route.UNAVAILABLE in rig.lines
    [state] = rig.has("run state")
    assert "unavailable (no /proc)" in state
    assert pid_of(run) == "123\n"


def _two_worktrees(rig, tmp_path):
    other = tmp_path / "wt" / "other-one"
    other.mkdir()
    rig.transcript(SID_A, 1000)  # SLUG's: before boot
    pdir = dro.project_dir(str(other), rig.env)
    pdir.mkdir(parents=True)
    (pdir / f"{SID_B}.jsonl").write_text("{}\n")
    os.utime(pdir / f"{SID_B}.jsonl", (9000, 9000))  # after boot
    return [(SLUG, str(rig.wt)), ("other-one", str(other))]


def test_list_resumable_prints_a_row_per_candidate(rig, tmp_path):
    rows = _two_worktrees(rig, tmp_path)
    assert rr.list_resumable(rows, rig.env, boot_fn=lambda: 5000, live_fn=lambda s, r: "",
                             out=rig.lines.append) == 0
    assert rig.lines == [f"{SLUG} {SID_A} 1970-01-01T00:16:40Z"]


def test_list_resumable_says_none_and_skips_live_runs(rig, tmp_path):
    rows = _two_worktrees(rig, tmp_path)
    assert rr.list_resumable(rows, rig.env, boot_fn=lambda: 5000, live_fn=lambda s, r: "claude",
                             out=rig.lines.append) == 0
    assert rig.lines == ["none"]


def test_list_resumable_with_an_unknown_boot_time_says_so_in_one_line(rig, tmp_path):
    rows = _two_worktrees(rig, tmp_path)
    assert rr.list_resumable(rows, rig.env, boot_fn=lambda: None, live_fn=lambda s, r: "",
                             out=rig.lines.append) == 0
    assert len(rig.lines) == 1 and "boot time" in rig.lines[0] and "unknown" in rig.lines[0]


def test_list_resumable_writes_nothing(rig, tmp_path):
    rows = _two_worktrees(rig, tmp_path)
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    assert rr.list_resumable(rows, rig.env, boot_fn=lambda: 5000, live_fn=lambda s, r: "",
                             runner=rig.fake, out=rig.lines.append) == 0
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before and not rig.fake.calls


def test_the_refresh_command_rewrites_run_state_from_the_pane_pid(rig):
    rig.transcript(SID_A, 1000)
    run = rig.fleet_worker()
    rig.fake.sessions[SLUG] = [{"id": "@7", "index": 1, "dead": False, "cmd": "x"}]
    argv = ["refresh", SLUG, str(rig.wt)]
    assert rr.main(argv, runner=rig.fake, has_proc=lambda: True, out=rig.lines.append) == 0
    assert pid_of(run) == f"{PANE}\n"
    assert rr.main(["bogus"], runner=rig.fake, out=rig.lines.append) == 2


def test_no_output_line_or_source_line_names_pgrep_or_signals_a_process(tmp_path):
    lines = []
    for n, over in enumerate(({}, {"wait": 0}, {"runner": None}, {"session": "nope-1"})):
        one = Rig(tmp_path / str(n))
        one.transcript(SID_A, 1000)
        one.fleet_worker()
        one.resume(**over)
        lines += one.lines
    assert lines and not [ln for ln in lines if "pgrep" in ln]
    with open(rr.__file__, encoding="utf-8") as fh:
        source = fh.read()
    for word in ("pgrep", "pkill", "killall", "os.kill", "killpg", "signal."):
        assert word not in source
