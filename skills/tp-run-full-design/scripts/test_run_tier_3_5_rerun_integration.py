"""test_run_tier_3_5_rerun_integration.py — the wrapper against a real re-run.

design: local-implement-and-review (impl-audit-1 #20)

Every other wrapper test stubs `rerun_phase`. This one runs `run_tier_3_5.main()` in a
`rerun_fixture` tmp repo (cwd = the repo) with the real re-run and a real `origin` for
the `git ls-remote` SHA check; only the worker-worktree cleanup is stubbed (there is no
worker worktree). A red phase test must come back as exit 2, case f — so a wrong
`Path.cwd()` or `design_dir` wiring cannot hide behind the stubs.
"""
from __future__ import annotations

import importlib
import io
import json
import sys
from unittest.mock import patch

from rerun_fixture import DD, PLAN, commit, git, leftovers, make_repo, plan, task

RED = "def test_ok():\n    assert False, 'MARKER-INTEGRATION-20'\n"


def _response(sha: str) -> str:
    body = {"schema": "tp-run-full-design/candidate/v1", "candidate_id": "single",
            "branch": "candidate/demo/single", "sha": sha, "summary": "Demo.",
            "test_results": {"passed": 1, "failed": 0, "skipped": 0, "raw": "1 passed"},
            "telemetry": {"duration_ms": 1, "tokens_used": 1, "tool_calls": 1}}
    return f"```json\n{json.dumps(body)}\n```\n"


def test_wrapper_real_rerun_red_is_case_f(tmp_path, monkeypatch):
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [task("1.1", "`tests/test_a.py::test_ok`")]}),
                        "tests/test_a.py": RED})
    origin = tmp_path / "origin.git"
    git(repo, "init", "-q", "--bare", str(origin))
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-q", "origin", "HEAD:refs/heads/candidate/demo/single")
    payload = {"worker_response": _response(sha),
               "agent_meta": {"agentId": "agent-x", "worktreePath": str(tmp_path / "gone")},
               "design_dir": str(repo / DD), "candidate_id": "single", "slug": "demo",
               "rerun": {"plan_path": PLAN, "phase": 1, "phase_base_sha": base,
                         "test_cmd": f"{sys.executable} -m pytest"}}
    monkeypatch.chdir(repo)
    sys.modules.pop("run_tier_3_5", None)
    wrapper = importlib.import_module("run_tier_3_5")
    monkeypatch.setattr(wrapper, "cleanup_worker_worktree", lambda **_kw: None)
    buf = io.StringIO()
    with patch.object(wrapper.sys, "stdin", io.StringIO(json.dumps(payload))), \
            patch.object(wrapper.sys, "stdout", buf):
        code = wrapper.main()
    env = json.loads(buf.getvalue().strip())
    assert (code, env["case"], env["event_token"]) == (2, "f", "rerun-failed"), env
    assert "1.1" in env["detail"] and "MARKER-INTEGRATION-20" in env["detail"]
    results = json.loads((repo / DD / "candidates" / "single" / "test-results.json")
                         .read_text(encoding="utf-8"))
    assert (results["source"], results["failed"]) == ("tier-3.5-rerun", 1)
    assert leftovers(repo) == ([], [], 1)
