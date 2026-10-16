"""Tests for the `hook-refused` failure class on the ladder (design red-commit-hook-refusal, 1.4).

A worker whose FIRST commit (the Red) was refused by a test-running pre-commit hook cannot be helped
by another attempt on another model: the hook refuses the same commit the same way. So the class is
its own bare string `hook-refused` (never `deterministic:`-prefixed), and `next_step` ends the task:
`stuck == "hook-refused"`, a verdict reason `hook-refused: <tail>`, action `halt`, final `env-error`
(the dispatcher and orchestrator already halt and escalate to the finalizer on that final).

The class applies only when the evidence says the refused commit was the attempt's first
(`first_commit`), no earlier class matched (`size-split`, `missing-fixture`, `out-of-scope-pin`
still win) and the hook tail names a failing test file (a lint or secret-scan refusal keeps the old
class). The watchdog's fast catch arrives as the reason `runaway: hook-refused: <tail>`, checked
BEFORE the generic `runaway: ` return. Pure data in, pure data out; the CLI test runs the real
`tier_ladder.py next` over a record file and a reply file. Stdlib only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import failure_class  # noqa: E402
import local_implement_config  # noqa: E402
import tier_ladder  # noqa: E402
from ladder_entry import build_evidence, to_decision_entry  # noqa: E402

SCRIPT = str(HERE / "tier_ladder.py")
CFG = {**local_implement_config.DEFAULTS, "max_retries": 2}
ROUTED = {"schema": "tp-local-route/v1", "state": "routed", "reason": "ok",
          "base_url": "http://127.0.0.1:3457", "checked_at": "2026-09-27T00:00:00Z"}

TAIL = "pre-commit: running tests\nFAILED tests/test_x.py::test_a - AssertionError\n1 failed"
LINT_TAIL = "ruff: skills/_shared/foo.py:3:1: E501 line too long (121 > 120)"
SIZE_TAIL = "file-size-guard: skills/_shared/foo.py has 612 lines (cap 500)\nFAILED tests/test_x.py"
SIZE_REASON = "runaway: hook-refused: " + SIZE_TAIL.replace("\n", " ")
REFUSED = "hook-refused"


def _classify(hook_tail: str = TAIL, **kw) -> str:
    return failure_class.classify("hook-failed", "", hook_tail=hook_tail, **kw)


# --- classify ------------------------------------------------------------------------------

def test_first_commit_hook_failure_with_failing_test_file_is_hook_refused() -> None:
    assert _classify(first_commit=True) == REFUSED
    assert not REFUSED.startswith("deterministic:")


def test_a_later_commit_keeps_the_old_class() -> None:
    assert _classify(first_commit=False) == "quality"
    assert _classify() == "quality"  # the keyword defaults to False: old callers are unchanged


def test_a_lint_refusal_without_a_failing_test_file_keeps_the_old_class() -> None:
    assert _classify(LINT_TAIL, first_commit=True) == "quality"


def test_a_size_guard_tail_still_wins() -> None:
    assert _classify(SIZE_TAIL, first_commit=True) == "deterministic:size-split"


def test_a_missing_fixture_tail_still_wins() -> None:
    tail = "FAILED tests/test_x.py::test_a - fixture 'conn' not found"
    assert _classify(tail, first_commit=True) == "deterministic:missing-fixture"


def test_out_of_scope_pin_still_wins() -> None:
    """A failing id the task's Targets do not name is the old class, not hook-refused."""
    row = {"files": ["skills/_shared/foo.py"],
           "test": {"specs": ["skills/_shared/test_foo.py"]}}
    tail = "FAILED tests/test_other.py::test_a - AssertionError"
    assert _classify(tail, row=row, first_commit=True) == "deterministic:out-of-scope-pin"
    # the same failure inside the task's own test file is a hook refusal
    own = "FAILED skills/_shared/test_foo.py::test_a - AssertionError"
    assert _classify(own, row=row, first_commit=True) == REFUSED


def test_a_permission_refusal_still_wins() -> None:
    flags = ["permission-refused: Bash(rm -rf build)"]
    assert _classify(first_commit=True, flags=flags) == "deterministic:permission-refused"


def test_the_runaway_hook_refused_reason_is_hook_refused() -> None:
    reason = "runaway: hook-refused: FAILED tests/test_x.py::test_a - AssertionError"
    assert failure_class.classify("FAIL", reason) == REFUSED


def test_a_size_guard_tail_inside_the_runaway_reason_still_wins() -> None:
    assert failure_class.classify("FAIL", SIZE_REASON) == "deterministic:size-split"


def test_the_generic_runaway_reason_is_unchanged() -> None:
    assert failure_class.classify("FAIL", "runaway: wall-clock 900s") == "runaway"


# --- build_evidence ------------------------------------------------------------------------

def _reply(tmp_path: Path, last: dict, body: str = TAIL) -> str:
    path = tmp_path / "reply.txt"
    path.write_text(f"{body}\n{json.dumps(last)}\n", encoding="utf-8")
    return str(path)


def test_build_evidence_marks_a_hook_failed_reply_with_no_red_as_first_commit(tmp_path) -> None:
    for last in ({"claimed": "hook-failed", "red_sha": None},
                 {"claimed": "hook-failed", "red_sha": ""},
                 {"claimed": "hook-failed"}):
        ev = build_evidence("1.4", reply=_reply(tmp_path, last))
        assert ev["first_commit"] is True, last
        assert "FAILED tests/test_x.py::test_a" in ev["hook_tail"]


