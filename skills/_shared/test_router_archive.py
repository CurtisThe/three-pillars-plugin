"""Tests for router_archive.py: dated append, partial lines, state, lock, status, CLI.

design: cheap-tier-local-routing 1.2 (detailed-design.md §Interfaces `router_archive.py`,
§Data Flow 5-6). Every log line is built here in the real router shape (POST lines with a
`[YYYY-MM-DD HH:MM:SS]` router-local stamp), so no test parses prose it did not build
(skills/_shared/test-fragility.md, fix 2). Trim, anchor and gap cases live in
test_router_archive_trim.py. Paths always point at tmp_path, never the real tp-local state.
"""
from __future__ import annotations

import datetime
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import router_archive as ra  # noqa: E402

SCRIPT = HERE / "router_archive.py"
NOW = datetime.datetime(2026, 10, 2, 6, 0, 0, tzinfo=datetime.timezone.utc)
NOW_ISO = "2026-10-02T06:00:00Z"
STATE_KEYS = {"inode", "size", "offset", "tail", "last_ts", "last_run_at"}
STATUS_KEYS = {"last_run_at", "last_trim_seen_at", "ran_before_last_trim", "gaps"}


def line(stamp: str, n: int) -> str:
    return (f"[{stamp}] POST /v1/messages  model=qwen3.8-27b-240k  sess=9a207ac4  agent=a9ac0e2b"
            f"  effort=medium  -> local (model resident) owner=9a207ac4  ({1000 + n}B)")


