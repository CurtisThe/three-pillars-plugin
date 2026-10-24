"""Tests for `ruling_cli.py ask` — write a run-asked ruling, print wait handles.

design: run-no-cards-hook (Task 1.5).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ruling_cli  # noqa: E402

ASK = ["ask", "--scope", "demo", "--question", "Keep the claim wording?",
       "--option", "keep=Keep the claim as written",
       "--option", "reword=Reword the claim", "--recommended", "keep"]


@pytest.fixture
def root(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True,
                   capture_output=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _files(root):
    d = root / "three-pillars-docs" / "escalations" / "rulings"
    return list(d.glob("*")) if d.exists() else []


def _show(rid, capsys):
    capsys.readouterr()
    assert ruling_cli.main(["show", "--id", rid]) == 0
    return json.loads(capsys.readouterr().out)


def test_ask_prints_handles_and_writes_ruling(root, capsys):
    assert ruling_cli.main(ASK) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    head = json.loads(lines[0])
    rid = head["id"]
    assert "path" in head
    assert lines[1] == f"awaiting-operator: ruling {rid}"
    assert f"ruling_cli.py answer --id {rid} --choice" in lines[2]
    assert len(_files(root)) == 1
    shown = _show(rid, capsys)
    assert shown["front"]["outcome"] == "escalate"
    assert shown["front"]["model"] == "run-ask"
    assert shown["front"]["kind"] == "decision"
    rec = [o for o in shown["ruling"]["ruling"]["options"]
           if o.get("recommended")]
    assert len(rec) == 1 and rec[0]["label"] == "keep"


def test_ask_kind(root, capsys):
    assert ruling_cli.main(ASK + ["--kind", "classifier-denial"]) == 0
    head = json.loads(capsys.readouterr().out.splitlines()[0])
    assert head["kind"] == "classifier-denial"
    assert _show(head["id"], capsys)["front"]["kind"] == "classifier-denial"


def _swap(argv, flag, value):
    out = list(argv)
    out[out.index(flag) + 1] = value
    return out


REFUSALS = {
    "one-option": ["ask", "--scope", "demo", "--question", "Q?",
                   "--option", "keep=Keep", "--recommended", "keep"],
    "five-options": ["ask", "--scope", "demo", "--question", "Q?",
                     *[x for n in "abcde" for x in ("--option", f"{n}=D{n}")],
                     "--recommended", "a"],
    "no-recommended": ASK[:-2],
    "bad-recommended": _swap(ASK, "--recommended", "nope"),
    "duplicate-label": ["ask", "--scope", "demo", "--question", "Q?",
                        "--option", "a=One", "--option", "a=Two",
                        "--recommended", "a"],
    "no-equals": ["ask", "--scope", "demo", "--question", "Q?",
                  "--option", "keep", "--option", "b=B",
                  "--recommended", "b"],
    "bad-kind": ASK + ["--kind", "nope"],
    "bad-scope": _swap(ASK, "--scope", "Bad Scope"),
}


@pytest.mark.parametrize("argv", REFUSALS.values(), ids=REFUSALS.keys())
def test_refusals(root, capsys, argv):
    assert ruling_cli.main(argv) == 2
    cap = capsys.readouterr()
    assert cap.out == ""
    err = cap.err.strip().splitlines()
    assert len(err) == 1 and err[0].startswith("ruling-cli:")
    assert _files(root) == []


def _ask_id(argv, capsys):
    assert ruling_cli.main(argv) == 0
    return json.loads(capsys.readouterr().out.splitlines()[0])["id"]


def test_ask_answer_wait(root, capsys):
    rid = _ask_id(ASK, capsys)
    assert ruling_cli.main(["answer", "--id", rid, "--choice", "reword"]) == 0
    capsys.readouterr()
    assert ruling_cli.main(["wait", "--id", rid]) == 0
    assert capsys.readouterr().out.splitlines() == ["reword"]
    rid2 = _ask_id(_swap(ASK, "--question", "Another question?"), capsys)
    assert ruling_cli.main(["answer", "--id", rid2, "--choice",
                            "answer-in-text", "--text",
                            "Use the shorter claim"]) == 0
    capsys.readouterr()
    assert ruling_cli.main(["wait", "--id", rid2]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "answer-in-text", "Use the shorter claim"]
