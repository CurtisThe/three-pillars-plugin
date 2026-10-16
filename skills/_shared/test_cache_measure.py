#!/usr/bin/env python3
"""test_cache_measure.py — per-agent-type cache read/write and over-TTL gaps (Behavior 5).

design: prompt-cache-aware-dispatch (Task 1.2)

The 10-15 finding: one `tp-worker` dispatcher waited past the 300 s prompt cache
between its own task calls, so every wake re-wrote its whole prefix — 10 gaps,
1.38M cache-write tokens on them. The fixture here is that dispatcher: a main
session plus one subagent transcript whose `.meta.json` names its agent type.
The numbers are the fixture's own arithmetic, so a gap counted twice, or a turn
counted per streamed record, moves them.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cache_measure
import run_cost

# the 10-15 dispatcher's waits, in seconds, between its first turn and its last
GAPS_1015 = [392, 410, 433, 450, 470, 488, 512, 540, 575, 599]

_BASE = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc)


def _ts(offset_s: int) -> str:
    """ISO-8601 with `Z`, `offset_s` after the fixture's first turn."""
    return (_BASE + timedelta(seconds=offset_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _turn(msg_id: str, ts: str, write: int, read: int = 0) -> dict:
    """One assistant record shaped like a Claude Code transcript line."""
    return {"type": "assistant", "timestamp": ts,
            "message": {"id": msg_id, "model": "claude-sonnet-4-5",
                        "stop_reason": "end_turn",
                        "usage": {"input_tokens": 1,
                                  "cache_creation_input_tokens": write,
                                  "cache_read_input_tokens": read,
                                  "output_tokens": 1}}}


def _write(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def wave_1015(tmp_path: Path) -> Path:
    """The 10-15 run's transcripts under `<cfg>/projects/-x-wt-demo/`; the project dir."""
    proj = tmp_path / "cfg" / "projects" / "-x-wt-demo"
    _write(proj / "s1.jsonl",
           [_turn(f"m{i}", _ts(60 * i), 1_000) for i in range(3)])

    subagents = proj / "s1" / "subagents"
    subagents.mkdir(parents=True, exist_ok=True)
    (subagents / "agent-a1.meta.json").write_text(json.dumps({"agentType": "tp-worker"}),
                                                  encoding="utf-8")
    offsets = [0]
    for gap in GAPS_1015:
        offsets.append(offsets[-1] + gap)
    offsets.append(offsets[-1] + 30)   # inside the TTL
    offsets.append(offsets[-1] + 300)  # exactly the TTL, so not over it
    writes = [200_000] + [138_000] * 10 + [2_000, 50_000]
    reads = [0] + [100_000] * 10 + [0, 0]
    _write(subagents / "agent-a1.jsonl",
           [_turn(f"a{i}", _ts(off), w, r)
            for i, (off, w, r) in enumerate(zip(offsets, writes, reads))])
    return proj


def test_reproduces_the_1015_finding(tmp_path: Path) -> None:
    """10 gaps over the TTL, and the 1.38M cache write the gaps paid for."""
    result = cache_measure.measure(*cache_measure.run_paths(wave_1015(tmp_path)))

    worker = result["tp-worker"]
    assert worker["gaps_over_ttl"] == 10
    assert worker["gap_cache_write"] == 1_380_000
    assert worker["turns"] == 13
    assert worker["cache_write"] == 1_632_000
    assert worker["cache_read"] == 1_000_000


def test_main_session_is_the_orchestrator_role(tmp_path: Path) -> None:
    """Every main transcript is the orchestrator; its 60 s gaps are all inside the TTL."""
    result = cache_measure.measure(*cache_measure.run_paths(wave_1015(tmp_path)))

    assert result[run_cost.ORCHESTRATOR]["turns"] == 3
    assert result[run_cost.ORCHESTRATOR]["gaps_over_ttl"] == 0


def test_streamed_reply_counts_once(tmp_path: Path) -> None:
    """Two records sharing a `message.id` are one reply, so one turn."""
    proj = tmp_path / "projects" / "-p"
    _write(proj / "s.jsonl", [
        _turn("msg_1", _ts(0), 5_000),
        _turn("msg_1", _ts(5), 5_000),
    ])

    assert cache_measure.measure(*cache_measure.run_paths(proj))[
        run_cost.ORCHESTRATOR]["turns"] == 1


def test_format_line(tmp_path: Path) -> None:
    """One line, `[cache] ` first, the worker segment carrying its gaps and their write."""
    result = cache_measure.measure(*cache_measure.run_paths(wave_1015(tmp_path)))

    line = cache_measure.format_line(result)
    assert "\n" not in line
    assert line.startswith("[cache] ")
    segments = [s for s in line[len("[cache] "):].split("; ") if s.startswith("tp-worker ")]
    assert len(segments) == 1
    assert "gaps>300s=10" in segments[0]
    assert "gap_write=1.38M" in segments[0]


def test_no_transcripts(tmp_path: Path, capsys) -> None:
    """Nothing to read is one line said out loud, never an empty success."""
    assert cache_measure.format_line({}) == "cache: no transcripts"

    empty = tmp_path / "empty"
    empty.mkdir()
    assert cache_measure.main(["--project-dir", str(empty)]) == 0
    assert capsys.readouterr().out == "cache: no transcripts\n"


def test_project_dir_slug() -> None:
    """A cwd becomes a project dir the way Claude Code slugs it: non-alnum to `-`."""
    assert cache_measure.project_dir("/a/b_c.d", "/cfg") == Path("/cfg/projects/-a-b-c-d")


def test_config_dir_from_env(tmp_path: Path, monkeypatch, capsys) -> None:
    """`--cwd` plus `$CLAUDE_CONFIG_DIR` finds the run's transcripts; `--line` prints one line."""
    cfg = tmp_path / "cfg"
    proj = wave_1015(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))

    assert cache_measure.main(["--cwd", "/x/wt/demo", "--line"]) == 0
    expected = cache_measure.format_line(cache_measure.measure(*cache_measure.run_paths(proj)))
    assert capsys.readouterr().out == expected + "\n"
