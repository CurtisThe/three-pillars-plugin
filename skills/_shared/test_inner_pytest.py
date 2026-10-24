"""Tests for inner_pytest: the isolated child pytest helper.

design: local-sized-tasks
"""
from __future__ import annotations

from inner_pytest import inner_pytest

PASSING = "def test_ok(tmp_path):\n    assert tmp_path.is_dir()\n"
FAILING = "def test_bad():\n    assert False\n"


def _inner(tmp_path, body):
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / "test_ok.py").write_text(body)
    return inner


def test_passing_child_returns_zero(tmp_path):
    inner = _inner(tmp_path, PASSING)
    res = inner_pytest(inner, ["test_ok.py"])
    assert res.returncode == 0, res.stdout + res.stderr


def test_parent_ini_addopts_ignored(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -n 2\n")
    inner = _inner(tmp_path, PASSING)
    res = inner_pytest(inner, ["test_ok.py"])
    assert res.returncode == 0, res.stdout + res.stderr


def test_env_addopts_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_ADDOPTS", "--bogus-flag")
    inner = _inner(tmp_path, PASSING)
    res = inner_pytest(inner, ["test_ok.py"])
    assert res.returncode == 0, res.stdout + res.stderr


def test_basetemp_lives_outside_inner(tmp_path):
    inner = _inner(tmp_path, PASSING)
    res = inner_pytest(inner, ["test_ok.py"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert (tmp_path / "inner-basetemp").is_dir()
    assert not list(inner.rglob("*basetemp*"))


def test_failing_child_nonzero(tmp_path):
    inner = _inner(tmp_path, FAILING)
    res = inner_pytest(inner, ["test_ok.py"])
    assert res.returncode != 0
