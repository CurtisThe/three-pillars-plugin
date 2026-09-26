"""Tests for argv_runner — the shared argv-list subprocess runner.

design: audit-pass-does-not-bind (Tasks 1.1, 1.2)

`run_argv` runs an argv list (never a shell) with a timeout and returns a
`RunResult(rc, stdout, tail)`; `rc is None` means the run itself failed
(timeout / OSError). `tail` is capped evidence; `output` keeps the full text.
"""

from __future__ import annotations

import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

import argv_runner
from argv_runner import OUTPUT_CAP, RunResult, run_argv, tail


class _Runner:
    """Records calls; returns a CompletedProcess or raises the given exception."""

    def __init__(self, rc=0, stdout="", stderr="", exc=None):
        self.rc, self.stdout, self.stderr, self.exc = rc, stdout, stderr, exc
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        if self.exc is not None:
            raise self.exc
        return subprocess.CompletedProcess(argv, self.rc, self.stdout, self.stderr)


def test_output_cap_is_500():
    assert OUTPUT_CAP == 500


def test_run_argv_returns_run_result(tmp_path):
    runner = _Runner(rc=3, stdout="out\n", stderr="err\n")
    r = run_argv(["tool", "--flag"], cwd=tmp_path, timeout=7, runner=runner)
    assert isinstance(r, RunResult)
    assert (r.rc, r.stdout) == (3, "out\n")
    assert "out" in r.tail and "err" in r.tail
    argv, kw = runner.calls[0]
    assert argv == ["tool", "--flag"]
    assert kw["cwd"] == str(tmp_path) and kw["timeout"] == 7
    assert kw["capture_output"] is True and kw["text"] is True


def test_output_keeps_full_stdout_and_stderr(tmp_path):
    big = "a" * 3000
    r = run_argv(["t"], cwd=tmp_path, timeout=1, runner=_Runner(stdout=big, stderr="E" * 900))
    assert big in r.output and "E" * 900 in r.output
    assert len(r.tail) == OUTPUT_CAP and r.output.endswith(r.tail)


def test_tail_is_capped(tmp_path):
    r = run_argv(["t"], cwd=tmp_path, timeout=1, runner=_Runner(stdout="x" * 2000))
    assert len(r.tail) <= OUTPUT_CAP
    assert len(tail("y" * 5000)) == OUTPUT_CAP


def test_tail_joins_non_empty_parts():
    # empty parts add nothing: the same evidence as passing only the non-empty ones, in order
    joined = tail("a", None, "", "b")
    assert joined == tail("a", "b") and joined.index("a") < joined.index("b")


def test_timeout_gives_rc_none_with_reason(tmp_path):
    exc = subprocess.TimeoutExpired(["t"], 4, output="partial-out", stderr="partial-err")
    r = run_argv(["t"], cwd=tmp_path, timeout=4, runner=_Runner(exc=exc))
    assert r.rc is None and r.stdout == ""
    assert "partial-out" in r.tail  # the partial output is kept as evidence
    assert "4" in re.findall(r"\d+", r.tail)  # ... beside the timeout that stopped it


def test_oserror_gives_rc_none_with_reason(tmp_path):
    r = run_argv(["nope"], cwd=tmp_path, timeout=1,
                 runner=_Runner(exc=FileNotFoundError("no such tool")))
    assert r.rc is None and r.stdout == ""
    assert "no such tool" in r.tail  # the OSError's own detail is the evidence


@pytest.mark.parametrize("argv", ["echo hi", ("echo", "hi"), None])
def test_non_list_argv_raises_type_error(tmp_path, argv):
    runner = _Runner()
    with pytest.raises(TypeError):
        run_argv(argv, cwd=tmp_path, timeout=1, runner=runner)
    assert runner.calls == []


def test_runner_never_receives_shell_true(tmp_path):
    runner = _Runner()
    run_argv(["t"], cwd=tmp_path, timeout=1, runner=runner)
    run_argv(["t"], cwd=tmp_path, timeout=1, env={"A": "1"}, runner=runner)
    for _, kw in runner.calls:
        assert kw.get("shell") in (None, False)


