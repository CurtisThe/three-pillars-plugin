"""test_dispatch_log_usage.py — `record --agent-id`: the spawn's transcript usage on the row.

design: task-worker-sonnet (task 1.5, the M47 fix for slot rows)

With `--agent-id`, the row's `tokens` becomes the transcript's cumulative fresh usage
(`input + cache_write + output` over `transcript_usage.summarize`), the harness number is
kept as `tokens_harness`, and `tokens_reason` is cleared when the fresh total is recorded.
An id with a leading `agent-` strips it. A transcript we cannot find or parse leaves the
row as today with a `usage_reason`. The CLI never errors and never raises.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import dispatch_log  # noqa: E402

CLI = _SHARED / "dispatch_log.py"
FIXTURE = _SHARED / "fixtures" / "transcript_usage" / "agent-mixed.jsonl"
FRESH = 7517  # the fixture's input + cache_write + output
HARNESS = 120000


def _plant(cfg: Path, agent_id: str, body: Path = FIXTURE) -> Path:
    """A subagent transcript at <cfg>/projects/p/s/subagents/agent-<id>.jsonl."""
    path = cfg / "projects" / "p" / "s" / "subagents" / f"agent-{agent_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(body, path)
    return path


def _base(design_dir: str, cfg: Path, *extra: str) -> list[str]:
    return ["record", "--design-dir", design_dir, "--role", "generator",
            "--agent", "tp-generator", "--reason", "r", "--outcome", "pass",
            "--config-dir", str(cfg), *extra]


def _row(design_dir: Path) -> dict:
    (line,) = (design_dir / "dispatch-telemetry.ndjson").read_text(encoding="utf-8").splitlines()
    return json.loads(line)


def _usage(design_dir: Path) -> dict:
    return _row(design_dir)["usage"]


def test_transcript_usage_replaces_the_harness_total(tmp_path):
    cfg = tmp_path / "cfg"
    _plant(cfg, "abc")
    d = tmp_path / "design"
    d.mkdir()
    rc = dispatch_log.main(_base(str(d), cfg, "--tokens", "120000", "--agent-id", "abc"))
    assert rc == 0
    row = _row(d)
    assert row["tokens"] == FRESH
    assert row["tokens"] != HARNESS
    assert row["tokens_harness"] == HARNESS
    assert row["usage_source"] == "mixed"
    assert row["usage"]["output_tokens"] == 2803
    assert row["usage"]["cache_read_input_tokens"] == 50000  # includes message E's 18000
    assert row["tokens_reason"] is None
    assert row["usage_reason"] is None


def test_prefixed_agent_id_strips_the_agent_prefix(tmp_path):
    cfg = tmp_path / "cfg"
    _plant(cfg, "abc")
    d = tmp_path / "design"
    d.mkdir()
    rc = dispatch_log.main(_base(str(d), cfg, "--tokens", "120000", "--agent-id", "agent-abc"))
    assert rc == 0
    row = _row(d)
    assert row["tokens"] == FRESH
    assert row["usage_source"] == "mixed"
    assert row["usage"]["output_tokens"] == 2803
    assert row["tokens_harness"] == HARNESS
    assert row["usage_reason"] is None


def test_no_tokens_flag_keeps_null_harness_and_clears_reason(tmp_path):
    cfg = tmp_path / "cfg"
    _plant(cfg, "abc")
    d = tmp_path / "design"
    d.mkdir()
    rc = dispatch_log.main(_base(str(d), cfg, "--agent-id", "abc"))
    assert rc == 0
    row = _row(d)
    assert row["tokens"] == FRESH
    assert row["tokens_harness"] is None
    # the "the spawn reported no usage total" reason measure() set is cleared
    assert row["tokens_reason"] is None


def test_unknown_agent_id_keeps_the_harness_total_with_a_reason(tmp_path):
    cfg = tmp_path / "cfg"
    _plant(cfg, "abc")
    d = tmp_path / "design"
    d.mkdir()
    rc = dispatch_log.main(_base(str(d), cfg, "--tokens", "120000", "--agent-id", "zzz"))
    assert rc == 0
    row = _row(d)
    assert row["tokens"] == HARNESS
    assert row["usage_source"] is None
    assert row["usage_reason"] == "no transcript for agent id"


def test_undecodable_transcript_is_a_reason_not_an_error(tmp_path):
    cfg = tmp_path / "cfg"
    garbage = cfg / "projects" / "p" / "s" / "subagents" / "agent-xyz.jsonl"
    garbage.parent.mkdir(parents=True, exist_ok=True)
    garbage.write_text("this line is malformed\nand so is this one\n", encoding="utf-8")
    d = tmp_path / "design"
    d.mkdir()
    proc = subprocess.run(
        [sys.executable, str(CLI), *_base(str(d), cfg, "--tokens", "120000",
                                          "--agent-id", "xyz")],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0
    assert "Traceback" not in proc.stderr
    row = _row(d)
    assert row["usage_source"] is None
    assert row["usage_reason"]
    assert "usage" in row["usage_reason"]
    assert row["tokens"] == HARNESS  # the harness value stays


def test_without_agent_id_the_row_shape_is_today(tmp_path):
    cfg = tmp_path / "cfg"
    _plant(cfg, "abc")
    d = tmp_path / "design"
    d.mkdir()
    rc = dispatch_log.main(_base(str(d), cfg, "--tokens", "120000"))
    assert rc == 0
    row = _row(d)
    assert "usage" not in row
    assert "usage_source" not in row
    assert "usage_reason" not in row
    assert "tokens_harness" not in row
    assert row["tokens"] == HARNESS
