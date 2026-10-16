#!/usr/bin/env python3
"""test_cache_measure_append.py - one `[cache]` line appended to `decisions.md`.

design: prompt-cache-aware-dispatch (Task 1.7, Behavior 5)

`/tp-design-learn` closes a design by appending its cache profile to the design's
own `decisions.md`, so the numbers a run actually paid for live where that run's
decisions already live. The contract is the append, not the prose: one line, the
same line stdout printed, the file's existing content untouched, a missing file
created. A run with no transcripts still logs something - `cache: no transcripts`
- never a silent no-op.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cache_measure

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


def one_worker(tmp_path: Path) -> Path:
    """A project dir holding one `tp-worker` subagent, two turns 400 s apart.

    400 s is over the 300 s TTL, so the second turn is a gap and its cache write
    is charged to it - the shape the line reports."""
    proj = tmp_path / "projects" / "-x-wt-demo"
    subagents = proj / "s1" / "subagents"
    subagents.mkdir(parents=True, exist_ok=True)
    (subagents / "agent-b1.meta.json").write_text(json.dumps({"agentType": "tp-worker"}),
                                                  encoding="utf-8")
    records = [_turn("a0", _ts(0), 120_000), _turn("a1", _ts(400), 120_000, 120_000)]
    (subagents / "agent-b1.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return proj


def test_append_adds_one_cache_line(tmp_path: Path, capsys) -> None:
    """The file keeps its content and gains exactly one line, the line stdout printed."""
    proj = one_worker(tmp_path)
    dec = tmp_path / "decisions.md"
    dec.write_text("# log\n", encoding="utf-8")

    assert cache_measure.main(["--project-dir", str(proj), "--append", str(dec)]) == 0

    printed = capsys.readouterr().out
    lines = dec.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# log"
    assert len(lines) == 2
    assert lines[1].startswith("[cache] ")
    assert printed == lines[1] + "\n"


def test_append_without_transcripts_logs_the_fallback(tmp_path: Path) -> None:
    """Nothing measured still appends one line saying so."""
    empty = tmp_path / "empty"
    empty.mkdir()
    dec = tmp_path / "decisions.md"
    dec.write_text("# log\n", encoding="utf-8")

    assert cache_measure.main(["--project-dir", str(empty), "--append", str(dec)]) == 0

    assert dec.read_text(encoding="utf-8") == "# log\ncache: no transcripts\n"


def test_append_to_a_file_without_trailing_newline(tmp_path: Path, capsys) -> None:
    """A file that ends mid-line gets its newline first, so the line stays whole."""
    proj = one_worker(tmp_path)
    dec = tmp_path / "decisions.md"
    dec.write_text("# log", encoding="utf-8")

    assert cache_measure.main(["--project-dir", str(proj), "--append", str(dec)]) == 0

    printed = capsys.readouterr().out
    line = printed.strip()
    assert dec.read_text(encoding="utf-8") == "# log\n" + line + "\n"


def test_append_creates_a_missing_file(tmp_path: Path, capsys) -> None:
    """A design log that does not exist yet ends up holding only the line."""
    proj = one_worker(tmp_path)
    dec = tmp_path / "notes" / "decisions.md"

    assert cache_measure.main(["--project-dir", str(proj), "--append", str(dec)]) == 0

    printed = capsys.readouterr().out
    assert dec.read_text(encoding="utf-8") == printed