def test_env_forwarded_only_when_set(tmp_path):
    runner = _Runner()
    run_argv(["t"], cwd=tmp_path, timeout=1, runner=runner)
    assert "env" not in runner.calls[0][1]
    run_argv(["t"], cwd=tmp_path, timeout=1, env={"TMPDIR": "/x"}, runner=runner)
    assert runner.calls[1][1]["env"] == {"TMPDIR": "/x"}


def test_fake_without_env_parameter_works_when_env_none(tmp_path):
    def fake(argv, *, cwd, capture_output, text, timeout):
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    assert run_argv(["t"], cwd=tmp_path, timeout=1, runner=fake).rc == 0


def test_real_subprocess_round_trip(tmp_path):
    r = argv_runner.run_argv([sys.executable, "-c", "print('hello')"],
                             cwd=tmp_path, timeout=30)
    assert r.rc == 0 and r.stdout.strip() == "hello"


# ---------- Task 1.2: reproduce.py delegates to argv_runner ----------

_REPRO_DIR = Path(__file__).resolve().parents[1] / "tp-pr-iterate" / "scripts"


@pytest.fixture
def reproduce(monkeypatch):
    monkeypatch.syspath_prepend(str(_REPRO_DIR))
    return importlib.import_module("reproduce")


class _Spy:
    """Stands in for `run_argv`; records calls and returns a fixed RunResult."""

    def __init__(self, result):
        self.result, self.calls = result, []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        return self.result


def _cmd_finding(argv, expect):
    return {"source": "code-review", "file": "a.py", "line_range": [1, 1],
            "summary": "s", "verdict": "structural", "class": "P", "blocking": True,
            "reproducer": {"kind": "command", "argv": argv, "expect": expect}}


def test_reproduce_delegates(reproduce, monkeypatch, tmp_path):
    assert reproduce.OUTPUT_CAP is argv_runner.OUTPUT_CAP
    assert reproduce._tail is argv_runner.tail
    spy = _Spy(RunResult(1, "so", "tail-text", "full"))
    monkeypatch.setattr(reproduce, "run_argv", spy)
    fake = _Runner()
    assert reproduce._run(fake, ["a", "b"], tmp_path, 5) == (1, "so", "tail-text")
    argv, kw = spy.calls[0]
    assert argv == ["a", "b"]
    assert kw == {"cwd": tmp_path, "timeout": 5, "runner": fake}


def test_reproduce_command_path_goes_through_run_argv(reproduce, monkeypatch, tmp_path):
    spy = _Spy(RunResult(0, "all ok\n", "all ok", "all ok\n"))
    monkeypatch.setattr(reproduce, "run_argv", spy)
    finding = _cmd_finding(["tool", "--x"], {"exit": 0, "stdout_contains": "ok"})
    out, _ = reproduce.run_reproducers([finding], cwd=tmp_path, scratch_dir=tmp_path / "s",
                                       runner=_Runner())
    assert spy.calls[0][0] == ["tool", "--x"]
    assert out[0]["downgrade"]["reason"] == "not-reproduced"


@pytest.mark.parametrize("expect,reproduced", [({"exit": 0, "stdout_contains": "ok"}, False),
                                               ({"exit": 1}, True)])
def test_reproduce_command_reproducer_real_run(reproduce, tmp_path, expect, reproduced):
    """Assumption 2: a non-pytest argv reproducer runs through run_argv for real."""
    finding = _cmd_finding([sys.executable, "-c", "print('ok')"], expect)
    out, downgrades = reproduce.run_reproducers([finding], cwd=tmp_path,
                                                scratch_dir=tmp_path / "s", timeout=30)
    if reproduced:
        assert out[0]["blocking"] is True and downgrades == []
    else:
        assert out[0]["blocking"] is False and "ok" in out[0]["downgrade"]["output"]
