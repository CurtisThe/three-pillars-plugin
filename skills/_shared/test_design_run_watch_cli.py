"""Hermetic tests for design_run_watch.main and the observers (no tmux, no real run).

design: design-run-launch-defaults (Behavior 5)
"""
from __future__ import annotations

import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_observe as dro  # noqa: E402
import design_run_watch as drw  # noqa: E402

LINE_RE = re.compile(r"^\d\d:\d\d:\d\d foo (commit|prompt|idle|exit|router): ")


class Out:
    def __init__(self):
        self.text, self.flushes = "", 0

    def write(self, s):
        self.text += s

    def flush(self):
        self.flushes += 1

    def lines(self):
        return self.text.splitlines()


class Script:
    """Observers fed from per-poll scripts; the last entry repeats."""

    def __init__(self, refs=(None,), live=(True,), router=([],), path=None):
        self.seq = {"refs": list(refs), "live": list(live), "router": list(router)}
        self.sleeps = 0
        self.observers = dro.Observers(
            refs=lambda: self._next("refs"), pane=lambda: "working",
            live=lambda: self._next("live"), router=lambda: self._next("router"),
            router_path=path)

    def _next(self, key):
        seq = self.seq[key]
        return seq.pop(0) if len(seq) > 1 else seq[0]

    def sleep(self, _s):
        self.sleeps += 1


def run(script, tmp_path, *args, session="abcd1234", wt=None):
    out = Out()
    argv = ["foo", *args] + (["--session", session] if session else [])
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg"), "HOME": str(tmp_path)}
    rc = drw.main(argv, observers=script.observers, out=out, env=env, worktree=wt,
                  clock=time.time, sleep=script.sleep)
    return rc, out


def test_runs_until_exit_and_flushes_every_line(tmp_path):
    refs = [{"tp/foo": ("a" * 40, "one")}, {"tp/foo": ("b" * 40, "two")}]
    script = Script(refs=refs, live=[True, True, False])
    rc, out = run(script, tmp_path)
    assert rc == 0 and script.sleeps == 2
    assert [m.group(1) for m in map(LINE_RE.match, out.lines())] == ["commit", "exit"]
    assert out.flushes >= len(out.lines())


def test_run_not_live_at_start_exits_with_a_line(tmp_path):
    rc, out = run(Script(live=[False]), tmp_path)
    assert rc == 0 and len(out.lines()) == 1 and " exit: " in out.lines()[0]


def test_router_events_follow_the_given_session(tmp_path):
    ours = "[2026-10-08 10:00:00] POST /v1/messages  model=q  sess=abcd1234  -> FALLBACK upstream (slot held by 1e71bc93)  (5B)"
    script = Script(live=[True, True, False], router=[[], [ours]])
    rc, out = run(script, tmp_path)
    assert "router: FALLBACK (slot held by 1e71bc93) [busy]" in out.text


def test_session_discovery_newest_transcript_prefix(tmp_path):
    wt = tmp_path / "wt" / "foo"
    wt.mkdir(parents=True)
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")}
    proj = dro.project_dir(str(wt), env)
    assert proj.name == re.sub("[^A-Za-z0-9]", "-", str(wt))
    proj.mkdir(parents=True)
    old, new = proj / "11111111-aaaa.jsonl", proj / "22222222-bbbb.jsonl"
    old.write_text("{}")
    new.write_text("{}")
    os.utime(old, (1, 1))
    assert dro.discover_session(str(wt), env) == "22222222"
    assert dro.discover_session(str(tmp_path / "nowhere"), env) is None
    assert dro.discover_session(None, env) is None


def test_resumed_run_switches_to_the_newest_transcript(tmp_path):
    wt = tmp_path / "wt" / "foo"
    wt.mkdir(parents=True)
    proj = dro.project_dir(str(wt), {"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")})
    proj.mkdir(parents=True)
    old = proj / "11111111-aaaa.jsonl"
    old.write_text("{}")
    os.utime(old, (1, 1))
    ours = ("[2026-10-08 10:00:00] POST /v1/messages  model=q  sess=22222222  -> FALLBACK "
            "upstream (slot held by 1e71bc93)  (5B)")
    polls = []

    def refs():
        polls.append(1)
        if len(polls) == 2:  # the run resumed: a newer transcript appears
            (proj / "22222222-bbbb.jsonl").write_text("{}")
        return None

    script = Script(live=[True, True, True, False], router=[[], [], [ours]])
    script.observers.refs = refs
    rc, out = run(script, tmp_path, session=None, wt=str(wt))
    assert rc == 0 and len([ln for ln in out.lines() if "router: session 22222222" in ln]) == 1
    assert "router: FALLBACK (slot held by 1e71bc93) [busy]" in out.text
    assert not any("session 11111111" in ln for ln in out.lines())


def test_explicit_session_is_never_rediscovered(tmp_path):
    wt = tmp_path / "wt" / "foo"
    wt.mkdir(parents=True)
    proj = dro.project_dir(str(wt), {"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")})
    proj.mkdir(parents=True)
    (proj / "33333333-cccc.jsonl").write_text("{}")
    rc, out = run(Script(live=[True, False]), tmp_path, wt=str(wt))
    assert not any("router: session" in ln for ln in out.lines())


def test_unknown_session_prints_one_notice(tmp_path):
    rc, out = run(Script(live=[False]), tmp_path, session=None, wt=str(tmp_path / "wt"))
    notices = [ln for ln in out.lines() if "router: session unknown" in ln]
    assert len(notices) == 1


def test_missing_router_log_prints_one_notice_and_keeps_watching(tmp_path):
    script = Script(live=[True, True, True, False], path=tmp_path / "absent.log")
    rc, out = run(script, tmp_path)
    assert rc == 0 and script.sleeps == 3
    assert len([ln for ln in out.lines() if "log not found" in ln]) == 1


def test_router_tail_reads_only_new_whole_lines(tmp_path):
    log = tmp_path / "router.log"
    log.write_text("old line\n")
    tail = dro.RouterTail(log)
    assert tail() == []
    with open(log, "a") as fh:
        fh.write("new one\npart")
    assert tail() == ["new one"]
    with open(log, "a") as fh:
        fh.write("ial\n")
    assert tail() == ["partial"]
    log.write_text("x\n")  # truncated: restart
    assert tail() == ["x"]
    assert dro.RouterTail(tmp_path / "missing.log")() == []


def test_git_refs_reads_tp_and_candidate_branches(tmp_path):
    import subprocess
    git = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True,
                                    capture_output=True)
    git("init", "-q", "-b", "master")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "first: msg")
    git("branch", "tp/foo")
    git("branch", "candidate/foo/a")
    git("branch", "tp/other")
    refs = dro.git_refs(str(tmp_path), "foo")
    assert set(refs) == {"tp/foo", "candidate/foo/a"}
    assert refs["tp/foo"][1] == "first: msg" and len(refs["tp/foo"][0]) == 40
    assert dro.git_refs(str(tmp_path / "nope"), "foo") is None


def test_watcher_modules_contain_no_kill_call():
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("design_run_watch.py", "design_run_observe.py"):
        text = open(os.path.join(here, name), encoding="utf-8").read()
        assert "kill" not in text and "os.signal" not in text
