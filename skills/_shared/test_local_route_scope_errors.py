"""test_local_route_scope_errors.py — an invalid `check --scope` names the
allowed forms, and `append` says on stderr why it wrote nothing.

design: run-tooling-footguns (Scope trap 3, Behaviors 3)

`local_route_check.py check --scope` accepts only `run-start` or `phase <N>`.
A bad word used to print `invalid or missing --scope` with no hint of the
allowed forms, and `local_route_log.py append` fed that line exited 0 with
`"appended": false` and no word on why. These tests drive the two real CLIs
end to end (check stdout piped into append stdin) and assert on the parsed
JSON fields plus the stable tokens of the stderr line, never its full wording
(skills/_shared/test-fragility.md). The accepted scope words do not change.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
CHECK_CLI = _SHARED / "local_route_check.py"
LOG_CLI = _SHARED / "local_route_log.py"

ALLOWED_FORMS = ("run-start", "phase <N>")


def _closed_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _env() -> dict:
    """A child env that never probes the real router: a closed loopback port."""
    env = dict(os.environ)
    env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{_closed_port()}"
    return env


def _run(script: Path, *args: str, stdin: str | None = None):
    proc = subprocess.run(
        [sys.executable, "-I", str(script), *args], input=stdin,
        capture_output=True, text=True, timeout=30, env=_env())
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    return proc


def _check(decisions: Path, scope: str) -> str:
    """The raw one-line stdout of `check --decisions … --scope …`."""
    proc = _run(CHECK_CLI, "check", "--decisions", str(decisions),
                "--scope", scope)
    assert len([ln for ln in proc.stdout.splitlines() if ln.strip()]) == 1
    return proc.stdout


def _append(decisions: Path, stdin: str):
    return _run(LOG_CLI, "append", "--decisions", str(decisions), stdin=stdin)


def test_bogus_scope_error_names_the_allowed_forms(tmp_path):
    out = json.loads(_check(tmp_path / "decisions.md", "bogus"))
    error = out["transition"]["error"]
    assert "entry" not in out["transition"]
    for form in ALLOWED_FORMS:
        assert form in error, f"{form!r} missing from {error!r}"


def test_missing_scope_error_names_the_allowed_forms(tmp_path):
    proc = _run(CHECK_CLI, "check", "--decisions", str(tmp_path / "d.md"))
    error = json.loads(proc.stdout)["transition"]["error"]
    for form in ALLOWED_FORMS:
        assert form in error, f"{form!r} missing from {error!r}"


def test_append_after_bad_scope_says_on_stderr_why_nothing_was_appended(tmp_path):
    decisions = tmp_path / "decisions.md"
    proc = _append(decisions, _check(decisions, "bogus"))
    result = json.loads(proc.stdout)
    assert result["appended"] is False and result["error"]
    lines = [ln for ln in proc.stderr.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected one stderr line, got {proc.stderr!r}"
    assert "nothing appended" in lines[0].lower()
    for form in ALLOWED_FORMS:  # the why carries the allowed forms
        assert form in lines[0], f"{form!r} missing from {lines[0]!r}"
    assert not decisions.exists()  # nothing written, nothing created


def test_accepted_scope_words_still_pass_and_append_stays_quiet(tmp_path):
    for scope in ("run-start", "phase 3"):
        decisions = tmp_path / f"{scope.replace(' ', '-')}.md"
        out = json.loads(_check(decisions, scope))
        assert "error" not in out["transition"], out["transition"]
        assert out["transition"]["entry"].startswith(f"### [routing] {scope}:")
        proc = _append(decisions, json.dumps(out))
        assert json.loads(proc.stdout)["appended"] is True
        assert proc.stderr == ""
        assert scope in decisions.read_text(encoding="utf-8")


def test_near_miss_scope_words_are_still_rejected(tmp_path):
    for scope in ("phase", "phase x", "Phase 1", "run-start ", "phase 1 2", ""):
        out = json.loads(_check(tmp_path / "decisions.md", scope))
        assert "error" in out["transition"], f"{scope!r} was accepted"
