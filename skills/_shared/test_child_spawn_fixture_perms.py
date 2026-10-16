"""Permission-flag tests for child_spawn_fixture.py — the fake `claude`'s CLI surface.

design: strata-classifier-cost-followups task 1.2 (design §Constraints, "The fake `claude` used
by tests must accept the new flags, and must reject an unknown `--permission-mode` value the way
the real CLI does"). Task 1.3 launches the fake with `--permission-mode dontAsk --allowedTools …
--disallowedTools …`, so the fake parses those flags the way CLI 2.1.296 does: variadic values up
to the next `--flag`, an unknown mode rejected with the CLI-shaped error before anything is
written, `--help` listing the modes it accepts, and `FAKE_ARGV_OUT` recording what reached the
CLI so a spawn test can assert the argv. Every other flag stays ignored, so
`test_child_spawn_fixture.py` keeps passing unchanged.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_transcript  # noqa: E402
from child_spawn_fixture import FAKE_PROJECT, write_fake_claude  # noqa: E402

SESSION = "s1"
RUN_TIMEOUT_S = 20
# The design's example argv (plan task 1.2 §Red) — the exact flags task 1.3 emits.
PERM_ARGV = ["-p", "x", "--session-id", SESSION, "--permission-mode", "dontAsk",
             "--allowedTools", "Read", "Bash(*)", "--disallowedTools", "Bash(kill*)",
             "--permission-prompts", "none", "--output-format", "json"]
# An older CLI's `--permission-mode` choices: no `dontAsk` (design §Behaviors, A4 fallback).
OLD_CLI_MODES = "acceptEdits,auto,bypassPermissions,default,plan"


def _env(tmp_path: Path, config_dir: bool = True, **extra) -> dict:
    """This run's env minus `CLAUDE_CODE_SESSION_ID`, plus the fixture's knobs."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ID"}
    if config_dir:
        env["CLAUDE_CONFIG_DIR"] = str(_cfg(tmp_path))
    env.update({k: str(v) for k, v in extra.items()})
    return env


def _cfg(tmp_path: Path) -> Path:
    return tmp_path / "cfg"


def _run(tmp_path: Path, script: Path, argv: list[str], config_dir: bool = True,
         **extra) -> subprocess.CompletedProcess:
    return subprocess.run([str(script), *argv], env=_env(tmp_path, config_dir, **extra),
                          capture_output=True, text=True, timeout=RUN_TIMEOUT_S)


def _host_path(tmp_path: Path, session: str = SESSION) -> Path:
    return _cfg(tmp_path) / "projects" / FAKE_PROJECT / (session + ".jsonl")


def _with_mode(argv: list[str], mode: str) -> list[str]:
    """`argv` with its `--permission-mode` value replaced by `mode`."""
    out = list(argv)
    out[out.index("--permission-mode") + 1] = mode
    return out


def test_permission_flags_accepted_and_argv_recorded(tmp_path: Path) -> None:
    """The design's example: exit 0, host transcript written, `FAKE_ARGV_OUT` as specified."""
    script = write_fake_claude(tmp_path)
    argv_out = tmp_path / "argv.json"
    proc = _run(tmp_path, script, PERM_ARGV, FAKE_ARGV_OUT=argv_out)
    assert proc.returncode == 0, proc.stderr
    assert _host_path(tmp_path).is_file()
    assert json.loads(proc.stdout)["session_id"] == SESSION
    got = json.loads(argv_out.read_text(encoding="utf-8"))
    assert got["permission_mode"] == "dontAsk"
    assert got["allowed"] == ["Read", "Bash(*)"]
    assert got["disallowed"] == ["Bash(kill*)"]
    assert got["argv"] == PERM_ARGV


def test_unknown_permission_mode_exits_1_and_writes_nothing(tmp_path: Path) -> None:
    """The real CLI rejects the value before running: exit 1, its error, no transcript."""
    script = write_fake_claude(tmp_path)
    control = _run(tmp_path, script, _with_session(PERM_ARGV, "s0"),
                   FAKE_ARGV_OUT=tmp_path / "argv-s0.json")
    assert control.returncode == 0, control.stderr
    assert _host_path(tmp_path, "s0").is_file(), "the control run wrote nothing"
    argv_out = tmp_path / "argv.json"
    proc = _run(tmp_path, script, _with_mode(PERM_ARGV, "bogus"), FAKE_ARGV_OUT=argv_out)
    assert proc.returncode == 1, proc.stderr
    assert "argument 'bogus' is invalid. Allowed choices are" in proc.stderr
    assert not _host_path(tmp_path).exists()
    assert not (_cfg(tmp_path) / "projects" / FAKE_PROJECT / SESSION).exists()
    assert not argv_out.exists()


def _with_session(argv: list[str], session: str) -> list[str]:
    """`argv` with its `--session-id` value replaced by `session`."""
    out = list(argv)
    out[out.index("--session-id") + 1] = session
    return out


def test_help_lists_the_modes_it_accepts(tmp_path: Path) -> None:
    """`--help` needs no config dir (like `--version`) and names `dontAsk` in its choices."""
    script = write_fake_claude(tmp_path)
    proc = _run(tmp_path, script, ["--help"], config_dir=False)
    assert proc.returncode == 0, proc.stderr
    assert "--permission-mode" in proc.stdout
    assert "dontAsk" in proc.stdout


def test_fake_permission_modes_narrows_the_choices(tmp_path: Path) -> None:
    """An older CLI: `--help` has no `dontAsk`, so `dontAsk` is rejected like any bad value."""
    script = write_fake_claude(tmp_path)
    help_proc = _run(tmp_path, script, ["--help"], FAKE_PERMISSION_MODES=OLD_CLI_MODES)
    assert help_proc.returncode == 0, help_proc.stderr
    assert "acceptEdits" in help_proc.stdout
    assert "dontAsk" not in help_proc.stdout
    rejected = _run(tmp_path, script, PERM_ARGV, FAKE_PERMISSION_MODES=OLD_CLI_MODES)
    assert rejected.returncode == 1, rejected.stderr
    assert "argument 'dontAsk' is invalid. Allowed choices are" in rejected.stderr
    assert not _host_path(tmp_path).exists()
    argv_out = tmp_path / "argv-auto.json"
    accepted = _run(tmp_path, script, _with_mode(PERM_ARGV, "auto"),
                    FAKE_PERMISSION_MODES=OLD_CLI_MODES, FAKE_ARGV_OUT=argv_out)
    assert accepted.returncode == 0, accepted.stderr
    assert _host_path(tmp_path).is_file()
    assert json.loads(argv_out.read_text(encoding="utf-8"))["permission_mode"] == "auto"


def test_auto_mode_is_accepted_by_default(tmp_path: Path) -> None:
    """The mode every existing child-spawn test launches with still parses, unchanged."""
    script = write_fake_claude(tmp_path)
    argv_out = tmp_path / "argv.json"
    proc = _run(tmp_path, script, ["-p", "x", "--session-id", SESSION, "--permission-mode",
                                  "auto", "--permission-prompts", "none", "--output-format",
                                  "json"], FAKE_ARGV_OUT=argv_out)
    assert proc.returncode == 0, proc.stderr
    got = json.loads(argv_out.read_text(encoding="utf-8"))
    assert got["permission_mode"] == "auto"
    assert got["allowed"] == [] and got["disallowed"] == []
    assert child_transcript.host_path(SESSION, _cfg(tmp_path)) is not None
