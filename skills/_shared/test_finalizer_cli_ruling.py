"""Tests for finalizer_cli ruling scope -- --scope/--entry, the ruling file, exit 2.

design: fable-escalation (Task 4.3). The scope comes from ``--scope`` or from a
``--decisions`` path under ``tp-designs/<slug>/`` or ``completed-tp-designs/<slug>/``.
A question stop with no scope is a usage error (exit 2, nothing written); any other
source writes no ruling file and prints one ``finalizer-cli: no ruling scope`` line
before its JSON. Every test chdirs into a non-git tmp dir so the ruling root resolves
there and no ruling file ever lands in this repo.
Run with: python3 -m pytest skills/_shared/test_finalizer_cli_ruling.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import finalizer_cli as cli  # noqa: E402
import finalizer_ruling as fr  # noqa: E402
import ruling_file as rf  # noqa: E402

T = 1_800_000_000.0
URL = "https://github.com/acme/widgets/pull/42"
STOP = {"source": "pr-iterate", "signal": "round-cap", "target": URL, "head": "a1" * 20,
        "detail": {"iteration": 8, "measured": 8, "limit": 6, "signal": "round-cap"}}
HALT = {"source": "halt", "signal": "env-error", "target": "widgets", "detail": "pytest missing"}
QUESTION = {"source": "question", "signal": "decision", "target": "fable-escalation",
            "detail": {"question": "Which rung owns the retry?"}}


class Rec:
    def __init__(self):
        self.calls = []

    def kwargs(self, now=T):
        return {"comment_fn": lambda u, b: self.calls.append(("comment", u, b)) or True,
                "label_fn": lambda u, lb: self.calls.append(("label", u, lb)) or True,
                "pr_state_fn": lambda u: {"state": "OPEN", "headRefOid": "b2" * 20},
                "is_ancestor_fn": lambda a, b: True, "now": now}


def run(capsys, rec, *argv, now=T):
    rc = cli.main([str(a) for a in argv], **rec.kwargs(now))
    captured = capsys.readouterr()
    lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    return rc, (json.loads(lines[-1]) if lines else None), lines, captured.err


def reply(tmp, outcome="resolved"):
    body = {"outcome": outcome, "actions": [], "diagnosis": "the loop cannot converge",
            "reasoning": "r (vision.md)", "demoted": [], "blocked": [], **fr.EMPTY_RULING}
    path = tmp / "reply.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def escalate_argv(stop, *more, decisions=None):
    return ["escalate", "--stop", json.dumps(stop), "--decisions",
            decisions or Path("decisions.md"), "--reason", "nested", *more]


def apply_argv(tmp, stop, *more, decisions=None):
    return ["apply", "--stop", json.dumps(stop), "--ledger", tmp / "ledger.json",
            "--reply", reply(tmp), "--decisions", decisions or Path("decisions.md"), *more]


VISION = ("# Vision\n\n## Fleet operation\n"
          "A run reaches a reviewable PR unattended.\n\n"
          "## Non-goals\nNo hosted service.\n")
QUOTE = "A run reaches a reviewable PR unattended."
OPT_A = {"id": "a", "label": "The run owns the retry",
         "description": "the run picks the retry rung", "recommended": True}
OPT_B = {"id": "b", "label": "The seat owns the retry",
         "description": "the seat picks the retry rung", "recommended": False}


def pillar_repo(tmp):
    """A tmp repo whose only pillar doc is ``three-pillars-docs/vision.md``."""
    doc = tmp / "three-pillars-docs" / "vision.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(VISION, encoding="utf-8")


def question_reply(tmp, quote=QUOTE):
    """A ``resolved`` question reply: a pillar basis, and a ``reasoning`` that cites
    no grounding doc — only the pillar check (``source="question"``) can resolve it.
    """
    body = {"outcome": "resolved", "actions": ["answer-question"], "diagnosis": "",
            "reasoning": "the chosen option follows the pillar quote",
            "demoted": [], "blocked": [],
            **fr.EMPTY_RULING,
            "options": [OPT_A, OPT_B],
            "pillar_basis": [{"option": "a", "doc": "vision.md",
                              "section": "Fleet operation", "quote": quote,
                              "stance": "serves"}],
            "confidence": "high"}
    path = tmp / "question-reply.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def question_apply_argv(tmp, *more, quote=QUOTE):
    """``apply`` for the question stop. The scope and any extra flags arrive in
    ``*more``, so a literal ``--pr-url`` is never swallowed into ``quote``.
    """
    return ["apply", "--stop", json.dumps(QUESTION), "--ledger", tmp / "ledger.json",
            "--reply", question_reply(tmp, quote=quote),
            "--decisions", Path("decisions.md"), *more]


def test_scope_from_flag(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc, out, lines, err = run(capsys, Rec(), *escalate_argv(HALT, "--scope", "fable-escalation"))
    assert (rc, out["outcome"]) == (0, "escalate")
    assert out["ruling_id"].startswith("fable-escalation-")
    path = tmp_path / rf.RULINGS_REL / (out["ruling_id"] + ".md")
    assert path == Path(out["ruling_path"]) and path.is_file()
    assert "slug: fable-escalation" in path.read_text(encoding="utf-8")


def test_scope_from_tp_designs_decisions(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decisions = tmp_path / "three-pillars-docs" / "tp-designs" / "my-design" / "decisions.md"
    rc, out, lines, err = run(capsys, Rec(), *escalate_argv(HALT, decisions=decisions))
    assert (rc, out["outcome"]) == (0, "escalate")
    assert out["ruling_id"].startswith("my-design-")
    assert (tmp_path / rf.RULINGS_REL / (out["ruling_id"] + ".md")).is_file()


def test_scope_from_completed_decisions(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decisions = (tmp_path / "three-pillars-docs" / "completed-tp-designs"
                 / "archived-design" / "decisions.md")
    rc, out, lines, err = run(capsys, Rec(), *escalate_argv(HALT, decisions=decisions))
    assert (rc, out["outcome"]) == (0, "escalate")
    assert out["ruling_id"].startswith("archived-design-")
    assert (tmp_path / rf.RULINGS_REL / (out["ruling_id"] + ".md")).is_file()


def test_escalate_with_scope_writes_ruling_file(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc, out, lines, err = run(capsys, Rec(), *escalate_argv(HALT, "--scope", "fable-escalation"))
    assert rc == 0 and {"ruling_id", "ruling_path"} <= set(out)
    text = Path(out["ruling_path"]).read_text(encoding="utf-8")
    assert text.startswith("---\n") and "outcome: escalate" in text.split("---")[1]
    parsed = rf.parse(out["ruling_path"])
    for key, value in fr.EMPTY_RULING.items():  # escalate has no reply: the ruling is empty
        assert parsed["ruling"][key] == value, key
    assert parsed["front"]["source"] == "halt"
    entry = (tmp_path / "decisions.md").read_text(encoding="utf-8")
    assert f"- **Ruling**: {out['ruling_id']}" in entry


def test_question_escalate_without_scope_exits_2(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc, out, lines, err = run(capsys, Rec(), *escalate_argv(QUESTION))
    assert rc == 2 and out is None
    assert "finalizer-cli: question stop needs --scope" in err
    assert not (tmp_path / rf.RULINGS_REL).exists()
    assert not (tmp_path / "decisions.md").exists()
    assert Rec().calls == []


def test_question_apply_without_scope_exits_2(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc, out, lines, err = run(capsys, Rec(), *apply_argv(tmp_path, QUESTION))
    assert rc == 2 and out is None
    assert "finalizer-cli: question stop needs --scope" in err
    assert not (tmp_path / rf.RULINGS_REL).exists()
    assert not (tmp_path / "decisions.md").exists()


def test_halt_escalate_without_scope_writes_no_file(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc, out, lines, err = run(capsys, Rec(), *escalate_argv(HALT))
    assert rc == 0 and out["outcome"] == "escalate"
    assert lines[-1].startswith("{")  # the JSON result is still the last line
    assert "finalizer-cli: no ruling scope" in lines
    assert lines.index("finalizer-cli: no ruling scope") == len(lines) - 2
    assert "ruling_id" not in out and "ruling_path" not in out
    assert not (tmp_path / rf.RULINGS_REL).exists()
def test_apply_question_with_pillar_quote_resolves(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pillar_repo(tmp_path)
    rec = Rec()
    rc, out, lines, err = run(capsys, rec, *question_apply_argv(tmp_path, "--scope", "demo"))
    assert rc == 0 and out["outcome"] == "resolved"
    path = Path(out["ruling_path"])
    assert path == tmp_path / rf.RULINGS_REL / (out["ruling_id"] + ".md")
    text = path.read_text(encoding="utf-8")
    assert "outcome: resolved" in text.split("---")[1]
    assert rf.parse(path)["front"]["kind"] == "decision"
    assert rec.calls == []


def test_apply_question_fabricated_quote_escalates(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pillar_repo(tmp_path)
    rec = Rec()
    rc, out, lines, err = run(capsys, rec, *question_apply_argv(
        tmp_path, "--scope", "demo", quote="no such text anywhere"))
    assert rc == 0 and out["outcome"] == "escalate"
    assert any(p.startswith("pillar-basis-missing") for p in out["problems"]), out["problems"]
    assert not any(p.startswith("ungrounded") for p in out["problems"])
    assert "outcome: escalate" in Path(out["ruling_path"]).read_text(encoding="utf-8").split("---")[1]
    assert rec.calls == []


MERGE_QUESTION = {"source": "question", "signal": "merge",
                  "target": "fable-escalation",
                  "detail": {"question": "Merge the candidate now?"}}


def test_apply_question_operator_only_signal_escalates(capsys, tmp_path, monkeypatch):
    """8.3: a `merge` question stop escalates through the CLI even with a verbatim
    serves quote — the ruling file records the operator-only escalation."""
    monkeypatch.chdir(tmp_path)
    pillar_repo(tmp_path)
    rec = Rec()
    argv = ["apply", "--stop", json.dumps(MERGE_QUESTION), "--ledger",
            tmp_path / "ledger.json", "--reply", question_reply(tmp_path),
            "--decisions", Path("decisions.md"), "--scope", "demo"]
    rc, out, lines, err = run(capsys, rec, *argv)
    assert rc == 0 and out["outcome"] == "escalate", out
    assert "operator-only: merge" in out["problems"], out["problems"]
    parsed = rf.parse(out["ruling_path"])
    assert parsed["front"]["outcome"] == "escalate"
    assert parsed["front"]["kind"] == "merge"
    assert rec.calls == []


def test_apply_question_without_scope_exits_2(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pillar_repo(tmp_path)
    rec = Rec()
    rc, out, lines, err = run(capsys, rec, *question_apply_argv(tmp_path))
    assert rc == 2 and out is None
    assert "finalizer-cli: question stop needs --scope" in err
    assert not (tmp_path / rf.RULINGS_REL).exists()
    assert not (tmp_path / "decisions.md").exists()
    assert rec.calls == []


def test_apply_question_posts_nothing(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pillar_repo(tmp_path)
    rec = Rec()
    rc, out, lines, err = run(capsys, rec, *question_apply_argv(
        tmp_path, "--scope", "demo", "--pr-url", URL))
    assert rc == 0 and out["outcome"] == "resolved"
    assert rec.calls == []  # a question stop has no PR: never a comment, never a label
    assert "finalizer-cli: no ruling scope" not in lines


def test_decisions_entry_names_ruling(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pillar_repo(tmp_path)
    rec = Rec()
    rc, out, lines, err = run(capsys, rec, *question_apply_argv(tmp_path, "--scope", "demo"))
    assert rc == 0 and out["outcome"] == "resolved"
    entry = (tmp_path / "decisions.md").read_text(encoding="utf-8")
    assert entry.startswith("### [finalizer] resolved — question/decision")
    assert f"- **Ruling**: {out['ruling_id']}" in entry
