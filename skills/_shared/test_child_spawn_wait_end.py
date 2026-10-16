"""Tests for child_spawn.py — `wait` ending a child whose turn is over or whose deadline passed.

strata-session-isolation task 4.5 (design §B1, detailed-design §CLI `wait`): every poll of `wait`
computes both answers — is the host process alive, has the inner turn ended. A host still alive past
`HOST_EXIT_S` (env `TP_CHILD_HOST_EXIT_S`) after its inner turn ended is stopped through its recorded
process group and then read as `done`: the reply is written, the slot released, the state says `done`,
exit 0. A host that is gone with its inner turn still open once `deadline_at` is past is
`{"state": "failed", "why": "deadline"}` at exit 3, with the slot released and the state `failed` —
the case where the child died mid-turn and nothing more will ever be written to it.

Nothing here starts a live `claude`, router or GPU job: the claude is Task 4.1's fake reached through
`TP_CHILD_SPAWN_CLAUDE`, `CLAUDE_CONFIG_DIR` is a tmp dir, and `child_slot.note_policy` /
`child_slot.release` / `stopped_agents.append` are monkeypatched so no router state is touched.
`--cwd` is a real tmp git repo's linked worktree, so the state lands under that repo's
`.git/tp-children/`. The deadline test only passes because the launch argv wraps the fake in GNU
`timeout`, which is what ends the child at `TP_CHILD_MAX_S` — hence its skipif. In both tests the
fixture reaps the process group it launched in teardown, on a failing assert too. Signal only the
group the test started.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_proc  # noqa: E402
import child_slot  # noqa: E402
import child_spawn  # noqa: E402
import child_state  # noqa: E402
import stopped_agents  # noqa: E402
from attempt_fixture import commit, git  # noqa: E402
from child_spawn_fixture import FAKE_REPLY_DEFAULT, write_fake_claude  # noqa: E402

AGENT_REF = "three-pillars:tp-runbook"
MODEL = "haiku"
SITE = "S1"
RUN = "wend0123"
PROMPT = "Report the output of `git status --porcelain`.\n"
REAP_TIMEOUT_S = 15
POLL_STEP_S = 0.2
POLL_BOUND_S = 15


class _Spawn:
    """One `start` against the fake claude, reaped no matter how the test ends."""

    def __init__(self, monkeypatch, tmp_path: Path, mode: str, sleep_s: str, max_s: str):
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
        monkeypatch.setenv("TP_CHILD_SPAWN_CLAUDE", str(write_fake_claude(tmp_path / "bin")))
        monkeypatch.setenv("TP_CHILD_MAX_S", max_s)
        monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
        monkeypatch.setenv("FAKE_SLEEP_S", sleep_s)
        monkeypatch.setenv("TP_CHILD_RESOLVE_S", "20")

        def release(inner_id, child, **kw) -> dict:
            self.releases.append((inner_id, child))
            return {"agent": "skipped", "session": "skipped"}

        real_launch = child_proc.launch

        def launch(argv, cwd, out_path, env):
            rec = real_launch(argv, cwd, out_path, env)
            self.launches.append(rec)
            return rec

        monkeypatch.setattr(child_slot, "note_policy", lambda *a, **k: True)
        monkeypatch.setattr(child_slot, "release", release)
        monkeypatch.setattr(stopped_agents, "append", lambda *a, **k: "skipped")
        monkeypatch.setattr(child_proc, "launch", launch)

    def prompt_file(self) -> Path:
        path = self.tmp / "prompt.md"
        path.write_text(PROMPT, encoding="utf-8")
        return path

    def recorded(self) -> dict:
        """The one launch this test made, as `child_proc.launch` reported it."""
        assert self.launches and "pid" in self.launches[0], self.launches
        return self.launches[0]

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


def _run(argv: list[str], capsys) -> tuple[int, dict]:
    """One `child_spawn.main` call; `(exit code, the one JSON line it printed)`."""
    code = child_spawn.main(argv)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 1, lines
    return code, json.loads(lines[0])


def _start(sp: _Spawn, capsys) -> dict:
    """Spawn one child through the CLI; the reply, with the fixture reaping it in teardown."""
    code, res = _run(["start", "--site", SITE, "--agent-ref", AGENT_REF, "--model", MODEL,
                      "--prompt-file", str(sp.prompt_file()), "--cwd", str(sp.wt),
                      "--run", RUN], capsys)
    assert code == 0, res
    return res


def test_lingering_host_stopped_then_done(monkeypatch, tmp_path, capsys) -> None:
    """Inner turn ended, host still sleeping: stopped at HOST_EXIT_S, then `done` at exit 0."""
    sp = _Spawn(monkeypatch, tmp_path, "linger", "30", "600")
    monkeypatch.setenv("TP_CHILD_HOST_EXIT_S", "2")
    try:
        started = _start(sp, capsys)
        assert started["state"] == "running", started
        state_path = started["state_path"]
        info = sp.recorded()
        reply = tmp_path / "out" / "reply.txt"

        began = time.monotonic()
        code, res = _run(["wait", "--state", state_path, "--budget-s", "20",
                          "--reply-out", str(reply)], capsys)
        elapsed = time.monotonic() - began
        assert code == 0, res
        assert res == {"state": "done", "reply_path": str(reply)}
        assert reply.read_text(encoding="utf-8") == FAKE_REPLY_DEFAULT
        assert sp.releases == [(started["inner_agent_id"], started["child_session"])]
        assert child_state.read(state_path)["state"] == "done"
        assert not child_proc.alive(int(info["pid"]), int(info["start_ticks"] or -1)), \
            "the lingering host was left running"
        assert elapsed < 15, f"wait waited out the fake's 30s sleep ({elapsed:.1f}s)"
    finally:
        sp.cleanup()


@pytest.mark.skipif(shutil.which("timeout") is None, reason="GNU timeout")
def test_deadline_kill_is_failed(monkeypatch, tmp_path, capsys) -> None:
    """`timeout` ends the host mid-turn past deadline_at: exit 3, `failed (deadline)`, released."""
    sp = _Spawn(monkeypatch, tmp_path, "sleep", "30", "2")
    try:
        started = _start(sp, capsys)
        assert started["state"] == "running", started
        state_path = started["state_path"]
        info = sp.recorded()
        pid, ticks = int(info["pid"]), int(info["start_ticks"] or -1)

        gone_at = time.monotonic() + POLL_BOUND_S
        while child_proc.alive(pid, ticks) and time.monotonic() < gone_at:
            time.sleep(POLL_STEP_S)
        assert not child_proc.alive(pid, ticks), "timeout did not end the child"

        code, res = _run(["wait", "--state", state_path, "--budget-s", "10"], capsys)
        assert code == 3, res
        assert res == {"state": "failed", "why": "deadline"}
        assert child_state.read(state_path)["state"] == "failed"
        assert sp.releases == [(started["inner_agent_id"], started["child_session"])]
    finally:
        sp.cleanup()
