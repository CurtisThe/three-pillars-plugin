"""Tests for child_spawn.py — the `start` subcommand's failure cleanup.

strata-session-isolation task 4.3 (design §B1, §B6): every failure after a `start` launches — a host
whose `Agent` call disagrees (`mismatch`), a host that never produces an inner transcript within
`TP_CHILD_RESOLVE_S` (`no-inner`), a launch that errors outright (`TP_CHILD_SPAWN_CLAUDE` pointing
nowhere) — ends the same way: the recorded process group is stopped, `child_slot.release` ends the
child's claim on the slot, the state file says `failed` with a `why`, and `main` exits 3 on one JSON
line. Never a traceback, never a leaked process, never a held slot.

Nothing here starts a live `claude`, router or GPU job: the claude is Task 4.1's fake reached through
`TP_CHILD_SPAWN_CLAUDE`, `CLAUDE_CONFIG_DIR` is a tmp dir, and `child_slot.note_policy` /
`child_slot.release` / `stopped_agents.append` are monkeypatched so no router state is touched.
`--cwd` is a real tmp git repo's linked worktree, so the state lands under that repo's
`.git/tp-children/`. Every launch the fake survives is reaped in teardown — signal only the group the
test started, on a failing assert too.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

import pytest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_proc  # noqa: E402
import child_slot  # noqa: E402
import child_spawn  # noqa: E402
import child_state  # noqa: E402
import stopped_agents  # noqa: E402
from attempt_fixture import commit, git  # noqa: E402
from child_spawn_fixture import write_fake_claude  # noqa: E402

AGENT_REF = "three-pillars:tp-runbook"
MODEL = "haiku"
SITE = "S1"
RUN = "fail0123"
MAX_S = 600
PROMPT = "Report the output of `git status --porcelain`.\n"
REAP_TIMEOUT_S = 15


class _Spawn:
    """One `start` against the fake claude, reaped no matter how the test ends."""

    def __init__(self, monkeypatch, tmp_path: Path, mode: str, resolve_s: str,
                 claude: str | None = None):
        self.tmp = tmp_path
        self.repo = tmp_path / "repo"
        self.wt = tmp_path / "wt"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        commit(self.repo, {"README.md": "demo\n"}, "base")
        git(self.repo, "worktree", "add", "-q", "-b", "wt", str(self.wt))
        self.releases: list = []
        self.launches: list = []

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", RUN)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.setenv("TP_CHILD_SPAWN_CLAUDE",
                           claude or str(write_fake_claude(tmp_path / "bin")))
        monkeypatch.setenv("TP_CHILD_MAX_S", str(MAX_S))
        monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
        monkeypatch.setenv("FAKE_SLEEP_S", "30")
        monkeypatch.setenv("TP_CHILD_RESOLVE_S", resolve_s)

        def note_policy(child, override=None, **kw) -> bool:
            return True

        def release(inner_id, child, **kw) -> dict:
            self.releases.append((inner_id, child))
            return {"agent": "skipped", "session": "skipped"}

        real_launch = child_proc.launch

        def launch(argv, cwd, out_path, env):
            rec = real_launch(argv, cwd, out_path, env)
            self.launches.append(rec)
            return rec

        monkeypatch.setattr(child_slot, "note_policy", note_policy)
        monkeypatch.setattr(child_slot, "release", release)
        monkeypatch.setattr(stopped_agents, "append", lambda *a, **k: "skipped")
        monkeypatch.setattr(child_proc, "launch", launch)

    def prompt_file(self) -> Path:
        path = self.tmp / "prompt.md"
        path.write_text(PROMPT, encoding="utf-8")
        return path

    def cleanup(self) -> None:
        """Signal only the group this test launched, then wait for it to be gone."""
        for info in self.launches:
            if "pid" not in info:
                continue
            pid, ticks = int(info["pid"]), int(info["start_ticks"] or 0)
            child_proc.stop_group(pid, int(info["pgid"]), ticks, grace_s=2)
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
            deadline = time.monotonic() + REAP_TIMEOUT_S
            while time.monotonic() < deadline and child_proc.alive(pid, ticks):
                time.sleep(0.05)


def _start(monkeypatch, tmp_path, capsys, mode: str, resolve_s: str = "5",
           claude: str | None = None) -> tuple:
    """Run `start` once expecting a failure; `(exit code, reply, elapsed s, the fixture)`."""
    sp = _Spawn(monkeypatch, tmp_path, mode, resolve_s, claude)
    try:
        began = time.monotonic()
        code = child_spawn.main(["start", "--site", SITE, "--agent-ref", AGENT_REF,
                                 "--model", MODEL, "--prompt-file", str(sp.prompt_file()),
                                 "--cwd", str(sp.wt), "--run", RUN])
        elapsed = time.monotonic() - began
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert len(lines) == 1, lines
        return code, json.loads(lines[0]), elapsed, sp
    finally:
        sp.cleanup()


def _assert_failed(code: int, res: dict, sp: _Spawn) -> None:
    """The cleanup every failure path owes: exit 3, a `why`, a `failed` state, a released slot."""
    assert code == 3, res
    assert res["state"] == "failed"
    assert res["why"]
    state = child_state.read(res["state_path"])
    assert state["state"] == "failed"
    assert state["why"] == res["why"]
    assert state["child_session"] == res["child_session"]
    assert sp.releases and sp.releases[-1][1] == res["child_session"]
    if not sp.launches or "pid" not in sp.launches[0]:
        return
    info = sp.launches[0]
    ticks = int(info["start_ticks"] or 0)
    assert not child_proc.alive(int(info["pid"]), ticks)


def test_host_mismatch_fails(monkeypatch, tmp_path, capsys) -> None:
    code, res, elapsed, sp = _start(monkeypatch, tmp_path, capsys, "mismatch")
    _assert_failed(code, res, sp)
    assert "mismatch" in res["why"]


def test_no_inner_within_resolve_fails(monkeypatch, tmp_path, capsys) -> None:
    code, res, elapsed, sp = _start(monkeypatch, tmp_path, capsys, "no-inner", resolve_s="2")
    _assert_failed(code, res, sp)
    assert elapsed < 10, f"start hung {elapsed:.1f}s past its 2s resolve bound"


@pytest.mark.skipif(shutil.which("timeout") is None, reason="GNU timeout")
def test_launch_error_fails(monkeypatch, tmp_path, capsys) -> None:
    code, res, elapsed, sp = _start(monkeypatch, tmp_path, capsys, "happy", claude="/nonexistent")
    _assert_failed(code, res, sp)
    assert elapsed < 10, f"start waited {elapsed:.1f}s for a host that died at once"
