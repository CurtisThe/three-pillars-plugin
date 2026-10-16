"""Tests for child_spawn.py — the `start` subcommand's happy path.

strata-session-isolation task 4.2 (design §B1, detailed-design §CLI `start`): `start --site S
--agent-ref A --model M --prompt-file P [--cwd DIR] [--busy-policy wait|fallback] [--run R]`
copies the prompt into `<cwd>/.tp-scratch/child-spawn/<child8>.prompt.md`, notes the child's
busy policy, launches the pinned host argv (design §B1) in its own session with an env that has no
`CLAUDE_CODE_SESSION_ID`, waits for exactly one inner subagent transcript, verifies the host made
the one Agent call it was told to make, and leaves a `running` state file carrying `deadline_at`.
The reply is `{"child_session", "pid", "inner_agent_id", "state_path", "state": "running"}` at
exit 0.

Nothing here starts a live `claude`, router or GPU job: the claude is Task 4.1's fake, reached
through `TP_CHILD_SPAWN_CLAUDE`, with `CLAUDE_CONFIG_DIR` pointed at a tmp dir and
`child_slot.note_policy` / `child_slot.release` / `stopped_agents.append` monkeypatched so no
router state is touched. `--cwd` is a real tmp git repo's linked worktree, so the state lands under
that repo's `.git/tp-children/` and never the ambient one. In `linger` mode the fake stays alive
for `FAKE_SLEEP_S`, so the fixture reaps the group it started in teardown — on a failing assert too.
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
from child_spawn_fixture import fake_inner_id, write_fake_claude  # noqa: E402

AGENT_REF = "three-pillars:tp-runbook"
MODEL = "haiku"
SITE = "S1"
RUN = "start0123"
MAX_S = 600
PROMPT = "Run `git status --porcelain` and report the output.\n"
REAP_TIMEOUT_S = 15


class _Spawn:
    """One `start` against the fake claude, reaped no matter how the test ends."""

    def __init__(self, monkeypatch, tmp_path: Path):
        self.tmp = tmp_path
        self.repo = tmp_path / "repo"
        self.wt = tmp_path / "wt"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        commit(self.repo, {"README.md": "demo\n"}, "base")
        git(self.repo, "worktree", "add", "-q", "-b", "wt", str(self.wt))
        self.notes: list = []
        self.launches: list = []

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", RUN)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.setenv("TP_CHILD_SPAWN_CLAUDE", str(write_fake_claude(tmp_path / "bin")))
        monkeypatch.setenv("TP_CHILD_MAX_S", str(MAX_S))
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "linger")
        monkeypatch.setenv("FAKE_SLEEP_S", "30")
        monkeypatch.setenv("TP_CHILD_RESOLVE_S", "20")

        def note_policy(child, override=None, **kw) -> bool:
            self.notes.append((child, override))
            return True

        real_launch = child_proc.launch

        def launch(argv, cwd, out_path, env):
            rec = real_launch(argv, cwd, out_path, env)
            self.launches.append({"argv": argv, "cwd": cwd, "out_path": out_path,
                                  "env": env, "rec": rec})
            return rec

        monkeypatch.setattr(child_slot, "note_policy", note_policy)
        monkeypatch.setattr(child_slot, "release",
                            lambda *a, **k: {"agent": "skipped", "session": "skipped"})
        monkeypatch.setattr(stopped_agents, "append", lambda *a, **k: "skipped")
        monkeypatch.setattr(child_proc, "launch", launch)

    def prompt_file(self) -> Path:
        path = self.tmp / "prompt.md"
        path.write_text(PROMPT, encoding="utf-8")
        return path

    def cleanup(self) -> None:
        """Signal only the group this test launched, then wait for it to be gone."""
        for rec in self.launches:
            info = rec["rec"]
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


def _start(monkeypatch, tmp_path, capsys, extra: list[str] = (), rel_cwd: bool = False) -> tuple:
    """Run `start` once against the fake claude; `(exit code, reply, the spawn fixture)`.

    `rel_cwd` chdirs into the worktree and passes `--cwd .`, the relative form a site may use.
    """
    sp = _Spawn(monkeypatch, tmp_path)
    if rel_cwd:
        monkeypatch.chdir(sp.wt)
    try:
        argv = ["start", "--site", SITE, "--agent-ref", AGENT_REF, "--model", MODEL,
                "--prompt-file", str(sp.prompt_file()), "--cwd", "." if rel_cwd else str(sp.wt),
                "--run", RUN] + list(extra)
        code = child_spawn.main(argv)
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert len(lines) == 1, lines
        return code, json.loads(lines[0]), sp
    finally:
        sp.cleanup()


def test_start_happy(monkeypatch, tmp_path, capsys) -> None:
    code, res, sp = _start(monkeypatch, tmp_path, capsys)
    assert code == 0, res
    child = res["child_session"]
    assert res["state"] == "running"
    assert res["inner_agent_id"] == fake_inner_id(child)
    assert res["pid"] == sp.launches[0]["rec"]["pid"]

    run_dir = child_state.run_dir(RUN, root=sp.wt)
    state_path = Path(res["state_path"])
    assert state_path == run_dir / (child[:8] + ".json")

    copy = sp.wt / ".tp-scratch" / "child-spawn" / (child[:8] + ".prompt.md")
    assert copy.read_bytes() == PROMPT.encode("utf-8")

    state = child_state.read(state_path)
    assert state["state"] == "running"
    assert state["child_session"] == child
    assert state["site"] == SITE
    assert state["agent_ref"] == AGENT_REF
    assert state["model"] == MODEL
    assert state["run"] == run_dir.name
    assert state["pid"] == res["pid"]
    assert Path(state["prompt_path"]) == copy
    assert Path(state["out_path"]).read_bytes()  # the host's json result landed here
    assert state["deadline_at"] == state["started_at"] + MAX_S
    assert sp.notes == [(child, None)]


def test_start_argv_prefix(monkeypatch, tmp_path, capsys) -> None:
    code, res, sp = _start(monkeypatch, tmp_path, capsys)
    assert code == 0, res
    launched = sp.launches[0]
    assert launched["argv"][:4] == ["timeout", "-k", "30", str(MAX_S)]
    assert "CLAUDE_CODE_SESSION_ID" not in launched["env"]
    assert launched["cwd"] == str(sp.wt)
    assert launched["out_path"] == str(child_state.run_dir(RUN, root=sp.wt)
                                       / (res["child_session"][:8] + ".out"))


def test_busy_policy_override_passed(monkeypatch, tmp_path, capsys) -> None:
    code, res, sp = _start(monkeypatch, tmp_path, capsys, ["--busy-policy", "wait"])
    assert code == 0, res
    assert sp.notes == [(res["child_session"], "wait")]


def test_relative_cwd_gives_absolute_prompt_path(monkeypatch, tmp_path, capsys) -> None:
    """`--cwd .` still hands the host an absolute prompt path — the host's own cwd may differ."""
    code, res, sp = _start(monkeypatch, tmp_path, capsys, rel_cwd=True)
    assert code == 0, res
    argv = sp.launches[0]["argv"]
    instruction = argv[argv.index("-p") + 1]
    prompt_path = instruction.split("Read ", 1)[1].split(" with the Read tool", 1)[0]
    assert os.path.isabs(prompt_path), prompt_path
    assert Path(prompt_path) == sp.wt.resolve() / ".tp-scratch" / "child-spawn" / (
        res["child_session"][:8] + ".prompt.md")
