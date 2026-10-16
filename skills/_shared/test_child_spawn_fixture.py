"""Tests for child_spawn_fixture.py — the fake `claude` the child-spawn CLI tests launch.

design: strata-session-isolation task 4.1 (detailed-design §Test Strategy, "child_spawn CLI
(integration, fake claude)"). Tasks 4.2-4.7 point `TP_CHILD_SPAWN_CLAUDE` at the script
`write_fake_claude` writes, so everything those tests read must come out of this script: a host
transcript and one inner subagent transcript at exactly the paths `child_transcript` looks in
under `$CLAUDE_CONFIG_DIR/projects/-fake/`, a `--output-format json`-shaped result on stdout, and
the behaviour its `FAKE_CLAUDE_MODE` names. Nothing here starts a live `claude`, router or GPU
job; the two sleeping modes are reaped by signalling only the process group the test started.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_spawn  # noqa: E402
import child_transcript  # noqa: E402
import transcript_tail  # noqa: E402
from child_spawn_fixture import (  # noqa: E402
    FAKE_REPLY_DEFAULT, FAKE_VERSION_DEFAULT, fake_inner_id, write_fake_claude)

AGENT_REF = "three-pillars:tp-runbook"
MODEL = "haiku"
SESSION = "u1"
RUN_TIMEOUT_S = 20
POLL_DEADLINE_S = 10


def _cfg(tmp_path: Path) -> Path:
    return tmp_path / "cfg"


def _env(tmp_path: Path, mode: str = "happy", **extra) -> dict:
    """This run's env minus `CLAUDE_CODE_SESSION_ID`, plus the fixture's knobs."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ID"}
    env["CLAUDE_CONFIG_DIR"] = str(_cfg(tmp_path))
    env["FAKE_CLAUDE_MODE"] = mode
    env["FAKE_AGENT_REF"] = AGENT_REF
    env["FAKE_MODEL"] = MODEL
    env.update({k: str(v) for k, v in extra.items()})
    return env


def _argv(script: Path, instruction: str = "x", session: str = SESSION) -> list[str]:
    """The shape `child_spawn.host_argv` builds, with the script in place of `claude`."""
    return [str(script), "-p", instruction, "--agent", "three-pillars:tp-spawn-host",
            "--session-id", session, "--permission-mode", "auto",
            "--permission-prompts", "none", "--output-format", "json"]


def _run(tmp_path: Path, script: Path, mode: str, **extra) -> subprocess.CompletedProcess:
    return subprocess.run(_argv(script), env=_env(tmp_path, mode, **extra),
                          capture_output=True, text=True, timeout=RUN_TIMEOUT_S)


def _host_records(tmp_path: Path) -> list[dict]:
    host = child_transcript.host_path(SESSION, _cfg(tmp_path))
    assert host is not None, "no host transcript"
    return transcript_tail.read_records(host)


