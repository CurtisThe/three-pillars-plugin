"""Tests for the `permission-refused` failure class on the ladder — Task 1.6.

design: strata-classifier-cost-followups (design §A3; plan Task 1.6)

A FAIL whose reply carries Task 1.5's `permission-refused: <rule>` banner is the deterministic class
`permission-refused`: the verdict records the refused rule text, the `[tier]` decision entry names
it, and the task is **not** retried on the same rung with the same prompt — it jumps to
`sonnet-medium` or above, an in-process rung the child's permission lists do not bind (a refused
call would be refused again by the same lists in another local child).

Two halves, in the order a live run takes them (`local-dispatch.md` §3 step 4 → §2 step 6): the
fake claude in `FAKE_CLAUDE_MODE=refuse` goes through `cmd_start` → `cmd_wait(reply_out=F)` →
`build_evidence(reply=F)` → `next_step`, so the banner travels the reply file the ladder already
reads; and the pure ladder step, with the flag in the evidence, decides the jump.

Nothing here starts a live `claude`, router or GPU job: the claude is Task 4.1's fake reached
through `TP_CHILD_SPAWN_CLAUDE`, `CLAUDE_CONFIG_DIR` is a tmp dir, and the slot/stop calls are
monkeypatched so no router state is touched. `--cwd` is a real tmp git repo's linked worktree. The
fixture reaps the process group it launched in teardown, on a failing assert too. Signal only the
group the test started. Stdlib only.
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
import local_implement_config  # noqa: E402
import stopped_agents  # noqa: E402
import tier_ladder  # noqa: E402
from attempt_fixture import commit, git  # noqa: E402
from child_spawn_fixture import write_fake_claude  # noqa: E402
from ladder_entry import build_evidence, to_decision_entry, to_telemetry  # noqa: E402

AGENT_REF = "three-pillars:tp-task-worker-local-medium"
MODEL = "haiku"
SITE = "S1"
RUN = "prl01234"
MAX_S = 600
PROMPT = "Report the output of `git status --porcelain`.\n"
REAP_TIMEOUT_S = 15
RULE = "Bash(rm -rf build)"
BANNER = "permission-refused: "
FLAG = BANNER + RULE
CFG = {**local_implement_config.DEFAULTS, "max_retries": 2}


class _Spawn:
    """One `start` against the fake claude in `refuse` mode, reaped no matter how the test ends."""

    def __init__(self, monkeypatch, tmp_path: Path):
        self.tmp = tmp_path
        self.repo = tmp_path / "repo"
        self.wt = tmp_path / "wt"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        commit(self.repo, {"README.md": "demo\n"}, "base")
        git(self.repo, "worktree", "add", "-q", "-b", "wt", str(self.wt))
        self.launches: list = []

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", RUN)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.setenv("TP_CHILD_SPAWN_CLAUDE", str(write_fake_claude(tmp_path / "bin")))
        monkeypatch.setenv("TP_CHILD_MAX_S", str(MAX_S))
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "refuse")
        monkeypatch.setenv("FAKE_SLEEP_S", "0")
        monkeypatch.setenv("TP_CHILD_RESOLVE_S", "20")

        real_launch = child_proc.launch

        def launch(argv, cwd, out_path, env):
            rec = real_launch(argv, cwd, out_path, env)
            self.launches.append(rec)
            return rec

        monkeypatch.setattr(child_slot, "note_policy", lambda *a, **k: True)
        monkeypatch.setattr(child_slot, "release", lambda *a, **k: {"agent": "skipped"})
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


def test_a_refused_call_walks_the_ladder_to_sonnet_medium(monkeypatch, tmp_path, capsys) -> None:
    """`refuse` → reply file `F` → `build_evidence(F)` → `next_step`: escalate, never retry."""
    sp = _Spawn(monkeypatch, tmp_path)
    try:
        code = child_spawn.main(["start", "--site", SITE, "--agent-ref", AGENT_REF, "--model",
                                 MODEL, "--prompt-file", str(sp.prompt_file()),
                                 "--cwd", str(sp.wt), "--run", RUN])
        started_out = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert code == 0 and len(started_out) == 1, started_out
        started = json.loads(started_out[0])
        reply = tmp_path / "out" / "reply.txt"
        assert child_spawn.cmd_wait(started["state_path"], budget_s=20,
                                    reply_out=str(reply))["state"] == "done"
        ev = build_evidence("1.6", reply=str(reply))
        assert ev["flags"] == [FLAG], ev
        action, rung, rec = tier_ladder.next_step(tier_ladder.start("1.6", "local-medium"),
                                                  "FAIL", CFG, reason="tests failed", evidence=ev)
        assert (action, rung) == ("escalate", "sonnet-medium")
        assert FLAG in rec["verdicts"][0]["flags"]
    finally:
        sp.cleanup()


def _step(evidence: dict) -> tuple:
    return tier_ladder.next_step(tier_ladder.start("1.6", "local-medium"), "FAIL", CFG,
                                 reason="tests failed", evidence=evidence)


def test_refused_flag_jumps_rungs_instead_of_retrying_the_same_one() -> None:
    """`next_step` on `local-medium` + the flag: `sonnet-medium`, stuck deterministic, no retry."""
    action, rung, rec = _step({"flags": [FLAG]})
    assert (action, rung) == ("escalate", "sonnet-medium")
    v = rec["verdicts"][0]
    assert v["class"] == "deterministic:permission-refused"
    assert v["stuck"] == "deterministic"
    assert FLAG in v["flags"]  # `_verdict` already copies ev["flags"]
    # never a `retry` of the same rung with the same prompt: the record moves up
    assert rec["tier_path"] == ["local-medium", "sonnet-medium"]


def test_decision_entry_names_the_refused_rule() -> None:
    """The `[tier]` entry carries `flag: permission-refused: <rule>` (it already renders flags)."""
    _action, _rung, rec = _step({"flags": [FLAG]})
    entry = to_decision_entry(to_telemetry(rec))
    assert "flag: permission-refused: Bash(rm -rf build)" in entry
    assert "stuck: deterministic permission-refused" in entry
