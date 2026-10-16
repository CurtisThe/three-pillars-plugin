"""Tests for the observed_red oracle in cheap_oracle_run.py (slot repro_scaffold).

design: cheap-tier-review-prep (Task 2.3). A tmp git repo and a real pytest
subprocess: only a named test that fails on an assertion is OK, and every other
outcome drops with its own reason.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_oracle  # noqa: E402
import cheap_oracle_run as cor  # noqa: E402
import junit_verdict  # noqa: E402

_GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
_RED = "def test_x():\n    assert 1 == 2\n"


def _git(repo, *args) -> str:
    done = subprocess.run([*_GIT, "-C", str(repo), *args], capture_output=True,
                          text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "a.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-q", "-m", "first")
    return root


def _ctx(repo, tmp_path, **extra) -> dict:
    ctx = {"cwd": str(repo), "head": _git(repo, "rev-parse", "HEAD"),
           "scratch_dir": str(tmp_path / "scratch"), "timeout": 60}
    ctx.update(extra)
    return ctx


def _art(source: str, name: str = "test_x") -> dict:
    return {"source": source, "test_name": name}


def test_observed_red_registered_into_cheap_oracle():
    assert cheap_oracle.ORACLES["observed_red"] is cor.observed_red


@pytest.mark.parametrize("body", ["assert 1 == 2", 'raise AssertionError("x")'])
def test_a_named_assertion_failure_is_ok(repo, tmp_path, body):
    v = cheap_oracle.check("repro_scaffold", _art(f"def test_x():\n    {body}\n"),
                           _ctx(repo, tmp_path))
    assert v["ok"] is True and v["oracle"] == "observed_red" and v["reason"] == ""


def test_a_parametrized_named_case_is_ok(repo, tmp_path):
    src = ("import pytest\n@pytest.mark.parametrize('n', [1])\n"
           "def test_x(n):\n    assert n == 2\n")
    assert cor.observed_red(_art(src), _ctx(repo, tmp_path)) == (True, "")


@pytest.mark.parametrize("source,reason", [
    ("def test_x():\n    assert 1 == 1\n", "passes on head"),
    ("import no_such_module_zz\ndef test_x():\n    assert 1 == 2\n",
     "collection or usage error (rc 2)"),
    ("def test_x():\n    raise ValueError('boom')\n", "failed, not by an assertion"),
    ("def test_x():\n    import no_such_module_zz\n", "failed, not by an assertion"),
    ("import pytest\n@pytest.fixture\ndef fx():\n    raise RuntimeError('fx')\n"
     "def test_x(fx):\n    assert 1 == 2\n", "error, not an assertion"),
    ("def test_other():\n    assert 1 == 2\n", "named test absent"),
])
def test_every_other_outcome_drops_with_its_reason(repo, tmp_path, source, reason):
    ok, why = cor.observed_red(_art(source), _ctx(repo, tmp_path))
    assert ok is False and reason in why


def test_a_scratch_at_another_commit_drops(repo, tmp_path):
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "second")
    ok, why = cor.observed_red(_art(_RED), _ctx(repo, tmp_path, head=first))
    assert ok is False and "scratch not at head" in why


def test_argv_without_the_report_flags_drops(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(junit_verdict, "report_args", lambda report: [])
    ok, why = cor.observed_red(_art(_RED), _ctx(repo, tmp_path))
    assert ok is False and "no junit report (non-pytest runner?)" in why


def test_a_stale_report_is_never_read(repo, tmp_path, monkeypatch):
    ctx = _ctx(repo, tmp_path)
    assert cor.observed_red(_art(_RED), ctx) == (True, "")
    monkeypatch.setattr(junit_verdict, "report_args", lambda report: [])
    ok, why = cor.observed_red(_art(_RED), ctx)
    assert ok is False and "no junit report" in why


def test_a_run_that_does_not_finish_drops(repo, tmp_path):
    src = "import time\ndef test_x():\n    time.sleep(30)\n    assert 1 == 2\n"
    ok, why = cor.observed_red(_art(src), _ctx(repo, tmp_path, timeout=0.5))
    assert ok is False and "did not finish" in why


def test_the_scaffold_is_written_to_the_scratch_dir(repo, tmp_path):
    ctx = _ctx(repo, tmp_path)
    cor.observed_red(_art(_RED), ctx)
    written = Path(ctx["scratch_dir"]) / "repro_scaffold.py"
    assert "def test_x" in written.read_text(encoding="utf-8")