def _wait_for(predicate, timeout_s: float = POLL_DEADLINE_S) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _spawn(tmp_path: Path, script: Path, mode: str, **extra) -> subprocess.Popen:
    return subprocess.Popen(_argv(script), env=_env(tmp_path, mode, **extra),
                            start_new_session=True, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def _reap(proc: subprocess.Popen) -> None:
    """Signal only the group this test started, then reap it."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait(timeout=RUN_TIMEOUT_S)


def test_happy_mode_transcripts_found(tmp_path: Path) -> None:
    script = write_fake_claude(tmp_path)
    proc = _run(tmp_path, script, "happy", FAKE_REPLY="reply-under-test")
    assert proc.returncode == 0, proc.stderr
    cfg = _cfg(tmp_path)
    host = child_transcript.host_path(SESSION, cfg)
    assert host is not None and host.is_file()
    assert child_transcript.inner_ids(SESSION, cfg) == [fake_inner_id(SESSION)]
    ok, why = child_transcript.verify_host(_host_records(tmp_path), AGENT_REF, MODEL)
    assert ok, why
    assert child_transcript.last_text(fake_inner_id(SESSION), cfg) == "reply-under-test"
    assert json.loads(proc.stdout)["is_error"] is False


def test_defaults_when_agent_env_unset(tmp_path: Path) -> None:
    """`subagent_type`/`model` come from the instruction; the reply from `FAKE_REPLY_DEFAULT`."""
    script = write_fake_claude(tmp_path)
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ID"}
    env["CLAUDE_CONFIG_DIR"] = str(_cfg(tmp_path))
    instruction = child_spawn.host_instruction(AGENT_REF, MODEL, str(tmp_path / "p.md"))
    proc = subprocess.run(_argv(script, instruction), env=env, capture_output=True,
                          text=True, timeout=RUN_TIMEOUT_S)
    assert proc.returncode == 0, proc.stderr
    ok, why = child_transcript.verify_host(_host_records(tmp_path), AGENT_REF, MODEL)
    assert ok, why
    assert child_transcript.last_text(fake_inner_id(SESSION),
                                      _cfg(tmp_path)) == FAKE_REPLY_DEFAULT


def test_mode_mismatch_fails_verify(tmp_path: Path) -> None:
    script = write_fake_claude(tmp_path)
    proc = _run(tmp_path, script, "mismatch")
    assert proc.returncode == 0, proc.stderr
    ok, why = child_transcript.verify_host(_host_records(tmp_path), AGENT_REF, MODEL)
    assert not ok and "subagent_type" in why
    assert child_transcript.inner_ids(SESSION, _cfg(tmp_path)) == [fake_inner_id(SESSION)]


def test_mode_no_inner_writes_host_only(tmp_path: Path) -> None:
    script = write_fake_claude(tmp_path)
    assert _run(tmp_path, script, "no-inner").returncode == 0
    cfg = _cfg(tmp_path)
    assert child_transcript.host_path(SESSION, cfg) is not None
    assert child_transcript.inner_ids(SESSION, cfg) == []
    started = time.monotonic()
    assert _run(tmp_path, script, "no-inner", FAKE_SLEEP_S=1).returncode == 0
    assert time.monotonic() - started >= 1.0
    assert child_transcript.inner_ids(SESSION, cfg) == []


def test_mode_sleep_inner_not_ended_then_sleeps(tmp_path: Path) -> None:
    script = write_fake_claude(tmp_path)
    inner, cfg = fake_inner_id(SESSION), _cfg(tmp_path)
    started = time.monotonic()
    proc = _spawn(tmp_path, script, "sleep", FAKE_SLEEP_S=1)
    try:
        assert _wait_for(lambda: child_transcript.inner_ids(SESSION, cfg) == [inner])
        assert child_transcript.inner_done(inner, cfg) is False
        assert child_transcript.verify_host(_host_records(tmp_path), AGENT_REF, MODEL)[0]
        assert proc.poll() is None
        assert proc.wait(timeout=RUN_TIMEOUT_S) == 0
        assert time.monotonic() - started >= 1.0
    finally:
        _reap(proc)
    assert child_transcript.inner_done(inner, cfg) is False


def test_mode_linger_ends_inner_turn_and_keeps_sleeping(tmp_path: Path) -> None:
    script = write_fake_claude(tmp_path)
    inner, cfg = fake_inner_id(SESSION), _cfg(tmp_path)
    proc = _spawn(tmp_path, script, "linger", FAKE_SLEEP_S=30)
    try:
        assert _wait_for(lambda: child_transcript.inner_done(inner, cfg))
        assert child_transcript.last_text(inner, cfg) == FAKE_REPLY_DEFAULT
        assert proc.poll() is None
    finally:
        _reap(proc)
    assert proc.poll() is not None


def test_mode_smoke_writes_smoke_file(tmp_path: Path) -> None:
    script = write_fake_claude(tmp_path)
    smoke = tmp_path / "child-spawn" / "smoke-deadbeef.txt"
    proc = _run(tmp_path, script, "smoke", FAKE_SMOKE_FILE=smoke, FAKE_SMOKE_TOKEN="deadbeef")
    assert proc.returncode == 0, proc.stderr
    assert smoke.read_text(encoding="utf-8").splitlines() == ["deadbeef", "exit=0"]
    assert child_transcript.inner_ids(SESSION, _cfg(tmp_path)) == [fake_inner_id(SESSION)]
    assert child_transcript.inner_done(fake_inner_id(SESSION), _cfg(tmp_path)) is True


def test_mode_deny_prints_denial_json(tmp_path: Path) -> None:
    script = write_fake_claude(tmp_path)
    proc = _run(tmp_path, script, "deny")
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["is_error"] is True
    assert out["permission_denials"]
    ok, why = child_transcript.verify_host(_host_records(tmp_path), AGENT_REF, MODEL)
    assert ok, why


def test_version_prints_one_line_without_config_dir(tmp_path: Path) -> None:
    script = write_fake_claude(tmp_path)
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_CONFIG_DIR", "FAKE_CLAUDE_MODE")}
    proc = subprocess.run([str(script), "--version"], env=env, capture_output=True,
                          text=True, timeout=RUN_TIMEOUT_S)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines() == [FAKE_VERSION_DEFAULT]


def test_missing_config_dir_exits_2_and_writes_nothing(tmp_path: Path) -> None:
    script = write_fake_claude(tmp_path)
    session = "fixture-no-cfg-check"
    base = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
    for env in (base, dict(base, CLAUDE_CONFIG_DIR="")):
        proc = subprocess.run([str(script), "-p", "x", "--session-id", session], env=env,
                              capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
        assert proc.returncode == 2, proc.stderr
        assert proc.stderr.strip()
    assert child_transcript.host_path(session, Path.home() / ".claude") is None
