"""Example tests for boot_time (no test reads the real /proc/stat)."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import boot_time  # noqa: E402


def _stat(tmp_path, text):
    p = tmp_path / "stat"
    p.write_text(text)
    return str(p)


def test_boot_epoch_reads_btime(tmp_path):
    p = _stat(tmp_path, "cpu 1 2 3\nbtime 1700000000\nprocs 4\n")
    assert boot_time.boot_epoch(proc_stat=p) == 1700000000


def test_boot_epoch_missing_file(tmp_path):
    assert boot_time.boot_epoch(proc_stat=str(tmp_path / "nope")) is None


def test_boot_epoch_no_btime_line(tmp_path):
    assert boot_time.boot_epoch(proc_stat=_stat(tmp_path, "cpu 1\n")) is None


def test_boot_epoch_non_numeric(tmp_path):
    assert boot_time.boot_epoch(proc_stat=_stat(tmp_path, "btime abc\n")) is None


def _file(tmp_path, mtime):
    f = tmp_path / "f"
    f.write_text("x")
    os.utime(f, (mtime, mtime))
    return str(f)


def test_predates_boot_true_when_before(tmp_path):
    assert boot_time.predates_boot(_file(tmp_path, 99), boot=100) is True


def test_predates_boot_false_at_or_after(tmp_path):
    assert boot_time.predates_boot(_file(tmp_path, 100), boot=100) is False
    assert boot_time.predates_boot(_file(tmp_path, 101), boot=100) is False


def test_predates_boot_false_missing_path(tmp_path):
    assert boot_time.predates_boot(str(tmp_path / "nope"), boot=100) is False


def test_predates_boot_false_unknown_boot(tmp_path, monkeypatch):
    monkeypatch.setattr(boot_time, "boot_epoch", lambda *a, **k: None)
    assert boot_time.predates_boot(_file(tmp_path, 1)) is False
