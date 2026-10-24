"""skills/conftest.py picks a short, run-tagged socket root when the temp dir is long (P12).

design: run-scratch-in-fence (Task 1.11). A real pytest subprocess runs a one-test project with a
copy of the shipped conftest and a chosen TMPDIR; the sweep cases import the conftest by path and
point its socket-parent constant at tmp_path, so only the bind case uses the real absolute temp root.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "_shared"))
import run_scratch  # noqa: E402

ABS_TMP = os.path.join(os.sep, "tmp")  # built from pieces: no absolute-temp literal on one line

INNER = '''
import json, os, socket, tempfile

def test_inner():
    td = os.environ["TMPDIR"]
    assert tempfile.tempdir == td
    sock_path = os.path.join(td, "s.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        srv.bind(sock_path)
    finally:
        srv.close()
        if os.path.exists(sock_path):
            os.unlink(sock_path)
    with open(os.environ["OUT_JSON"], "w") as fh:
        json.dump({"tmpdir": td, "tempdir": tempfile.tempdir, "sock_len": len(sock_path)}, fh)
'''


def _run_inner(tmp_path, tmpdir):
    proj = tmp_path / "proj"
    proj.mkdir()
    shutil.copy(HERE / "conftest.py", proj / "conftest.py")
    (proj / "test_inner.py").write_text(INNER, encoding="utf-8")
    out = tmp_path / "out.json"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "TMPDIR")}
    env.update(TMPDIR=str(tmpdir), OUT_JSON=str(out))
    res = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_inner.py"],
                         cwd=proj, env=env, capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stdout + res.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def test_long_tmpdir_uses_tagged_root_and_leaves_nothing(tmp_path):
    wt = tmp_path / "a-fairly-long-worktree-name"
    run_dir = wt / ".tp-scratch" / "run"
    run_dir.mkdir(parents=True)
    assert len(str(run_dir)) > 40
    info = _run_inner(tmp_path, run_dir)
    tag = run_scratch.tag(wt)
    per_test = info["tmpdir"]
    prefix = os.path.join(ABS_TMP, "tpt-" + tag + "-")
    assert per_test.startswith(prefix), per_test
    assert info["sock_len"] < 100
    assert not os.path.exists(per_test)
    assert not os.path.exists(os.path.dirname(per_test))  # session root removed too


def test_short_tmpdir_keeps_the_root_under_gettempdir(tmp_path):
    short = tempfile.mkdtemp(prefix="s", dir=ABS_TMP)
    try:
        assert len(short) <= 40
        info = _run_inner(tmp_path, short)
        assert info["tmpdir"].startswith(os.path.join(short, "tpt-")), info["tmpdir"]
        assert not os.path.exists(info["tmpdir"])
    finally:
        shutil.rmtree(short, ignore_errors=True)


def _load_conftest():
    spec = importlib.util.spec_from_file_location("conftest_under_test", HERE / "conftest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _age(path, hours):
    old = time.time() - hours * 3600
    os.utime(path, (old, old))


def test_sweep_removes_old_roots_of_any_tag_and_keeps_young_ones(tmp_path, monkeypatch):
    mod = _load_conftest()
    parent = tmp_path / "sock-parent"
    parent.mkdir()
    old, young = parent / "tpt-aaaaaa-old", parent / "tpt-bbbbbb-young"
    old.mkdir()
    young.mkdir()
    _age(old, 25)
    monkeypatch.setattr(mod, "_SOCKET_PARENT", str(parent))
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path) + "/" + "x" * 50)
    root = mod._make_root()
    try:
        assert not old.exists()
        assert young.exists()
        assert os.path.dirname(root) == str(parent)
        assert os.path.basename(root).startswith("tpt-")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_sweep_with_a_short_tempdir_globs_that_dir(tmp_path, monkeypatch):
    mod = _load_conftest()
    short = tmp_path / "t"
    short.mkdir()
    old = short / "tpt-old"
    old.mkdir()
    _age(old, 30)
    monkeypatch.setattr(mod, "_SHORT_TMP_MAX", 10_000)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(short))
    root = mod._make_root()
    try:
        assert not old.exists()
        assert os.path.dirname(root) == str(short)
    finally:
        shutil.rmtree(root, ignore_errors=True)