def test_build_evidence_keeps_a_reply_with_a_red_sha_unmarked(tmp_path) -> None:
    ev = build_evidence("1.4", reply=_reply(tmp_path, {"claimed": "hook-failed", "red_sha": "ab12cd3"}))
    assert not ev.get("first_commit")
    assert "hook_tail" in ev


def test_build_evidence_ignores_a_reply_that_is_not_hook_failed(tmp_path) -> None:
    ev = build_evidence("1.4", reply=_reply(tmp_path, {"claimed": "green", "red_sha": None}))
    assert not ev.get("first_commit")


# --- next_step -----------------------------------------------------------------------------

def _step(evidence: dict | None, reason: str = "hook failed", rung: str = "local-medium") -> tuple:
    return tier_ladder.next_step(tier_ladder.start("1.4", rung), "FAIL", CFG,
                                 reason=reason, evidence=evidence)


def test_next_step_halts_with_env_error_on_a_first_commit_hook_refusal() -> None:
    action, rung, rec = _step({"hook_tail": TAIL, "first_commit": True})
    assert (action, rung) == ("halt", None)
    assert rec["final"] == "env-error"
    assert rec["tier_path"] == ["local-medium"]
    assert rec["attempts"]["local-medium"] == 1  # the attempt counter still increments
    v = rec["verdicts"][0]
    assert v["class"] == REFUSED and v["stuck"] == REFUSED
    assert v["reason"].startswith("hook-refused: ")
    assert "FAILED tests/test_x.py::test_a - AssertionError 1 failed" in v["reason"]  # collapsed


def test_next_step_keeps_the_last_300_chars_of_a_long_tail() -> None:
    tail = "FAILED tests/test_x.py " + "x" * 500 + "\nEND-MARK"
    _action, _rung, rec = _step({"hook_tail": tail, "first_commit": True})
    reason = rec["verdicts"][0]["reason"]
    assert len(reason) == len("hook-refused: ") + 300
    assert reason.endswith("x END-MARK")


def test_next_step_without_the_first_commit_evidence_keeps_the_old_path() -> None:
    action, rung, rec = _step({"hook_tail": TAIL})
    assert (action, rung) == ("retry", "local-medium")
    assert rec["verdicts"][0]["class"] == "quality" and rec["final"] is None


def test_next_step_lets_a_size_guard_tail_escalate() -> None:
    action, rung, rec = _step({"hook_tail": SIZE_TAIL, "first_commit": True})
    assert (action, rung) == ("escalate", "opus-medium")
    assert rec["verdicts"][0]["class"] == "deterministic:size-split"


def test_next_step_halts_on_the_watchdogs_runaway_hook_refused_reason() -> None:
    reason = "runaway: hook-refused: FAILED tests/test_x.py::test_a - AssertionError"
    action, rung, rec = _step(None, reason=reason)
    assert (action, rung) == ("halt", None)
    assert rec["final"] == "env-error"
    v = rec["verdicts"][0]
    assert v["class"] == REFUSED and v["stuck"] == REFUSED
    assert v["reason"] == "hook-refused: FAILED tests/test_x.py::test_a - AssertionError"


def test_decision_entry_prints_the_stuck_line() -> None:
    _action, _rung, rec = _step({"hook_tail": TAIL, "first_commit": True})
    entry = to_decision_entry(rec)
    assert any(ln.startswith("stuck: hook-refused") for ln in entry.splitlines()), entry
    assert "### [tier] 1.4 — env-error" in entry


# --- the tier_ladder CLI -------------------------------------------------------------------

def _cli(*args: str) -> tuple[int, str]:
    env = dict(os.environ)
    env.pop("ANTHROPIC_BASE_URL", None)
    proc = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                          timeout=60, env=env)
    return proc.returncode, proc.stdout


def _cli_next(tmp_path: Path, last: dict) -> tuple[dict, dict]:
    """`start` a local-medium record, then `next --outcome FAIL` over a reply ending in `last`."""
    record, bare = tmp_path / "R.json", tmp_path / "bare"
    bare.mkdir()
    rc, _out = _cli("start", "--task", "1.4", "--tier", "local-medium", "--record", str(record),
                    "--route", json.dumps(ROUTED), "--root", str(bare))
    assert rc == 0
    rc, out = _cli("next", "--record", str(record), "--outcome", "FAIL", "--reason", "hook failed",
                   "--reply-json", _reply(tmp_path, last), "--root", str(bare))
    assert rc == 0, out
    return json.loads(out), json.loads(record.read_text(encoding="utf-8"))


def test_cli_next_halts_on_a_first_commit_hook_refusal(tmp_path) -> None:
    out, rec = _cli_next(tmp_path, {"claimed": "hook-failed", "red_sha": None})
    assert out["action"] == "halt" and out["rung"] is None
    assert rec["final"] == "env-error"
    v = rec["verdicts"][0]
    assert v["class"] == REFUSED and v["stuck"] == REFUSED
    assert v["reason"].startswith("hook-refused: ")


def test_cli_next_keeps_the_old_class_when_a_red_was_committed(tmp_path) -> None:
    out, rec = _cli_next(tmp_path, {"claimed": "hook-failed", "red_sha": "ab12cd3"})
    assert out["action"] == "retry" and out["rung"] == "local-medium"
    assert rec["final"] is None
    assert rec["verdicts"][0]["class"] == "quality"
