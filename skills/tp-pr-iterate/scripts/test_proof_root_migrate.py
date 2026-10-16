"""test_proof_root_migrate.py — one-time legacy migration (review-proof-out-of-tree 1.2).

Every design Behavior-2 case: an in-tree `.three-pillars/review-proof` (a real dir,
or a symlink to one, as PR #48 left it) moves to the out-of-tree root when that root
is absent. Nothing is ever deleted except the staging dir on failure, the legacy
real dir once its copy is in place, and the legacy symlink itself. Any failure falls
back to the legacy root for that call; the next call retries.
"""
from __future__ import annotations

import errno
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import proof_root  # noqa: E402
from proof_root_itest import LEGACY, SUB, linked  # noqa: E402

STATE = "iterate-state.v1.json"


def _legacy_dir(wt: Path, text="state-1") -> Path:
    legacy = wt / LEGACY
    (legacy / "rounds" / "9" / "r1").mkdir(parents=True)
    (legacy / STATE).write_text(text, encoding="utf-8")
    (legacy / "rounds" / "9" / "r1" / "angles.json").write_text("m", encoding="utf-8")
    return legacy


def _no_staging(new: Path) -> bool:
    return not [p for p in new.parent.iterdir() if ".migrating-" in p.name] \
        if new.parent.exists() else True


def test_legacy_absent_is_a_silent_no_op(tmp_path):
    wt, new, err = tmp_path / "wt", tmp_path / "gd" / "root", io.StringIO()
    wt.mkdir()
    assert proof_root.migrate_legacy(wt, new, err=err) == new
    assert not new.exists() and err.getvalue() == ""


def test_legacy_that_is_the_new_root_is_a_no_op(tmp_path):
    wt, err = tmp_path / "wt", io.StringIO()
    legacy = _legacy_dir(wt)
    assert proof_root.migrate_legacy(wt, wt / LEGACY, err=err) == wt / LEGACY
    assert (legacy / STATE).read_text(encoding="utf-8") == "state-1"
    assert err.getvalue() == ""


def test_new_root_exists_leaves_both_and_notices_once(tmp_path):
    wt, new, err = tmp_path / "wt", tmp_path / "gd" / "root", io.StringIO()
    legacy = _legacy_dir(wt)
    new.mkdir(parents=True)
    (new / STATE).write_text("new", encoding="utf-8")
    assert proof_root.migrate_legacy(wt, new, err=err) == new
    assert (legacy / STATE).read_text(encoding="utf-8") == "state-1"
    assert (new / STATE).read_text(encoding="utf-8") == "new"
    assert err.getvalue().count("\n") == 1 and "proof_root" in err.getvalue()


def test_real_dir_moves_by_rename(tmp_path):
    wt, new = tmp_path / "wt", tmp_path / "gd" / "three-pillars" / "root"
    _legacy_dir(wt)
    assert proof_root.migrate_legacy(wt, new, err=io.StringIO()) == new
    assert (new / STATE).read_text(encoding="utf-8") == "state-1"
    assert (new / "rounds" / "9" / "r1" / "angles.json").is_file()
    assert not os.path.lexists(wt / LEGACY)


def test_real_dir_cross_filesystem_is_staged_then_renamed(tmp_path, monkeypatch):
    wt, new = tmp_path / "wt", tmp_path / "gd" / "root"
    _legacy_dir(wt)
    real_rename, calls = os.rename, []

    def rename(src, dst):
        calls.append((src, dst))
        if len(calls) == 1:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real_rename(src, dst)

    monkeypatch.setattr(os, "rename", rename)
    assert proof_root.migrate_legacy(wt, new, err=io.StringIO()) == new
    assert len(calls) == 2 and ".migrating-" in str(calls[1][0])
    assert (new / STATE).read_text(encoding="utf-8") == "state-1"
    assert not os.path.lexists(wt / LEGACY) and _no_staging(new)


