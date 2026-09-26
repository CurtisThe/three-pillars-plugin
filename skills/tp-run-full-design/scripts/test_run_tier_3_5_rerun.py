"""test_run_tier_3_5_rerun.py — the Tier 3.5 wrapper's re-run wiring.

design: local-implement-and-review

`run_tier_3_5.main()` runs with `subprocess.run` faked (cleanup + `ls-remote`) and
`rerun_phase_tests.rerun_phase` stubbed on the **source module** — the wrapper calls it
through the module attribute, so the stub survives the `del sys.modules` re-import.
"""
from __future__ import annotations

import importlib
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import rerun_phase_tests

SHA = "a1b2c3d4e5f6071829304a5b6c7d8e9f0a1b2c3d"
BRANCH = "candidate/demo-slug/single"
RERUN = {"plan_path": "three-pillars-docs/tp-designs/demo-slug/plan.md", "phase": 2,
         "phase_base_sha": "b" * 40}
SELF_REPORTED = {"passed": 3, "failed": 0, "skipped": 0, "raw": "3 passed"}


def _response(sha: str = SHA) -> str:
    body = {"schema": "tp-run-full-design/candidate/v1", "candidate_id": "single",
            "branch": BRANCH, "sha": sha, "summary": "Demo.", "test_results": SELF_REPORTED,
            "telemetry": {"duration_ms": 1, "tokens_used": 1, "tool_calls": 1}}
    return f"```json\n{json.dumps(body)}\n```\n"


def _result(status="passed", reason="", case=None, nodes=(), escaped=(), tail=""):
    return {"status": status, "reason": reason, "case": case, "nodes": list(nodes),
            "escaped_files": list(escaped), "unparsed_files": [], "output_tail": tail,
            "rc": None, "control": None}


def _node(tid, status, reason="", spec="tests/test_x.py::test_x"):
    return {"task_id": tid, "spec": spec, "status": status, "reason": reason}


def _main(tmp_path, monkeypatch, result, *, rerun=RERUN, remote_sha=SHA):
    """Run the wrapper → ``(exit_code, envelope, calls, design_dir)``."""
    design_dir = tmp_path / "design"
    design_dir.mkdir(parents=True)
    worktree = tmp_path / "worktree"
    worktree.mkdir(parents=True)
    payload = {"worker_response": _response(),
               "agent_meta": {"agentId": "agent-demo", "worktreePath": str(worktree)},
               "design_dir": str(design_dir), "candidate_id": "single", "slug": "demo-slug"}
    if rerun is not None:
        payload["rerun"] = rerun
    calls = []

    def stub(*args, **kwargs):
        calls.append((args, kwargs))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(rerun_phase_tests, "rerun_phase", stub)

    def fake_run(cmd, **kwargs):
        out = f"{remote_sha}\trefs/heads/{BRANCH}\n".encode() if "ls-remote" in cmd else b""
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=out, stderr=b"")

    sys.modules.pop("run_tier_3_5", None)
    wrapper = importlib.import_module("run_tier_3_5")
    import cleanup_worker_worktree as cww
    buf = io.StringIO()
    with patch.object(wrapper.subprocess, "run", side_effect=fake_run), \
            patch.object(cww.subprocess, "run", side_effect=fake_run), \
            patch.object(wrapper.sys, "stdin", io.StringIO(json.dumps(payload))), \
            patch.object(wrapper.sys, "stdout", buf):
        code = wrapper.main()
    return code, json.loads(buf.getvalue().strip()), calls, design_dir


def _log(design_dir: Path) -> str:
    path = design_dir / "decisions.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_rerun_failed_exits_2(tmp_path, monkeypatch):
    failed = _result("failed", case="f", tail="AssertionError: MARKER-9",
                     nodes=[_node("2.3", "failed", "red"), _node("2.4", "pass")])
    code, env, calls, _ = _main(tmp_path, monkeypatch, failed)
    assert code == 2
    assert (env["status"], env["case"], env["event_token"]) == ("escalate", "f", "rerun-failed")
    assert "2.3" in env["detail"] and "MARKER-9" in env["detail"]
    (args, kwargs), = calls
    assert args[1] == SHA and args[2:5] == (RERUN["plan_path"], 2, RERUN["phase_base_sha"])
    assert kwargs["test_cmd"] is None


def test_rerun_exception_is_rerun_error(tmp_path, monkeypatch):
    """impl-audit-1 #20: a re-run that raises escalates (exit 2, case None), never exit 1."""
    code, env, calls, _ = _main(tmp_path, monkeypatch, RuntimeError("scratch exploded"))
    assert (code, env["case"], env["event_token"]) == (2, None, "rerun-error")
    assert env["detail"] == "RuntimeError: scratch exploded" and len(calls) == 1


