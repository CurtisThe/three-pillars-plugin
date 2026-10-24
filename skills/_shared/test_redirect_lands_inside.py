"""run-scratch-in-fence 1.6 -- a child started with exactly the run's env pairs keeps its temp inside.

P1 (`mktemp -d`, `tempfile`, pytest's `pytest-of-<user>` tree) and P6 (the pip cache) all resolve
under `<worktree>/.tp-scratch/run`, and the watch set gains no entry. The control shows the same
commands do leak into a scratch area when only `TMPDIR` names that area, so the check is not
vacuous. The children are real subprocesses with a fake HOME and a fake scratch area.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_command as drc  # noqa: E402
import design_run_launch_plan as lp  # noqa: E402
import run_scratch  # noqa: E402
import scratch_leftovers  # noqa: E402

MKTEMP = ["mktemp", "-d"]
MKTEMP_NAMED = ["mktemp", "-d", "-t", "slot8-XXXXXX"]  # a name the noise list does not hide
PYTHON_TEMP = [sys.executable, "-c", "import tempfile; print(tempfile.mkdtemp())"]
INNER_TEST = "def test_x(tmp_path):\n    print('PATH=' + str(tmp_path))\n"


def _launcher_pairs(wt):
    """The NAME=value words the launcher puts in the run's command, as a dict (exactly those)."""
    plan = lp.build({}, {}, False, None, str(wt), scratch=True)
    words = shlex.split(drc.window_command("foo", str(wt), extra_env=plan.extra_env))
    names = {name for name, _ in run_scratch.env_pairs(wt)}
    return dict(w.split("=", 1) for w in words if "=" in w and w.split("=", 1)[0] in names)


@pytest.fixture
def child(tmp_path):
    tmp_path = tmp_path.resolve()
    wt, home, area = tmp_path / "wt", tmp_path / "home", tmp_path / "area"
    for d in (wt, home, area):
        d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=wt, check=True)
    run = run_scratch.ensure_run_dir(wt)
    base = {"PATH": os.environ["PATH"], "HOME": str(home)}
    env = {**base, **_launcher_pairs(wt)}
    assert len(env) == len(base) + 7
    check_env = {"HOME": str(home)}
    return SimpleNamespace(wt=wt, home=home, area=area, run=run, env=env, base=base,
                           check_env=check_env, tmp=tmp_path)


def _out(cmd, env, cwd=None):
    done = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def _inside(path, run):
    return os.path.realpath(path).startswith(run + os.sep)


def _scratch(c, cmd):
    return scratch_leftovers.main([cmd, "--worktree", str(c.wt), "--slug", "s"],
                                  env=c.check_env, areas=(str(c.area),))


@pytest.mark.parametrize("cmd", [MKTEMP, MKTEMP_NAMED, PYTHON_TEMP], ids=["mktemp", "named", "tempfile"])
def test_p1_a_temp_dir_lands_in_the_run_dir(child, cmd):
    made = _out(cmd, child.env)
    assert _inside(made, child.run) and os.path.isdir(made)


def test_p1_pytest_basetemp_lands_in_the_run_dir(child):
    inner = child.tmp / "inner"
    inner.mkdir()
    (inner / "test_inner.py").write_text(INNER_TEST, encoding="utf-8")
    out = _out([sys.executable, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider",
                "-o", "addopts=", "test_inner.py"], child.env, cwd=inner)
    got = next(ln for ln in out.splitlines() if ln.startswith("PATH="))[len("PATH="):]
    assert _inside(got, child.run) and "pytest-of-" in got
    assert [p for p in os.listdir(child.run) if p.startswith("pytest-of-")]


def test_p6_the_pip_cache_is_the_run_dirs(child):
    if subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True).returncode:
        pytest.skip("pip is not installed")
    got = _out([sys.executable, "-m", "pip", "cache", "dir"], child.env)
    assert got == os.path.join(child.run, "pip") and _inside(got, child.run)


def test_the_watch_set_gains_no_entry_when_the_pairs_are_set(child):
    assert _scratch(child, "provision") == 0
    for cmd in (MKTEMP, MKTEMP_NAMED, PYTHON_TEMP):
        _out(cmd, child.env)
    assert _scratch(child, "check") == 0
    assert os.listdir(child.area) == []


def test_control_the_same_commands_leak_when_only_tmpdir_names_the_area(child, capsys):
    assert _scratch(child, "provision") == 0
    capsys.readouterr()
    leaky = {**child.base, "TMPDIR": str(child.area)}
    made = _out(MKTEMP_NAMED, leaky)
    assert os.path.dirname(made) == str(child.area)
    assert _scratch(child, "check") == 1
    assert f"scratch-leftover: {made}" in capsys.readouterr().out