def test_symlink_copies_the_target_unlinks_the_link_keeps_the_target(tmp_path):
    wt, new = tmp_path / "wt", tmp_path / "gd" / "root"
    shared = tmp_path / "shared-proof"
    shared.mkdir()
    (shared / STATE).write_text("shared", encoding="utf-8")
    (wt / ".three-pillars").mkdir(parents=True)
    os.symlink(os.path.relpath(shared, wt / ".three-pillars"), wt / LEGACY)
    assert proof_root.migrate_legacy(wt, new, err=io.StringIO()) == new
    assert (new / STATE).read_text(encoding="utf-8") == "shared"
    assert not os.path.lexists(wt / LEGACY)
    assert (shared / STATE).read_text(encoding="utf-8") == "shared"
    assert not new.is_symlink() and _no_staging(new)


def test_dangling_symlink_is_left_with_a_notice(tmp_path):
    wt, new, err = tmp_path / "wt", tmp_path / "gd" / "root", io.StringIO()
    (wt / ".three-pillars").mkdir(parents=True)
    os.symlink(str(tmp_path / "gone"), wt / LEGACY)
    assert proof_root.migrate_legacy(wt, new, err=err) == new
    assert os.path.islink(wt / LEGACY) and not new.exists()
    assert "dangling" in err.getvalue()


def test_rename_failure_falls_back_to_legacy_then_retries(tmp_path, monkeypatch):
    wt, new, err = tmp_path / "wt", tmp_path / "gd" / "root", io.StringIO()
    legacy = _legacy_dir(wt)

    def denied(src, dst):
        raise OSError(errno.EACCES, "Permission denied")

    with monkeypatch.context() as m:
        m.setattr(os, "rename", denied)
        assert proof_root.migrate_legacy(wt, new, err=err) == legacy
    assert not new.exists() and _no_staging(new)
    assert (legacy / STATE).read_text(encoding="utf-8") == "state-1"
    assert "proof_root" in err.getvalue()
    assert proof_root.migrate_legacy(wt, new, err=io.StringIO()) == new
    assert (new / STATE).read_text(encoding="utf-8") == "state-1"


def test_copy_failure_removes_only_the_staging_dir(tmp_path, monkeypatch):
    wt, new, err = tmp_path / "wt", tmp_path / "gd" / "root", io.StringIO()
    legacy = _legacy_dir(wt)
    def half_copy(src, dst, **_kw):  # a copy that dies part-way through
        Path(dst).mkdir()
        (Path(dst) / STATE).write_text("partial", encoding="utf-8")
        raise OSError(errno.ENOSPC, "No space left on device")

    def xdev(src, dst):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    with monkeypatch.context() as m:
        m.setattr(os, "rename", xdev)
        m.setattr(shutil, "copytree", half_copy)
        assert proof_root.migrate_legacy(wt, new, err=err) == legacy
    assert not new.exists() and _no_staging(new)
    assert (legacy / STATE).read_text(encoding="utf-8") == "state-1"
    assert "proof_root" in err.getvalue()


def test_second_call_is_a_silent_no_op(tmp_path):
    wt, new = tmp_path / "wt", tmp_path / "gd" / "root"
    _legacy_dir(wt)
    proof_root.migrate_legacy(wt, new, err=io.StringIO())
    err = io.StringIO()
    assert proof_root.migrate_legacy(wt, new, err=err) == new
    assert err.getvalue() == "" and (new / STATE).read_text(encoding="utf-8") == "state-1"


def test_default_proof_root_resolves_then_migrates(tmp_path, monkeypatch):
    monkeypatch.delenv(proof_root.ENV_VAR, raising=False)
    main, wt = linked(tmp_path)
    _legacy_dir(wt)
    got = proof_root.default_proof_root(wt)
    assert got == (main / ".git" / "worktrees" / "wt" / SUB).resolve()
    assert (got / STATE).read_text(encoding="utf-8") == "state-1"
    assert not os.path.lexists(wt / LEGACY)


def test_cli_migrates_by_default(tmp_path):
    main, wt = linked(tmp_path)
    _legacy_dir(wt)
    env = dict(os.environ)
    env.pop(proof_root.ENV_VAR, None)
    p = subprocess.run([sys.executable, str(HERE / "proof_root.py")], cwd=str(wt),
                       capture_output=True, text=True, env=env, check=False)
    assert p.returncode == 0, p.stderr
    assert (Path(p.stdout.strip()) / STATE).read_text(encoding="utf-8") == "state-1"
    assert not os.path.lexists(wt / LEGACY)
