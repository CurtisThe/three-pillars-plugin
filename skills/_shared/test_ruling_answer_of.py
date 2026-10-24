"""Tests for ruling_file.answer_of — the one reading of "answered".

design: seat-escalate-first (Task 1.3). The hook, `review_stop.settle` and the
seat commit guard all read an operator answer through this helper: the label of
the last `- YYYY-MM-DD: answer: <label>` feedback line, ` (Recommended)` and any
` — <text>` stripped. Every fixture is a tmp git repo; no network.
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
    """A tmp git repo as cwd, so `ruling_cli` writes its answers under it."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _ruling(root) -> str:
    path = ruling_file.write(
        root, scope="demo", entry="run",
        stop={"source": "question", "signal": "decision",
              "detail": {"question": "Stop here, or fix these notes first?"}},
        key="question:decision:x", result={"outcome": "escalate"}, model="fable",
        at="2026-10-21T00:00:00Z")
    return path.stem


def _parsed(root, rid) -> dict:
    return ruling_file.parse(ruling_file.find(root, rid))


def _answer(rid, choice, text=None) -> None:
    argv = ["answer", "--id", rid, "--choice", choice]
    if text is not None:
        argv += ["--text", text]
    assert ruling_cli.main(argv) == 0


def test_no_feedback_is_no_answer(root):
    rid = _ruling(root)
    assert ruling_file.answer_of(_parsed(root, rid)) is None


def test_answer_label_strips_recommended_and_text(root, capsys):
    rid = _ruling(root)
    _answer(rid, "Fix these notes first (Recommended)", "gap")
    capsys.readouterr()
    assert ruling_file.answer_of(_parsed(root, rid)) == "Fix these notes first"


def test_last_answer_wins(root, capsys):
    rid = _ruling(root)
    _answer(rid, "Stop here")
    _answer(rid, "Fix these notes first")
    capsys.readouterr()
    assert ruling_file.answer_of(_parsed(root, rid)) == "Fix these notes first"


def test_agree_line_is_no_answer():
    assert ruling_file.answer_of({"feedback": ["- 2026-10-21: agree — x"]}) is None


def test_agree_after_an_answer_keeps_the_answer():
    feedback = ["- 2026-10-21: answer: Stop here", "- 2026-10-21: agree — x"]
    assert ruling_file.answer_of({"feedback": feedback}) == "Stop here"