def test_missing_rerun_after_sha_check_is_stdin_invalid(tmp_path, monkeypatch):
    code, env, calls, _ = _main(tmp_path, monkeypatch, _result(), rerun=None)
    assert (code, env["case"], env["event_token"]) == (2, None, "stdin-invalid")
    assert "rerun" in env["detail"] and not calls
    # The SHA check is reached first: a mismatch still reports case e, not stdin-invalid.
    code, env, _, _ = _main(tmp_path / "e", monkeypatch, _result(), rerun=None,
                            remote_sha="d" * 40)
    assert (code, env["case"]) == (2, "e")
    for index, bad in enumerate(({**RERUN, "phase": "2"}, {**RERUN, "phase": -1},
                                 {**RERUN, "phase_base_sha": ""},
                {k: v for k, v in RERUN.items() if k != "plan_path"}, "not-an-object")):
        sub = tmp_path / f"bad{index}"
        code, env, calls, _ = _main(sub, monkeypatch, _result(), rerun=bad)
        assert (code, env["event_token"]) == (2, "stdin-invalid") and not calls


def test_phase_zero_is_a_valid_rerun_phase():
    """PR #165 r1: plans may start at `## Phase 0`; its re-run must not be stdin-invalid."""
    import tier_3_5_rerun

    out = tier_3_5_rerun.validate_rerun({"rerun": {**RERUN, "phase": 0}})
    assert out["phase"] == 0


def test_validate_rerun_key_sets():
    """`test_cmd` is optional (None when absent); each required key is enforced."""
    import pytest
    import tier_3_5_rerun

    assert tier_3_5_rerun.validate_rerun({"rerun": RERUN}) == {**RERUN, "test_cmd": None}
    out = tier_3_5_rerun.validate_rerun({"rerun": {**RERUN, "test_cmd": "pytest -q"}})
    assert out["test_cmd"] == "pytest -q"
    for key in RERUN:
        with pytest.raises((KeyError, TypeError, ValueError)):
            tier_3_5_rerun.validate_rerun({"rerun": {k: v for k, v in RERUN.items() if k != key}})


def test_skipped_unverified_escape_self_logged(tmp_path, monkeypatch):
    mixed = _result(nodes=[_node("2.1", "pass"), _node("2.2", "unverified", "targets-missing"),
                           _node("2.3", "unverified", "timeout")],
                    escaped=["src/stray.py", "docs/x.md"])
    code, env, _, design_dir = _main(tmp_path, monkeypatch, mixed)
    assert (code, env["status"], env["event_token"]) == (0, "ok", "ok")
    log = _log(design_dir)
    assert "[tp-run-full-design/tier-3.5] rerun-unverified 2" in log
    assert "[tp-run-full-design/tier-3.5] files-escape-logged src/stray.py docs/x.md" in log
    code, env, _, design_dir = _main(tmp_path / "s", monkeypatch,
                                     _result("skipped", "no-runner"))
    assert (code, env["status"]) == (0, "ok")
    assert "[tp-run-full-design/tier-3.5] rerun-skipped no-runner" in _log(design_dir)


def test_results_json_is_rerun(tmp_path, monkeypatch):
    mixed = _result(nodes=[_node("2.1", "pass"), _node("2.2", "unverified", "timeout"),
                           _node("2.3", "excluded", "Blocked")])
    _, _, _, design_dir = _main(tmp_path, monkeypatch, mixed)
    results = design_dir / "candidates" / "single" / "test-results.json"
    data = json.loads(results.read_text(encoding="utf-8"))
    assert data["source"] == "tier-3.5-rerun"
    assert (data["status"], data["passed"], data["failed"], data["unverified"]) == (
        "passed", 1, 0, 1)
    assert "2.2" in data["raw"]
    assert data["self_reported"] == SELF_REPORTED


def test_nothing_verified_phase_self_logged_never_a_pass(tmp_path, monkeypatch):
    """A phase that verified nothing: exit 0 and self-logged, but recorded as
    ``unverified`` (never ``passed``) and never escalated as case f."""
    nothing = _result("unverified", "nothing-verified",
                      nodes=[_node("2.1", "unverified", "runner-error")])
    code, env, _, design_dir = _main(tmp_path, monkeypatch, nothing)
    assert (code, env["status"], env["case"]) == (0, "ok", None)
    assert ("[tp-run-full-design/tier-3.5] rerun-phase-unverified nothing-verified"
            in _log(design_dir))
    results = design_dir / "candidates" / "single" / "test-results.json"
    data = json.loads(results.read_text(encoding="utf-8"))
    assert (data["status"], data["passed"], data["unverified"]) == ("unverified", 0, 1)
    assert data["raw"].startswith("rerun-phase-unverified nothing-verified")
