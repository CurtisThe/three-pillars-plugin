"""telemetry.json must not carry an absolute host path (consumer pre-commit gates)."""
import copy
import json
from pathlib import Path

from portable_path import OUTSIDE_MARKER
from write_candidate_artifacts import write_candidate_artifacts


def _parsed() -> dict:
    return {
        "schema": "tp-run-full-design/candidate/v1",
        "candidate_id": "single",
        "branch": "candidate/my-slug/single",
        "sha": "a1b2c3d4e5f6071829304a5b6c7d8e9f0a1b2c3d",
        "summary": "done",
        "test_results": {"passed": 1, "failed": 0, "skipped": 0, "raw": "1 passed"},
        "telemetry": {"tokens_used": 10},
    }


def _write(tmp_path: Path, agent_meta: dict) -> tuple[dict, str]:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    design_dir = repo / "three-pillars-docs" / "tp-designs" / "my-slug"
    design_dir.mkdir(parents=True)
    write_candidate_artifacts(_parsed(), design_dir, agent_meta)
    text = (design_dir / "candidates" / "single" / "telemetry.json").read_text(encoding="utf-8")
    return json.loads(text), text


def test_absolute_paths_become_portable(tmp_path):
    wt = tmp_path / "repo" / ".claude" / "worktrees" / "agent-a"
    meta = {"agentId": "agent-a", "worktreePath": str(wt),
            "other": "/elsewhere/x", "n": None, "model": "opus"}
    telemetry, text = _write(tmp_path, meta)
    assert telemetry["worktreePath"] == ".claude/worktrees/agent-a"
    assert telemetry["other"] == f"{OUTSIDE_MARKER}:x"
    assert telemetry["n"] is None
    assert telemetry["agentId"] == "agent-a"
    assert telemetry["model"] == "opus"
    assert telemetry["tokens_used"] == 10
    assert str(tmp_path) not in text


def test_caller_agent_meta_is_not_mutated(tmp_path):
    wt = str(tmp_path / "repo" / ".claude" / "worktrees" / "agent-a")
    meta = {"agentId": "agent-a", "worktreePath": wt}
    before = copy.deepcopy(meta)
    _write(tmp_path, meta)
    assert meta == before
    assert Path(meta["worktreePath"]).is_absolute()


def test_worker_reported_absolute_path_is_portable(tmp_path):
    parsed_extra = {"log": str(tmp_path / "repo" / ".claude" / "worktrees" / "agent-a" / "run.log")}
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    design_dir = repo / "three-pillars-docs" / "tp-designs" / "my-slug"
    design_dir.mkdir(parents=True)
    parsed = _parsed()
    parsed["telemetry"] = {**parsed["telemetry"], **parsed_extra}
    write_candidate_artifacts(parsed, design_dir, {"agentId": "a"})
    text = (design_dir / "candidates" / "single" / "telemetry.json").read_text(encoding="utf-8")
    assert json.loads(text)["log"] == ".claude/worktrees/agent-a/run.log"
    assert str(tmp_path) not in text
    assert parsed["telemetry"]["log"] == parsed_extra["log"]  # caller's dict untouched
