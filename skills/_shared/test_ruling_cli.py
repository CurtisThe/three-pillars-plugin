"""Tests for ruling_cli — answer / feedback / link / show.

design: fable-escalation (Task 4.5). Every subcommand prints exactly one JSON
line on stdout and exits 0; bad input (unknown id, id outside ``ID_RE``, a
verdict that is not agree/disagree, missing args) exits 2 with a
``ruling-cli: <why>`` line on stderr and writes nothing. Every test chdirs into
a non-git tmp dir so the ruling root resolves there, and writes its ruling with
``ruling_file.write``.
Run with: python3 -m pytest skills/_shared/test_ruling_cli.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ruling_cli  # noqa: E402
import ruling_file as rf  # noqa: E402

AT = "2026-10-11T19:00:00Z"
STOP = {"source": "halt", "signal": "env-error", "target": "demo",
        "detail": "pytest missing"}
KEY = "halt:env-error:demo:deadbeef"
RESULT = {"outcome": "escalate", "problems": ["x"], "diagnosis": "d",
          "reasoning": "r (vision.md)", "demoted": [], "actions": []}


@pytest.fixture
def ruling(tmp_path, monkeypatch):
    """A tmp repo holding one ruling file; returns its id."""
    monkeypatch.chdir(tmp_path)
    path = rf.write(tmp_path, scope="demo", entry="run", stop=STOP, key=KEY,
                    result=RESULT, model="fable", at=AT)
    return path.stem


def _json_out(capsys):
    """The single JSON line on stdout (and nothing else printed there)."""
    captured = capsys.readouterr()
    lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    assert len(lines) == 1, captured.out
    return json.loads(lines[0])


def _stderr(capsys):
    return capsys.readouterr().err.strip()


def test_answer_appends_feedback(tmp_path, ruling, capsys):
    code = ruling_cli.main(["answer", "--id", ruling, "--choice", "Continue",
                            "--text", "ok"])
    assert code == 0
    assert _json_out(capsys)["id"] == ruling
    parsed = rf.parse(rf.find(tmp_path, ruling))
    assert any(ln.endswith("answer: Continue — ok") for ln in parsed["feedback"])


def test_answer_without_text_is_choice_only(tmp_path, ruling, capsys):
    assert ruling_cli.main(["answer", "--id", ruling, "--choice",
                            "Stop-run"]) == 0
    _json_out(capsys)
    parsed = rf.parse(rf.find(tmp_path, ruling))
    assert any(ln.endswith("answer: Stop-run") for ln in parsed["feedback"])


def test_feedback_agree_disagree(tmp_path, ruling, capsys):
    assert ruling_cli.main(["feedback", "--id", ruling, "agree",
                            "--reason", "pillar 1 wins"]) == 0
    _json_out(capsys)
    assert ruling_cli.main(["feedback", "--id", ruling, "disagree",
                            "--reason", "cost"]) == 0
    _json_out(capsys)
    parsed = rf.parse(rf.find(tmp_path, ruling))
    assert any(ln.endswith("agree — pillar 1 wins") for ln in parsed["feedback"])
    assert any(ln.endswith("disagree — cost") for ln in parsed["feedback"])


def test_link_sets_explain(tmp_path, ruling, capsys):
    assert ruling_cli.main(["link", "--id", ruling, "--explain",
                            "three-pillars-docs/escalations/human-escalation.md"
                            "#demo"]) == 0
    assert _json_out(capsys)["id"] == ruling
    parsed = rf.parse(rf.find(tmp_path, ruling))
    assert parsed["front"]["explain"].endswith("#demo")


def test_show_prints_parsed(tmp_path, ruling, capsys):
    assert ruling_cli.main(["show", "--id", ruling]) == 0
    assert _json_out(capsys) == rf.parse(rf.find(tmp_path, ruling))


def test_unknown_id_exits_2(tmp_path, ruling, capsys):
    assert ruling_cli.main(["show", "--id", "demo-20261011-aaaaaa"]) == 2
    assert _stderr(capsys).startswith("ruling-cli: ")
    assert capsys.readouterr().out == ""


def test_bad_id_shape_exits_2(tmp_path, ruling, capsys):
    assert ruling_cli.main(["answer", "--id", "../outside", "--choice",
                            "Continue"]) == 2
    assert _stderr(capsys).startswith("ruling-cli: ")
    assert rf.find(tmp_path, "demo-20261011-aaaaaa") is None


def test_feedback_bad_verdict_exits_2(tmp_path, ruling, capsys):
    assert ruling_cli.main(["feedback", "--id", ruling, "maybe",
                            "--reason", "x"]) == 2
    assert _stderr(capsys).startswith("ruling-cli: ")
    assert rf.parse(rf.find(tmp_path, ruling))["feedback"] == []


def test_missing_args_exit_2(tmp_path, ruling, capsys):
    for argv in (["answer", "--id", ruling],
                 ["feedback", "--id", ruling, "agree"],
                 ["link", "--id", ruling],
                 []):
        assert ruling_cli.main(argv) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip()


# --- Task 4.6: subject and card -------------------------------------------

Q_STOP = {"source": "question", "signal": "decision", "target": "demo",
          "detail": {"question": "Rewrite the retry loop now or later?"}}
OPTIONS = [
    {"id": "a", "label": "Rewrite now", "description": "Land it this phase.",
     "recommended": True},
    {"id": "b", "label": "Rewrite later",
     "description": "Keep the current loop.", "recommended": False},
]
BASIS = [
    {"option": "a", "doc": "vision.md", "section": "Fleet operation",
     "stance": "serves", "quote": "unattended"},
    {"option": "b", "doc": "architecture.md", "section": "Retry rules",
     "stance": "violates", "quote": "one shared predicate"},
]
RULING6 = {"options": OPTIONS, "pillar_basis": BASIS,
           "tie_breaker": "pillar 1 wins", "commits_to": ["known_issues.md"],
           "confidence": "high", "lesson_proposal": None}
Q_RESULT = {"outcome": "resolved", "problems": [], "diagnosis": "d",
            "reasoning": "r (vision.md)", "demoted": [], "actions": [],
            "ruling": RULING6}


def _write_question_ruling(tmp_path, result, at=AT):
    """A question-stop ruling file holding ``result``; returns its id."""
    path = rf.write(tmp_path, scope="demo", entry="run", stop=Q_STOP,
                    key="question:decision:demo:cafebabe", result=result,
                    model="fable", at=at)
    return path.stem


@pytest.fixture
def question_ruling(tmp_path, monkeypatch):
    """A resolved question-stop ruling with two options; returns its id."""
    monkeypatch.chdir(tmp_path)
    return _write_question_ruling(tmp_path, Q_RESULT)


def test_subject_writes_dict(tmp_path, question_ruling, capsys):
    out = tmp_path / "subject.json"
    assert ruling_cli.main(["subject", "--id", question_ruling,
                            "--out", str(out)]) == 0
    emitted = _json_out(capsys)
    assert emitted["id"] == question_ruling
    assert Path(emitted["out"]) == out
    subject = json.loads(out.read_text(encoding="utf-8"))
    assert set(subject) == {"question", "decided", "options", "pillar_basis",
                            "commits_to", "tie_breaker"}
    assert subject["question"] == Q_STOP["detail"]["question"]
    assert subject["decided"] == "Rewrite now — Land it this phase."
    assert subject["options"] == OPTIONS
    assert subject["pillar_basis"] == BASIS
    assert subject["commits_to"] == ["known_issues.md"]
    assert subject["tie_breaker"] == "pillar 1 wins"


def test_card_recommended_first_and_tagged(tmp_path, question_ruling, capsys):
    assert ruling_cli.main(["card", "--id", question_ruling]) == 0
    card = _json_out(capsys)
    assert set(card) == {"question", "options"}
    assert card["question"] == (Q_STOP["detail"]["question"]
                                + "\nruling: " + question_ruling)
    labels = [o["label"] for o in card["options"]]
    assert labels == ["Rewrite now (Recommended)", "Rewrite later"]
    assert card["options"][0]["description"] == (
        "Land it this phase. Serves vision.md \u00a7 Fleet operation.")
    assert card["options"][1]["description"] == (
        "Keep the current loop. Violates architecture.md \u00a7 Retry rules.")


def test_card_pads_to_two_options(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    one = dict(RULING6, options=[dict(OPTIONS[0])])
    rid = _write_question_ruling(tmp_path, dict(Q_RESULT, ruling=one))
    assert ruling_cli.main(["card", "--id", rid]) == 0
    card = _json_out(capsys)
    labels = [o["label"] for o in card["options"]]
    assert labels == ["Rewrite now (Recommended)", "stop-run"]
    assert card["options"][1]["description"]
    assert len(card["options"]) == 2


def test_card_zero_options_pads_distinct(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    zero = dict(RULING6, options=[])
    rid = _write_question_ruling(tmp_path, dict(Q_RESULT, ruling=zero))
    assert ruling_cli.main(["card", "--id", rid]) == 0
    card = _json_out(capsys)
    labels = [o["label"] for o in card["options"]]
    assert labels == ["stop-run", "answer-in-text"]
    assert len(card["options"]) == 2
    assert all(o["description"] for o in card["options"])


def test_card_caps_at_four(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    opts = [dict(OPTIONS[1])] + [
        {"id": "c", "label": "Option c", "description": "Third."},
        {"id": "d", "label": "Option d", "description": "Fourth."},
        {"id": "e", "label": "Option e", "description": "Fifth."},
        dict(OPTIONS[0]),
    ]
    five = dict(RULING6, options=opts)
    rid = _write_question_ruling(tmp_path, dict(Q_RESULT, ruling=five))
    assert ruling_cli.main(["card", "--id", rid]) == 0
    card = _json_out(capsys)
    labels = [o["label"] for o in card["options"]]
    assert len(card["options"]) == 4
    assert labels[0] == "Rewrite now (Recommended)"
    assert labels[1:] == ["Rewrite later", "Option c", "Option d"]


def test_card_html_link(tmp_path, question_ruling, capsys):
    assert ruling_cli.main(["card", "--id", question_ruling, "--html",
                            "three-pillars-docs/escalations/demo.html"]) == 0
    card = _json_out(capsys)
    assert card["question"] == (Q_STOP["detail"]["question"]
                                + " (Full explanation: "
                                + "three-pillars-docs/escalations/demo.html)"
                                + "\nruling: " + question_ruling)
