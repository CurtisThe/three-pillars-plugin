"""Tests for router_archive.py across a trim: B6, the tail check, anchors and anchor-lost gaps.

design: cheap-tier-local-routing 1.2 (detailed-design.md §Interfaces `router_archive.py`,
§Test Strategy B6, §Notes 8). A trim is simulated the way a trimmer does it: cut the log to its
last N lines either in place (same inode) or by writing a new file over it (new inode). Every
line is built here (skills/_shared/test-fragility.md, fix 2); paths point at tmp_path only.
"""
from __future__ import annotations

import datetime
import json
import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import router_archive as ra  # noqa: E402
import router_history as rh  # noqa: E402

UTC = datetime.timezone.utc
RUN1 = datetime.datetime(2026, 10, 2, 5, 59, 0, tzinfo=UTC)
RUN2 = datetime.datetime(2026, 10, 2, 6, 1, 0, tzinfo=UTC)
RUN2_ISO = "2026-10-02T06:01:00Z"


def line(n: int, minute: int = 0) -> str:
    stamp = f"2026-10-01 10:{minute + n // 60:02d}:{n % 60:02d}"
    return (f"[{stamp}] POST /v1/messages  model=qwen3.8-27b-240k  sess=9a207ac4  agent=a9ac0e2b"
            f"  effort=medium  -> local (model resident) owner=9a207ac4  ({1000 + n}B)")


def lines(lo: int, hi: int) -> list[str]:
    return [line(n) for n in range(lo, hi + 1)]


def write(path: Path, rows) -> Path:
    path.write_text("".join(f"{x}\n" for x in rows), encoding="utf-8")
    return path


def add(path: Path, rows) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("".join(f"{x}\n" for x in rows))


def trim_in_place(path: Path, keep: int) -> None:
    kept = path.read_text(encoding="utf-8").splitlines()[-keep:]
    with open(path, "r+", encoding="utf-8") as fh:
        fh.write("".join(f"{x}\n" for x in kept))
        fh.truncate()


def trim_new_inode(path: Path, keep: int) -> None:
    kept = path.read_text(encoding="utf-8").splitlines()[-keep:]
    tmp = write(path.with_name(path.name + ".trim"), kept)
    os.replace(tmp, path)


def archived(d: Path) -> list[str]:
    out = []
    for p in sorted(d.glob("router-*.log")):
        stem = p.stem[len("router-"):]
        if len(stem) == 8 and stem.isdigit():
            out += p.read_text(encoding="utf-8").splitlines()
    return out


def gap_rows(d: Path) -> list[dict]:
    path = d / "archive-gaps.ndjson"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_b6_archive_before_a_trim_to_the_last_three_lines_loses_nothing(tmp_path):
    log, d = write(tmp_path / "router.log", lines(1, 10)), tmp_path / "arch"
    ra.archive(log, d, now=RUN1)  # the ExecStartPre run
    trim_in_place(log, 3)
    add(log, lines(11, 12))
    ra.archive(log, d, now=RUN2)
    assert archived(d) == lines(1, 12)
    st = ra.status(log, d)
    assert st["ran_before_last_trim"] is True and st["last_trim_seen_at"] == RUN2_ISO
    assert st["gaps"] == 0 and gap_rows(d) == []


def test_an_in_place_trim_that_shrank_the_log_loses_no_line_and_doubles_none(tmp_path):
    log, d = write(tmp_path / "router.log", lines(1, 10)), tmp_path / "arch"
    ra.archive(log, d, now=RUN1)
    add(log, lines(11, 13))  # written after the run, before the trim
    trim_in_place(log, 6)
    assert len(log.read_text(encoding="utf-8").splitlines()) < 10
    ra.archive(log, d, now=RUN2)
    assert archived(d) == lines(1, 13)
    assert ra.status(log, d)["last_trim_seen_at"] == RUN2_ISO


def test_an_in_place_trim_regrown_past_offset_is_caught_by_the_tail_check(tmp_path):
    log, d = write(tmp_path / "router.log", lines(1, 10)), tmp_path / "arch"
    ra.archive(log, d, now=RUN1)
    inode = os.stat(log).st_ino
    offset = json.loads((d / ".archive-state.json").read_text(encoding="utf-8"))["offset"]
    add(log, lines(11, 15))
    trim_in_place(log, 8)  # keeps lines 8..15: the archived tail 8, 9, 10 survives
    add(log, lines(16, 20))
    assert os.stat(log).st_ino == inode and os.stat(log).st_size >= offset
    ra.archive(log, d, now=RUN2)
    assert archived(d) == lines(1, 20)
    assert ra.status(log, d)["last_trim_seen_at"] == RUN2_ISO


