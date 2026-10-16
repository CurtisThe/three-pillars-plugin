"""Tests for scratch_reap.py — the scratch-root sweep.

scratch-reaper task 1.1. Every test builds a temp root and ages entries with
`os.utime`, then asserts which names the sweep removed and which it kept. The
allowlist is the framework's own names only (`tp-angle-*`, `slotrel-*`,
`vfy.*`, and a ci-local stage root: `c` + 3 alphanumerics that is a real
directory whose children are all stage dirs / stage logs, or empty); foreign
names, non-stage-shaped `c`+3 names, and roots with a recently written child
are kept. Symlinks are unlinked, never followed. Fail-open: one stderr line,
exit 0.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import scratch_reap as sr  # noqa: E402

OLD_S = 48 * 3600  # comfortably past the default 24 h floor
FRESH_S = 0


def _age(path: Path, age_s: int) -> None:
    """Set mtime (and atime) `age_s` seconds in the past; never follow a symlink."""
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp), follow_symlinks=False)


def _age_tree(root: Path, age_s: int) -> None:
    """Age every entry under `root` (children first so the parent's mtime sticks)."""
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and not entry.is_symlink():
            _age_tree(entry, age_s)
        _age(entry, age_s)
    _age(root, age_s)


def _mkdir(root: Path, name: str, children: dict[str, str | None] | None = None) -> Path:
    """Create `root/name` and any children (`None` value = dir, str = file body)."""
    d = root / name
    d.mkdir(parents=True)
    for child, body in (children or {}).items():
        if body is None:
            (d / child).mkdir()
        else:
            (d / child).write_text(body, encoding="utf-8")
    return d


def _stage_root(root: Path, name: str) -> Path:
    """A ci-local stage root: the real layout of a killed run."""
    return _mkdir(root, name, {
        "a": None,
        "b": None,
        "0-pytest.log": "log\n",
        "1-selftest.log": "log\n",
    })


def _names(root: Path) -> set[str]:
    return {p.name for p in root.iterdir()}


REMOVED = ["tp-angle-x-abc", "slotrel-1", "vfy.q1", "c9Z3", "cAb1", "cQ7z"]
KEPT = [
    "tp-angle-new", "notes.txt", "tmpabc", "pytest-of-u", "c12", "cabcd",
    "core", "code", "cfg1", "tp-angle-live",
    # names that merely CONTAIN an allowlisted pattern — the whole-name match
    # keeps every one of them
    "keep-tp-angle-notes.txt", "xslotrel-1", "my-vfy.q1",
    # a stage-shaped NAME carried by a symlink, plus the real dir it points at
    "cLnk", "stage-target",
]


def _populate(root: Path) -> None:
    """Build the fixture root: every name aged OLD unless stated fresh."""
    _mkdir(root, "tp-angle-x-abc", {"x": "x\n"})
    _mkdir(root, "slotrel-1", {"f": "f\n"})
    _mkdir(root, "vfy.q1")
    _stage_root(root, "c9Z3")
    _mkdir(root, "cAb1")  # empty stage-shaped
    _stage_root(root, "cQ7z")
    _mkdir(root, "tp-angle-new", {"x": "x\n"})
    (root / "notes.txt").write_text("mine\n", encoding="utf-8")
    _mkdir(root, "tmpabc", {"f": "f\n"})
    _mkdir(root, "pytest-of-u", {"pytest-1": None})
    _mkdir(root, "c12", {"a": None})
    _mkdir(root, "cabcd", {"a": None})
    _mkdir(root, "core", {"main.c": "int main(){return 0;}\n"})
    (root / "code").write_text("not a dir\n", encoding="utf-8")
    _mkdir(root, "cfg1", {"src": None})
    _mkdir(root, "tp-angle-live", {"work": "written now\n"})
    (root / "keep-tp-angle-notes.txt").write_text("mine\n", encoding="utf-8")
    _mkdir(root, "xslotrel-1", {"f": "f\n"})
    (root / "my-vfy.q1").write_text("mine\n", encoding="utf-8")
    _mkdir(root, "stage-target")
    (root / "cLnk").symlink_to(root / "stage-target", target_is_directory=True)
    _age_tree(root, OLD_S)
    _age(root / "tp-angle-new", FRESH_S)
    _age(root / "tp-angle-live" / "work", FRESH_S)


def test_old_allowlisted_entries_removed_fresh_and_foreign_kept(tmp_path, capsys):
    _populate(tmp_path)
    removed = sr.reap(tmp_path, 24, False)
    assert set(removed) == set(REMOVED), f"removed={sorted(removed)} expected={sorted(REMOVED)}"
    assert _names(tmp_path) == set(KEPT), f"left={sorted(_names(tmp_path))} expected={sorted(KEPT)}"
    for name in KEPT:
        assert (tmp_path / name).exists(), name
    out = capsys.readouterr().out
    for name in REMOVED:
        assert name in out


def test_stage_shaped_c3_dirs_removed(tmp_path):
    _populate(tmp_path)
    sr.reap(tmp_path, 24, False)
    assert (tmp_path / "cAb1").exists() is False
    assert (tmp_path / "cQ7z").exists() is False


def test_not_stage_shaped_c3_names_kept(tmp_path):
    _populate(tmp_path)
    sr.reap(tmp_path, 24, False)
    for name in ("c12", "cabcd", "core", "code", "cfg1"):
        assert (tmp_path / name).exists(), name


def test_root_with_fresh_child_kept(tmp_path):
    _populate(tmp_path)
    sr.reap(tmp_path, 24, False)
    assert (tmp_path / "tp-angle-live").is_dir()


def test_matching_symlink_unlinked_target_intact(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep\n", encoding="utf-8")
    root = tmp_path / "scratch"
    root.mkdir()
    link = root / "slotrel-link"
    link.symlink_to(outside, target_is_directory=True)
    _age(link, OLD_S)
    removed = sr.reap(root, 24, False)
    assert removed == ["slotrel-link"]
    assert not link.exists()
    assert not link.is_symlink()
    assert outside.is_dir()
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep\n"


def test_dry_run_lists_but_removes_nothing(tmp_path, capsys):
    _populate(tmp_path)
    removed = sr.reap(tmp_path, 24, True)
    assert set(removed) == set(REMOVED)
    assert _names(tmp_path) == set(KEPT) | set(REMOVED)
    out = capsys.readouterr().out
    for name in REMOVED:
        assert name in out


def test_hours_flag_ages_out_a_2_hour_entry(tmp_path):
    root = tmp_path / "scratch"
    root.mkdir()
    two_h = _mkdir(root, "tp-angle-old", {"x": "x\n"})
    _age_tree(two_h, 2 * 3600)
    assert sr.reap(root, 24, False) == []
    assert two_h.is_dir()
    assert sr.reap(root, 1, False) == ["tp-angle-old"]
    assert not two_h.exists()


def test_missing_root_one_stderr_line_exit_zero(capsys):
    missing = "/definitely/not/a/root-tp-scratch-reap"
    assert sr.main(["--root", missing]) == 0
    captured = capsys.readouterr()
    lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("scratch_reap:")


def test_bad_flags_exit_zero(tmp_path, capsys):
    assert sr.main(["--nonsense"]) == 0
    assert sr.main(["--root", str(tmp_path), "--hours", "abc"]) == 0
    assert sr.main(["--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out.count("\n") >= 1
