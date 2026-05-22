"""Tests for write_candidate_artifacts — emits per-candidate worker artifacts."""
import json
import os
import re
from pathlib import Path

import pytest

from write_candidate_artifacts import write_candidate_artifacts


def _parsed_example() -> dict:
    return {
        "schema": "tp-run-full-design/candidate/v1",
        "candidate_id": "single",
        "branch": "candidate/my-slug/single",
        "sha": "a1b2c3d4e5f6071829304a5b6c7d8e9f0a1b2c3d",
        "summary": "Implemented the thing; tests pass.",
        "test_results": {"passed": 12, "failed": 0, "skipped": 0, "raw": "12 passed"},
        "telemetry": {"duration_ms": 4200, "tokens_used": 18500, "tool_calls": 47},
    }


def _agent_meta_example() -> dict:
    return {"agent_id": "agent-abc123", "model": "claude-opus-4-7"}


def test_a_writes_four_files_with_expected_content(tmp_path: Path) -> None:
    parsed = _parsed_example()
    agent_meta = _agent_meta_example()

    write_candidate_artifacts(parsed, tmp_path, agent_meta)

    cand_dir = tmp_path / "candidates" / "single"
    assert cand_dir.is_dir(), "candidate dir should exist"

    branch_txt = cand_dir / "branch.txt"
    summary_md = cand_dir / "summary.md"
    test_results_json = cand_dir / "test-results.json"
    telemetry_json = cand_dir / "telemetry.json"

    assert branch_txt.read_text() == "candidate/my-slug/single\n"
    assert summary_md.read_text() == (
        "# Candidate single\n\nImplemented the thing; tests pass.\n"
    )

    tr = json.loads(test_results_json.read_text())
    assert tr == parsed["test_results"]
    # Pretty-printed with 2-space indent
    assert "\n  " in test_results_json.read_text()


def test_b_telemetry_merges_parsed_telemetry_agent_meta_and_iso_timestamp(
    tmp_path: Path,
) -> None:
    parsed = _parsed_example()
    agent_meta = _agent_meta_example()

    write_candidate_artifacts(parsed, tmp_path, agent_meta)

    telemetry = json.loads(
        (tmp_path / "candidates" / "single" / "telemetry.json").read_text()
    )
    # Original telemetry fields preserved
    assert telemetry["duration_ms"] == 4200
    assert telemetry["tokens_used"] == 18500
    assert telemetry["tool_calls"] == 47
    # Agent meta merged in
    assert telemetry["agent_id"] == "agent-abc123"
    assert telemetry["model"] == "claude-opus-4-7"
    # ISO timestamp (e.g., 2026-05-22T13:45:01Z)
    assert "written_at" in telemetry
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", telemetry["written_at"]
    ), f"unexpected timestamp format: {telemetry['written_at']!r}"


def test_c_atomic_write_no_partials_on_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parsed = _parsed_example()
    agent_meta = _agent_meta_example()

    real_replace = os.replace
    call_count = {"n": 0}

    def flaky_replace(src, dst):
        call_count["n"] += 1
        # Fail on the second os.replace call — after at least one file was placed
        if call_count["n"] == 2:
            # Clean up the staging file ourselves so the test environment is clean
            try:
                os.unlink(src)
            except OSError:
                pass
            raise OSError("simulated mid-write failure")
        return real_replace(src, dst)

    monkeypatch.setattr(
        "write_candidate_artifacts.os.replace", flaky_replace, raising=True
    )

    with pytest.raises(OSError, match="simulated mid-write failure"):
        write_candidate_artifacts(parsed, tmp_path, agent_meta)

    cand_dir = tmp_path / "candidates" / "single"
    # The candidate dir may exist (we mkdir before writes), but the file that
    # failed mid-write must not appear at its final path. Any staging tmp file
    # must also be gone (or, at minimum, the final paths beyond the first
    # successful write must not exist).
    final_files = [
        cand_dir / "branch.txt",
        cand_dir / "summary.md",
        cand_dir / "test-results.json",
        cand_dir / "telemetry.json",
    ]
    # At most one of the four final files should exist (the one that succeeded
    # before the simulated failure). The failed write must not leave a final file.
    existing = [p for p in final_files if p.exists()]
    assert len(existing) <= 1, f"too many final files survived: {existing}"

    # No partial tmp staging files should be lingering at the final paths.
    if cand_dir.exists():
        leftover_tmps = [
            p
            for p in cand_dir.iterdir()
            if ".tmp." in p.name
        ]
        assert leftover_tmps == [], f"staging tmp files leaked: {leftover_tmps}"


def test_d_idempotent_second_call_overwrites_cleanly(tmp_path: Path) -> None:
    parsed_v1 = _parsed_example()
    write_candidate_artifacts(parsed_v1, tmp_path, _agent_meta_example())

    parsed_v2 = _parsed_example()
    parsed_v2["branch"] = "candidate/my-slug/single"
    parsed_v2["summary"] = "Second run — different summary."
    parsed_v2["test_results"] = {
        "passed": 20,
        "failed": 1,
        "skipped": 2,
        "raw": "20 passed 1 failed 2 skipped",
    }
    parsed_v2["telemetry"] = {
        "duration_ms": 9999,
        "tokens_used": 1,
        "tool_calls": 2,
    }

    write_candidate_artifacts(parsed_v2, tmp_path, {"agent_id": "agent-xyz"})

    cand_dir = tmp_path / "candidates" / "single"
    assert (cand_dir / "summary.md").read_text() == (
        "# Candidate single\n\nSecond run — different summary.\n"
    )
    tr = json.loads((cand_dir / "test-results.json").read_text())
    assert tr["passed"] == 20
    assert tr["failed"] == 1
    telemetry = json.loads((cand_dir / "telemetry.json").read_text())
    assert telemetry["duration_ms"] == 9999
    assert telemetry["agent_id"] == "agent-xyz"
    # The previous run's agent_meta keys should not leak into the second write.
    assert "model" not in telemetry

    # No stale staging tmp files left behind.
    leftover_tmps = [p for p in cand_dir.iterdir() if ".tmp." in p.name]
    assert leftover_tmps == []