def write(path: Path, lines, tail: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{x}\n" for x in lines) + tail, encoding="utf-8")
    return path


def add(path: Path, lines, tail: str = "") -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("".join(f"{x}\n" for x in lines) + tail)


def dated(d: Path) -> dict[str, list[str]]:
    """{file name: lines} for every dated `router-YYYYMMDD.log` in `d`."""
    out = {}
    for p in sorted(d.glob("router-*.log")):
        stem = p.stem[len("router-"):]
        if len(stem) == 8 and stem.isdigit():
            out[p.name] = p.read_text(encoding="utf-8").splitlines()
    return out


def archived(d: Path) -> list[str]:
    return [x for lines in dated(d).values() for x in lines]


def run_cli(*args, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          env=env, timeout=60, check=False)


def test_lines_land_in_files_dated_by_their_own_stamp_in_the_default_dir(tmp_path):
    log = tmp_path / "tp-local" / "router.log"
    lines = [line("2026-09-30 23:59:58", 1), line("2026-09-30 23:59:59", 2),
             line("2026-10-01 00:00:01", 3)]
    write(log, lines)
    out = ra.archive(env={"TP_LOCAL_LOG": str(log)}, now=NOW)
    assert out["archived"] == 3
    d = log.parent / "router-archive"
    assert dated(d) == {"router-20260930.log": lines[:2], "router-20261001.log": lines[2:]}


def test_a_partial_last_line_waits_for_its_newline(tmp_path):
    log, d = tmp_path / "router.log", tmp_path / "arch"
    first = [line("2026-10-01 10:00:01", 1), line("2026-10-01 10:00:02", 2)]
    partial = line("2026-10-01 10:00:03", 3)
    write(log, first, tail=partial[:40])
    assert ra.archive(log, d, now=NOW)["archived"] == 2
    assert archived(d) == first
    add(log, [partial[40:], line("2026-10-01 10:00:04", 4)])
    assert ra.archive(log, d, now=NOW)["archived"] == 2
    assert archived(d) == [*first, partial, line("2026-10-01 10:00:04", 4)]


def test_incremental_runs_append_each_line_once(tmp_path):
    log, d = tmp_path / "router.log", tmp_path / "arch"
    a = [line(f"2026-10-01 10:00:{i:02d}", i) for i in range(1, 6)]
    b = [line(f"2026-10-01 10:01:{i:02d}", i) for i in range(1, 4)]
    write(log, a)
    assert ra.archive(log, d, now=NOW)["archived"] == 5
    assert ra.archive(log, d, now=NOW)["archived"] == 0
    add(log, b)
    assert ra.archive(log, d, now=NOW)["archived"] == 3
    assert archived(d) == a + b


def test_the_state_file_records_inode_size_offset_tail_and_stamps(tmp_path):
    log, d = tmp_path / "router.log", tmp_path / "arch"
    lines = [line(f"2026-10-01 10:00:{i:02d}", i) for i in range(1, 6)]
    partial = "[2026-10-01 10:00:09] POST /v1/mess"
    write(log, lines, tail=partial)
    ra.archive(log, d, now=NOW)
    state = json.loads((d / ".archive-state.json").read_text(encoding="utf-8"))
    assert STATE_KEYS <= set(state)
    complete = len(("\n".join(lines) + "\n").encode("utf-8"))
    assert state["inode"] == os.stat(log).st_ino
    assert state["size"] == complete + len(partial)
    assert state["offset"] == complete
    assert state["tail"] == lines[-3:]
    assert state["last_ts"] == "2026-10-01 10:00:05"
    assert state["last_run_at"] == NOW_ISO


def test_the_state_is_replaced_from_a_tmp_file_after_the_append(tmp_path, monkeypatch):
    log, d = tmp_path / "router.log", tmp_path / "arch"
    lines = [line(f"2026-10-01 10:00:{i:02d}", i) for i in range(1, 4)]
    write(log, lines)
    seen, real = [], os.replace

    def spy(src, dst, *a, **kw):
        seen.append((Path(src).parent, Path(dst), archived(d)))
        return real(src, dst, *a, **kw)

    monkeypatch.setattr(ra.os, "replace", spy)
    ra.archive(log, d, now=NOW)
    assert [(src_dir, dst) for src_dir, dst, _ in seen] == [(d, d / ".archive-state.json")]
    assert seen[0][2] == lines  # the dated archive already held the batch


def test_no_router_log_archives_nothing_and_creates_nothing(tmp_path):
    log, d = tmp_path / "router.log", tmp_path / "arch"
    assert ra.archive(log, d, now=NOW) == {"archived": 0, "reason": "no router log"}
    assert not d.exists()


def test_a_held_lock_is_a_no_op_that_reports_locked(tmp_path):
    log, d = tmp_path / "router.log", tmp_path / "arch"
    write(log, [line("2026-10-01 10:00:01", 1)])
    d.mkdir()
    with open(d / ".archive.lock", "w", encoding="utf-8") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert ra.archive(log, d, now=NOW) == {"archived": 0, "reason": "locked"}
        proc = run_cli("archive", "--log", str(log), "--dir", str(d))
    assert proc.returncode == 0
    assert [json.loads(x) for x in proc.stdout.splitlines()] == [{"archived": 0, "reason": "locked"}]
    assert archived(d) == []
    assert ra.archive(log, d, now=NOW)["archived"] == 1  # released: the next run proceeds


def test_snapshots_in_the_archive_dir_are_never_written_or_deleted(tmp_path):
    log, d = tmp_path / "router.log", tmp_path / "arch"
    snap = write(d / "router-20261001T1612.log", [line("2026-10-01 09:00:00", 0)])
    before = snap.read_bytes()
    write(log, [line("2026-10-01 16:12:00", 1), line("2026-10-01 16:13:00", 2)])
    ra.archive(log, d, now=NOW)
    add(log, [line("2026-10-01 16:14:00", 3)])
    ra.archive(log, d, now=NOW)
    assert snap.read_bytes() == before
    assert sorted(p.name for p in d.glob("router-*.log")) == ["router-20261001.log",
                                                             "router-20261001T1612.log"]


def test_status_before_any_run_reports_nothing_seen(tmp_path):
    out = ra.status(tmp_path / "router.log", tmp_path / "arch")
    assert out == {"last_run_at": None, "last_trim_seen_at": None, "ran_before_last_trim": False,
                   "gaps": 0}


def test_status_after_a_run_without_a_trim(tmp_path):
    log, d = tmp_path / "router.log", tmp_path / "arch"
    write(log, [line("2026-10-01 10:00:01", 1)])
    ra.archive(log, d, now=NOW)
    out = ra.status(log, d)
    assert set(out) == STATUS_KEYS
    assert out["last_run_at"] == NOW_ISO
    assert out["last_trim_seen_at"] is None and out["ran_before_last_trim"] is False
    assert out["gaps"] == 0


def test_cli_prints_one_json_line_and_exits_zero(tmp_path):
    log, d = tmp_path / "router.log", tmp_path / "arch"
    missing = run_cli("archive", "--log", str(log), "--dir", str(d))
    assert missing.returncode == 0
    assert [json.loads(x) for x in missing.stdout.splitlines()] == [
        {"archived": 0, "reason": "no router log"}]
    write(log, [line("2026-10-01 10:00:01", 1), line("2026-10-01 10:00:02", 2)])
    done = run_cli("archive", "--log", str(log), "--dir", str(d))
    assert done.returncode == 0
    rows = [json.loads(x) for x in done.stdout.splitlines()]
    assert len(rows) == 1 and rows[0]["archived"] == 2
    st = run_cli("status", "--log", str(log), "--dir", str(d))
    assert st.returncode == 0
    rows = [json.loads(x) for x in st.stdout.splitlines()]
    assert len(rows) == 1 and set(rows[0]) == STATUS_KEYS and rows[0]["last_run_at"]


def test_cli_defaults_follow_the_router_log_env(tmp_path):
    log = write(tmp_path / "state" / "router.log", [line("2026-10-01 10:00:01", 1)])
    env = {**os.environ, "TP_LOCAL_LOG": str(log)}
    proc = run_cli("archive", env=env)
    assert proc.returncode == 0 and json.loads(proc.stdout)["archived"] == 1
    assert archived(log.parent / "router-archive") == [line("2026-10-01 10:00:01", 1)]
    assert json.loads(run_cli("status", env=env).stdout)["gaps"] == 0
