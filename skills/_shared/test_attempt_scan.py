"""Tests for attempt_scan.py — locate() (run-throughput 1.5) and scan() flags (2.9)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import attempt_scan  # noqa: E402
import design_run_command as drc  # noqa: E402

BODY = '{"type": "assistant", "timestamp": "2026-09-28T15:00:18.400Z"}\n'
FIXTURES = json.loads((HERE / "fixtures" / "attempt_scan" / "transcripts.json")
                      .read_text(encoding="utf-8"))["cases"]


def _plant(base: Path, agent_id: str) -> Path:
    """A subagent transcript at <base>/projects/p/s/subagents/agent-<id>.jsonl."""
    path = base / "projects" / "p" / "s" / "subagents" / f"agent-{agent_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(BODY, encoding="utf-8")
    return path


def _write_case(tmp_path: Path, name: str) -> Path:
    path = tmp_path / f"{name}.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for rec in FIXTURES[name]:
            fh.write(json.dumps(rec) + "\n")
    return path


def _flags(tmp_path, name):
    return attempt_scan.scan(_write_case(tmp_path, name))["flags"]


def test_locate_via_config_dir(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    found = _plant(cfg, "abc")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    assert attempt_scan.locate("abc", None) == found
    assert attempt_scan.locate("abc", cfg) == found


def test_locate_falls_back_to_home_claude(tmp_path, monkeypatch):
    found = _plant(tmp_path / ".claude", "abc")
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg, warning = drc.resolve_config_dir(os.environ)
    assert cfg is None
    assert warning and "CLAUDE_CONFIG_DIR" in warning
    assert attempt_scan.locate("abc", None) == found


def test_locate_unknown_id_is_none(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    _plant(cfg, "abc")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    assert attempt_scan.locate("zzz", None) is None


def test_identical_calls_total_below_threshold_no_flag(tmp_path):
    assert not any("identical-calls" in f for f in _flags(tmp_path, "identical_calls_total_4"))


def test_identical_calls_total_at_threshold_flags(tmp_path):
    flags = _flags(tmp_path, "identical_calls_total_5")
    assert any(f == "identical-calls 5x Bash" for f in flags)


def test_identical_calls_row_below_threshold_no_flag(tmp_path):
    assert not any("identical-calls" in f for f in _flags(tmp_path, "identical_calls_row_2"))


def test_identical_calls_row_at_threshold_flags(tmp_path):
    flags = _flags(tmp_path, "identical_calls_row_3")
    assert any("identical-calls" in f and "Bash" in f for f in flags)


def test_reverted_edit_below_threshold_no_flag(tmp_path):
    assert not any("reverted-edit" in f for f in _flags(tmp_path, "reverted_edit_1"))


def test_reverted_edit_at_threshold_flags(tmp_path):
    flags = _flags(tmp_path, "reverted_edit_2")
    assert any(f.startswith("reverted-edit 2x") for f in flags)


def test_same_test_red_below_threshold_no_flag(tmp_path):
    assert not any("same-test-red" in f for f in _flags(tmp_path, "same_test_red_4"))


def test_same_test_red_at_threshold_flags(tmp_path):
    flags = _flags(tmp_path, "same_test_red_5")
    assert any(f.startswith("same-test-red 5x") for f in flags)


def test_reasoning_tokens_below_threshold_no_flag(tmp_path):
    assert not any("reasoning-without-action" in f for f in _flags(tmp_path, "reasoning_tokens_23999"))


def test_reasoning_tokens_at_threshold_flags(tmp_path):
    flags = _flags(tmp_path, "reasoning_tokens_24000")
    assert any("24000-token turn" in f for f in flags)


def test_reasoning_toolfree_below_threshold_no_flag(tmp_path):
    assert not any("tool-free turns" in f for f in _flags(tmp_path, "reasoning_toolfree_1"))


def test_reasoning_toolfree_at_threshold_flags(tmp_path):
    flags = _flags(tmp_path, "reasoning_toolfree_2")
    assert any("2x tool-free turns" in f for f in flags)


def test_split_multi_block_is_one_turn(tmp_path):
    out = attempt_scan.scan(_write_case(tmp_path, "split_multi_block"))
    assert out["turns"] == 1


def test_missing_file_returns_flags_and_error(tmp_path):
    out = attempt_scan.scan(tmp_path / "nope.jsonl")
    assert out["flags"] == []
    assert "error" in out


def test_cli_scan_by_path_exits_zero(tmp_path, capsys):
    path = _write_case(tmp_path, "identical_calls_total_5")
    rc = attempt_scan.main(["scan", "--path", str(path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert any(f == "identical-calls 5x Bash" for f in out["flags"])


def test_cli_scan_missing_agent_exits_zero(capsys):
    rc = attempt_scan.main(["scan", "--agent-id", "nope-such-agent"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["flags"] == []
    assert "error" in out
