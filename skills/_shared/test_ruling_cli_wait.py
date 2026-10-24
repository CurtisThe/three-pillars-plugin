"""Tests for `ruling_cli.py wait --id` — read-only poll for an operator answer.

design: fleet-seat-drive-gaps (Task 1.2). Fixtures are tmp git repos; the sleep
and clock seams are monkeypatched so no test really waits.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ruling_cli  # noqa: E402
import ruling_file  # noqa: E402


@pytest.fixture
def root(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True,
                   capture_output=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _ruling(root) -> str:
    path = ruling_file.write(
        root, scope="demo", entry="run",
        stop={"source": "question", "signal": "decision",
              "detail": {"question": "Stop here, or fix these notes first?"}},
        key="question:decision:x", result={"outcome": "escalate"},
        model="fable", at="2026-10-21T00:00:00Z")
    return path.stem


def _bytes(root, rid) -> bytes:
    return ruling_file.find(root, rid).read_bytes()


def _answer(rid, choice, text=None) -> None:
    argv = ["answer", "--id", rid, "--choice", choice]
    if text is not None:
        argv += ["--text", text]
    assert ruling_cli.main(argv) == 0


def test_answer_before_wait(root, capsys):
    rid = _ruling(root)
    _answer(rid, "keep-going")
    capsys.readouterr()
    before = _bytes(root, rid)
    assert ruling_cli.main(["wait", "--id", rid]) == 0
    assert capsys.readouterr().out.splitlines() == ["keep-going"]
    assert _bytes(root, rid) == before


def test_answer_with_text_prints_two_lines(root, capsys):
    rid = _ruling(root)
    _answer(rid, "answer-in-text", "use the second hunk")
    capsys.readouterr()
    before = _bytes(root, rid)
    assert ruling_cli.main(["wait", "--id", rid]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "answer-in-text", "use the second hunk"]
    assert _bytes(root, rid) == before


def test_answer_during_wait(root, capsys, monkeypatch):
    rid = _ruling(root)
    calls = []

    def fake_sleep(_s):
        calls.append(1)
        if len(calls) == 1:
            _answer(rid, "keep-going")

    monkeypatch.setattr(ruling_cli, "_sleep", fake_sleep)
    monkeypatch.setattr(ruling_cli, "_clock", lambda: 0.0)
    before = _bytes(root, rid)
    assert ruling_cli.main(["wait", "--id", rid]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "keep-going"
    assert calls
    assert _bytes(root, rid) != before  # only the answer call wrote


def test_unknown_id_exits_2(root, capsys):
    assert ruling_cli.main(["wait", "--id", "nope"]) == 2
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and err[0].startswith("ruling-cli:")


def test_timeout_zero_exits_3(root, capsys):
    rid = _ruling(root)
    before = _bytes(root, rid)
    assert ruling_cli.main(["wait", "--id", rid, "--timeout", "0"]) == 3
    assert capsys.readouterr().out.splitlines() == [
        f"awaiting-operator: ruling {rid} (no answer after 0s)"]
    assert _bytes(root, rid) == before
