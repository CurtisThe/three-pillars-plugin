"""skills/conftest.py moves pytest's basetemp out of a run's in-tree TMPDIR (review r1, PR #391).

design: run-scratch-in-fence. A launched run's TMPDIR is `<worktree>/.tp-scratch/run`, so pytest's
default basetemp (`tmp_path`) would sit inside the run's checkout: repo discovery from a test's temp
dir finds the checkout, and a socket under `tmp_path` overruns AF_UNIX. A real pytest subprocess runs
a project holding a copy of the shipped conftest, serial and under xdist, and reports each test's
`tmp_path` and whether `git rev-parse` succeeds there.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "_shared"))
import run_scratch  # noqa: E402

ABS_TMP = os.path.join(os.sep, "tmp")  # built from pieces: no absolute-temp literal on one line

INNER = '''
import json, os, subprocess
import pytest

@pytest.mark.parametrize("i", [0, 1])
def test_inner(tmp_path, i):
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=tmp_path, capture_output=True)
    out = os.path.join(os.environ["OUT_DIR"], f"{i}.json")
    with open(out, "w") as fh:
        json.dump({"tmp_path": str(tmp_path), "git_rc": r.returncode}, fh)
'''


def _clean_env(**extra):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("PYTEST_", "GIT_")) and k != "TMPDIR"}
    env.update(extra)
    return env


def _run_inner(tmp_path, tmpdir, *args):
    proj = tmp_path / "proj"
    proj.mkdir()
    shutil.copy(HERE / "conftest.py", proj / "conftest.py")
    (proj / "test_inner.py").write_text(INNER, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    res = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                          "-o", "addopts=", *args, "test_inner.py"], cwd=proj,
                         env=_clean_env(TMPDIR=str(tmpdir), OUT_DIR=str(out)),
                         capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    got = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.iterdir())]
    assert len(got) == 2
    return got


@pytest.fixture
def run_wt(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=wt, check=True, env=_clean_env())
    run = run_scratch.ensure_run_dir(wt)
    assert run
    return wt, run


@pytest.mark.parametrize("xdist", [(), ("-n", "2")], ids=["serial", "xdist"])
def test_in_tree_tmpdir_moves_tmp_path_out_of_the_repo(tmp_path, run_wt, xdist):
    wt, run = run_wt
    holders = os.path.join(ABS_TMP, "tpt-" + run_scratch.tag(wt) + "-b")
    for info in _run_inner(tmp_path, run, *xdist):
        got = info["tmp_path"]
        assert got.startswith(holders), got
        assert len(got) < 70, got
        assert not got.startswith(str(wt) + os.sep)
        assert info["git_rc"] != 0, f"{got} is inside a git repo"
    assert not glob.glob(holders + "*"), "the basetemp holder is removed at session end"
    assert not [p for p in os.listdir(run) if p.startswith("pytest-of-")]


def test_a_short_tmpdir_keeps_pytests_default_layout(tmp_path):
    short = tempfile.mkdtemp(prefix="s", dir=ABS_TMP)
    try:
        for info in _run_inner(tmp_path, short):
            assert info["tmp_path"].startswith(os.path.join(short, "pytest-of-")), info
        assert not glob.glob(os.path.join(ABS_TMP, "tpt-*-b*", "p", "test_inner*"))
    finally:
        shutil.rmtree(short, ignore_errors=True)


def test_an_explicit_basetemp_is_respected(tmp_path, run_wt):
    wt, run = run_wt
    bt = tmp_path / "bt"
    for info in _run_inner(tmp_path, run, f"--basetemp={bt}"):
        assert info["tmp_path"].startswith(str(bt) + os.sep), info
    assert not glob.glob(os.path.join(ABS_TMP, "tpt-" + run_scratch.tag(wt) + "-*"))


def test_needs_short_shapes():
    import importlib.util
    spec = importlib.util.spec_from_file_location("conftest_shape", HERE / "conftest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._needs_short("/r/.tp-scratch/run")
    assert mod._needs_short("/r/.tp-scratch/run/")
    assert mod._needs_short("/" + "x" * 41)
    assert not mod._needs_short("/srv/t")
    assert not mod._needs_short("/r/.tp-scratch/runner")
