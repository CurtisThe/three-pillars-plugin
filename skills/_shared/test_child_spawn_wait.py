"""Tests for child_spawn.py — the `wait` subcommand's two answers.

strata-session-isolation task 4.4 (design §B1, detailed-design §CLI `wait`): `wait --state S
--budget-s N [--reply-out F]` polls the recorded child once a second. A host that has exited with its
inner turn ended is `done`: the inner agent's last text goes to `--reply-out`, `child_slot.release`
ends the child's claim on the slot, the state file says `done` with its `reply_path`, and `main`
exits 0 on `{"state": "done", "reply_path": F}`. A child still alive when the budget is spent exits 3
on `{"state": "running"}` and leaves the state file `running` for a later `wait` to finish.

Nothing here starts a live `claude`, router or GPU job: the claude is Task 4.1's fake reached through
`TP_CHILD_SPAWN_CLAUDE`, `CLAUDE_CONFIG_DIR` is a tmp dir, and `child_slot.note_policy` /
`child_slot.release` / `stopped_agents.append` are monkeypatched so no router state is touched.
`--cwd` is a real tmp git repo's linked worktree, so the state lands under that repo's
`.git/tp-children/`. In `sleep` mode the fake stays alive for `FAKE_SLEEP_S`, so the test stops the
child with `cmd_stop` and the fixture reaps the group it started in teardown — on a failing assert
too. Signal only the group the test launched.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

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
RUN = "wait0123"
MAX_S = 600
PROMPT = "Report the output of `git status --porcelain`.\n"
REAP_TIMEOUT_S = 15


class _Spawn:
    """One `start` against the fake claude, reaped no matter how the test ends."""

    def __init__(self, monkeypatch, tmp_path: Path, mode: str, sleep_s: str):
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
        monkeypatch.setenv("TP_CHILD_MAX_S", str(MAX_S))
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


def _start(sp: _Spawn, capsys) -> dict:
    """Spawn one child through the CLI; the reply, with the fixture reaping it in teardown."""
    code, res = _run(["start", "--site", SITE, "--agent-ref", AGENT_REF, "--model", MODEL,
                      "--prompt-file", str(sp.prompt_file()), "--cwd", str(sp.wt),
                      "--run", RUN], capsys)
    assert code == 0, res
    return res


def _run(argv: list[str], capsys) -> tuple[int, dict]:
    """One `child_spawn.main` call; `(exit code, the one JSON line it printed)`."""
    code = child_spawn.main(argv)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 1, lines
    return code, json.loads(lines[0])


def test_wait_done_writes_reply(monkeypatch, tmp_path, capsys) -> None:
    """A host that exited after its inner turn: exit 0, the reply file, one release, `done`."""
    sp = _Spawn(monkeypatch, tmp_path, "happy", "0")
    try:
        started = _start(sp, capsys)
        assert started["state"] == "running", started
        state_path = started["state_path"]
        reply = tmp_path / "out" / "reply.txt"

        began = time.monotonic()
        code, res = _run(["wait", "--state", state_path, "--budget-s", "20",
                          "--reply-out", str(reply)], capsys)
        assert code == 0, res
        assert res == {"state": "done", "reply_path": str(reply)}
        assert reply.read_text(encoding="utf-8") == FAKE_REPLY_DEFAULT
        assert sp.releases == [(started["inner_agent_id"], started["child_session"])]
        state = child_state.read(state_path)
        assert state["state"] == "done"
        assert state["reply_path"] == str(reply)
        assert time.monotonic() - began < 15, "wait did not finish as soon as the child was done"
    finally:
        sp.cleanup()


def test_wait_running_exit_4(monkeypatch, tmp_path, capsys) -> None:
    """A child still alive at the end of the budget: exit 4, `running`, state left `running`."""
    sp = _Spawn(monkeypatch, tmp_path, "sleep", "30")
    try:
        started = _start(sp, capsys)
        assert started["state"] == "running", started
        state_path = started["state_path"]

        began = time.monotonic()
        code, res = _run(["wait", "--state", state_path, "--budget-s", "2"], capsys)
        elapsed = time.monotonic() - began
        assert code == 4, res
        assert res == {"state": "running"}
        assert 2 <= elapsed < 12, f"wait spent {elapsed:.1f}s of a 2s budget"
        assert child_state.read(state_path)["state"] == "running"
        assert sp.releases == []
        assert child_spawn.cmd_stop(state_path)["result"] == "ok"
        assert child_state.read(state_path)["state"] == "stopped"
    finally:
        sp.cleanup()