def test_a_new_inode_is_a_trim_even_when_the_tail_still_matches_at_offset(tmp_path):
    log, d = write(tmp_path / "router.log", lines(1, 10)), tmp_path / "arch"
    ra.archive(log, d, now=RUN1)
    inode = os.stat(log).st_ino
    add(log, lines(11, 12))
    trim_new_inode(log, 12)  # same bytes, new file
    assert os.stat(log).st_ino != inode
    ra.archive(log, d, now=RUN2)
    assert archived(d) == lines(1, 12)
    st = ra.status(log, d)
    assert st["last_trim_seen_at"] == RUN2_ISO and st["ran_before_last_trim"] is True


def test_a_tail_that_occurs_twice_anchors_at_the_last_occurrence(tmp_path):
    x, y, z = line(30), line(31), line(32)
    first = [line(1), x, y, z, line(2), x, y, z]
    log, d = write(tmp_path / "router.log", first), tmp_path / "arch"
    ra.archive(log, d, now=RUN1)
    add(log, [line(40), line(41)])
    trim_new_inode(log, 9)  # drops line(1); the tail x, y, z now occurs twice
    ra.archive(log, d, now=RUN2)
    assert archived(d) == [*first, line(40), line(41)]
    assert gap_rows(d) == []


def test_anchor_lost_appends_only_lines_after_last_ts_and_records_one_gap(tmp_path):
    log, d = write(tmp_path / "router.log", lines(1, 5)), tmp_path / "arch"
    ra.archive(log, d, now=RUN1)
    older = line(4).replace("(1004B)", "(9004B)")  # stamped before last_ts, never archived
    write(log, [older, line(5), *lines(6, 9)])  # in place: lines 3 and 4 were cut
    ra.archive(log, d, now=RUN2)
    assert archived(d) == lines(1, 9)
    rows = gap_rows(d)
    assert len(rows) == 1 and set(rows[0]) == {"at", "reason", "gap"}
    assert rows[0]["reason"] == "anchor-lost"
    gap = [datetime.datetime.fromisoformat(v) for v in rows[0]["gap"]]
    assert gap == [datetime.datetime(2026, 10, 1, 10, 0, 5), datetime.datetime(2026, 10, 1, 10, 0, 6)]
    st = ra.status(log, d)
    assert st["gaps"] == 1 and st["ran_before_last_trim"] is False
    assert st["last_trim_seen_at"] == RUN2_ISO


def test_the_anchor_lost_gap_is_subtracted_from_router_history_coverage(tmp_path):
    log, d = write(tmp_path / "router.log", lines(1, 5)), tmp_path / "arch"
    ra.archive(log, d, now=RUN1)
    write(log, lines(20, 30))  # the whole archived tail is gone
    ra.archive(log, d, now=RUN2)
    hist = rh.load(sorted(d.glob("router-*.log")), utc_offset=datetime.timedelta(hours=-6))
    assert hist.covered("2026-10-01T16:00:01Z", "2026-10-01T16:00:05Z")
    assert not hist.covered("2026-10-01T16:00:04Z", "2026-10-01T16:00:21Z")
    assert hist.covered("2026-10-01T16:00:20Z", "2026-10-01T16:00:30Z")


def test_property_runs_before_every_trim_archive_every_line_exactly_once(tmp_path):
    rnd = random.Random(20261002)
    log, d = write(tmp_path / "router.log", []), tmp_path / "arch"
    written: list[str] = []
    for step in range(40):
        new = [line(len(written) + i, minute=0) for i in range(rnd.randint(0, 7))]
        add(log, new)
        written += new
        if rnd.random() < 0.6:
            ra.archive(log, d, now=RUN1)
        if rnd.random() < 0.3:
            ra.archive(log, d, now=RUN1)  # the ExecStartPre run, then the trim
            size = len(log.read_text(encoding="utf-8").splitlines())
            if size > 3:
                (trim_in_place if step % 2 else trim_new_inode)(log, rnd.randint(3, size))
    ra.archive(log, d, now=RUN2)
    assert archived(d) == written
    assert gap_rows(d) == []
