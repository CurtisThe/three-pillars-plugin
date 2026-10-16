"""Tests for child_spawn.py — the launch argv, the child env and the CLI skeleton.

strata-session-isolation task 1.5: design §B1 pins the exact launch form
`timeout -k 30 <CHILD_MAX_S> claude -p <host instruction> --agent <tp-spawn-host ref>
--session-id <uuid> <permission flags> --permission-prompts none --output-format json`,
so `test_host_argv_exact` compares the whole list item by item (only the instruction element
is matched by substring, because its wording is the host's one job, not a flag). Task 1.3 of
strata-classifier-cost-followups replaces `--permission-mode auto` with the `child_permissions`
flags — `dontAsk` plus the shipped allow/deny lists, the `Edit(//…)` rule scoped to the child's
`cwd` (§A1, task 2.5: an `Edit` path rule covers every file-editing tool; a `Write(<path>)` allow
rule is never honoured) — so the pinned list carries them and the per-repo additions live in
`test_child_spawn_argv_perms.py`. The child env drops `CLAUDE_CODE_SESSION_ID` so the child never
inherits the dispatcher's session, and a bad subcommand is a usage error: exit 2 with no non-JSON
on stdout. Nothing here runs a real `claude` or any subprocess — argv lists and dicts only, plus
`main` in-process.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import attempt_watchdog  # noqa: E402
import child_permissions as cp  # noqa: E402
import child_spawn  # noqa: E402
import child_spawn_ops  # noqa: E402
import model_policy  # noqa: E402

AGENT_REF = "three-pillars:tp-runbook"
HOST_REF = "three-pillars:tp-spawn-host"
MODEL = "haiku"
PROMPT_PATH = "/w/.claude/worktrees/child-spawn/ab12cd34.prompt.md"
PROMPT_LINE = f"Read {PROMPT_PATH} with the Read tool first, then follow it exactly."


def test_host_argv_exact() -> None:
    argv = child_spawn.host_argv(AGENT_REF, MODEL, PROMPT_PATH, "uuid-1", env={}, cwd="/w")
    instruction = argv[6]
    # design §A1 pins this allow list for a child whose cwd is /w; the deny values are the
    # shipped list, asserted as the module's own list rather than a second copy.
    allow = ["Agent", "Read", "Grep", "Glob", "Bash(*)", "Edit(//w/**)"]

    assert argv == [
        "timeout", "-k", "30", "1800", "claude", "-p", instruction,
        "--agent", HOST_REF,
        "--model", "sonnet",
        "--session-id", "uuid-1",
        "--permission-mode", "dontAsk",
        "--allowedTools", *allow,
        "--disallowedTools", *cp.DEFAULT_DENY,
        "--permission-prompts", "none",
        "--output-format", "json",
    ]
    assert f"subagent_type={AGENT_REF}" in instruction
    assert f"model={MODEL}" in instruction
    assert PROMPT_LINE in instruction


def test_host_argv_pins_model_sonnet(tmp_path) -> None:
    """The host is pinned to sonnet whatever the profile settings.json model is."""
    (tmp_path / "settings.json").write_text(json.dumps({"model": "opus"}), encoding="utf-8")
    for env in ({}, {"CLAUDE_CONFIG_DIR": str(tmp_path)}):
        argv = child_spawn.host_argv(AGENT_REF, MODEL, PROMPT_PATH, "u", env=env, cwd="/w")
        i = argv.index("--model")
        assert argv[i + 1] == "sonnet", "spawn host pinned to the policy sonnet, not the profile model"


def test_host_model_matches_spawn_host_agent() -> None:
    frontmatter = (HERE.parent.parent / "agents" / "tp-spawn-host.md").read_text(encoding="utf-8")
    assert child_spawn_ops.HOST_MODEL == model_policy.AGENTS["tp-spawn-host"][1]
    assert f"\nmodel: {child_spawn_ops.HOST_MODEL}\n" in frontmatter


def test_host_instruction_names_description() -> None:
    """The Agent tool requires `description`; without it the host's first call fails
    validation, it retries, and verify_host sees 2 calls (smoke: host mismatch, 2026-10-10)."""
    instruction = child_spawn.host_instruction(AGENT_REF, MODEL, PROMPT_PATH)
    assert 'description="' in instruction


def test_child_max_s_env() -> None:
    assert child_spawn.host_argv(AGENT_REF, MODEL, PROMPT_PATH, "u",
                                 env={"TP_CHILD_MAX_S": "90"})[3] == "90"
    assert child_spawn.host_argv(AGENT_REF, MODEL, PROMPT_PATH, "u",
                                 env={"TP_CHILD_MAX_S": "soon"})[3] == "1800"
    assert child_spawn.host_argv(AGENT_REF, MODEL, PROMPT_PATH, "u",
                                 env={"TP_CHILD_MAX_S": "-5"})[3] == "1800"


def test_claude_override() -> None:
    assert child_spawn.host_argv(AGENT_REF, MODEL, PROMPT_PATH, "u",
                                 env={"TP_CHILD_SPAWN_CLAUDE": "/x/fake"})[4] == "/x/fake"
    assert child_spawn.host_argv(AGENT_REF, MODEL, PROMPT_PATH, "u", env={})[4] == "claude"


def test_child_env_drops_session_id() -> None:
    env = {"CLAUDE_CODE_SESSION_ID": "s", "PATH": "p"}

    assert child_spawn.child_env(env) == {"PATH": "p", "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "0"}
    assert env == {"CLAUDE_CODE_SESSION_ID": "s", "PATH": "p"}


def test_usage_error_exit_2(capsys) -> None:
    assert child_spawn.main(["bogus"]) == 2
    out = capsys.readouterr().out
    assert out == "" or all(_is_json(line) for line in out.splitlines() if line.strip())


def test_child_max_exceeds_watchdog_wall() -> None:
    assert child_spawn.CHILD_MAX_S_DEFAULT > attempt_watchdog.DEFAULT_WALL_S


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def test_child_env_disables_bg_wait_ceiling() -> None:
    """`claude -p` stops its background tasks 600 s after its last turn, and the inner task
    worker runs as one, so a child task past ~600 s died (review-convergence 8.3, 2026-10-10).
    The child's lifetime is bounded by host_argv's `timeout -k`, not by that ceiling."""
    env = child_spawn.child_env({"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "600000", "X": "1"})
    assert env["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] == "0"
    assert env["X"] == "1"
    assert child_spawn.child_env({})["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] == "0"
