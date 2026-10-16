"""Tests for the ``question`` stop source in finalizer (design fable-escalation 3.1).

A question stop is ``{"source": "question", "signal": <kind>, "target": <slug>,
"detail": {"question": "..."}}``. Its key follows the halt grammar
(``question:<kind>:<slug>:<hash8>``) over ``normalize_detail(detail["question"])``,
the kind must be one of ``finalizer_ruling.KINDS``, and ``_target_of_key`` reads
the slug back like it does for a halt key.
Run with: python3 -m pytest skills/_shared/test_finalizer_question_stop.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import finalizer as fin  # noqa: E402
import finalizer_cli as cli  # noqa: E402
import finalizer_outcome as fo  # noqa: E402
import finalizer_ruling as fr  # noqa: E402


def _question(question="Which option?", kind="decision", target="my-design"):
    return {"source": "question", "signal": kind, "target": target,
            "detail": {"question": question}}


def test_question_key_grammar():
    key = fin.stop_key(_question("Which option?"))
    head, _, digest = key.rpartition(":")
    assert head == "question:decision:my-design"
    assert re.fullmatch(r"[0-9a-f]{8}", digest)


def test_question_key_ignores_volatile_tokens():
    assert fin.stop_key(_question("retry in 30 seconds")) == fin.stop_key(
        _question("retry in 45 seconds")
    )


def test_question_kind_outside_enum_raises():
    with pytest.raises(ValueError):
        fin.stop_key(_question(kind="lunch"))


def test_target_of_question_key():
    key = fin.stop_key(_question())
    assert fin._target_of_key(key) == "my-design"


def _repo(tmp_path, pillars=("vision.md",), lessons_md=True):
    """tmp repo with the named pillar docs (+ repo lesson layer when asked)."""
    docs = tmp_path / "three-pillars-docs"
    docs.mkdir()
    for name in pillars:
        (docs / name).write_text(f"# {name}\n", encoding="utf-8")
    if lessons_md:
        lesson_file = docs / "escalations" / "lessons.md"
        lesson_file.parent.mkdir(parents=True, exist_ok=True)
        lesson_file.write_text("### L1 — t\n- lesson: x\n", encoding="utf-8")
    return tmp_path


def test_brief_lines_lists_present_pillars_and_lessons(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty-config"))
    repo = _repo(tmp_path)
    lines = fr.brief_lines("seat", repo, tmp_path / "decisions.md")
    text = "\n".join(lines)
    assert "- three-pillars-docs/vision.md" in text
    assert "- three-pillars-docs/escalations/lessons.md" in text
    assert "architecture.md" not in text


def test_brief_lines_names_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty-config"))
    repo = _repo(tmp_path)
    lines = fr.brief_lines("seat", repo, tmp_path / "decisions.md")
    assert any("entry: seat" in line for line in lines)


def test_brief_lines_names_keys_and_operator_kinds(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty-config"))
    repo = _repo(tmp_path)
    lines = fr.brief_lines("seat", repo, tmp_path / "decisions.md")
    text = "\n".join(lines)
    for key in fr.RULING_KEYS:
        assert f"`{key}`" in text
    for kind in fr.OPERATOR_ONLY:
        assert f"`{kind}`" in text


def test_brief_lines_without_pillars_says_escalate(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty-config"))
    repo = _repo(tmp_path, pillars=())
    lines = fr.brief_lines("seat", repo, tmp_path / "decisions.md")
    text = "\n".join(lines)
    assert "(none found)" in text
    assert "no-pillar-basis" in text


# --- Task 3.3: the question brief tail, the seat entry, the halt hint ---------

T = 1_800_000_000.0

_STOPS = {
    "pr-iterate": {"source": "pr-iterate", "signal": "round-cap",
                   "target": "https://github.com/acme/widgets/pull/42",
                   "detail": {"measured": 8, "limit": 6}},
    "audit-gate": {"source": "audit-gate", "signal": "plan", "target": "my-design"},
    "halt": {"source": "halt", "signal": "env-error", "target": "my-design",
             "detail": "router down"},
    "question": _question(),
}


def _brief(tmp_path, stop, monkeypatch, entry=None, name="led"):
    """One dispatch's brief over a tmp repo holding vision.md."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    repo = _repo(tmp_path)
    kw = {} if entry is None else {"entry": entry}
    out = fin.prepare(stop, tmp_path / name / "finalizer-ledger.json",
                      resolve_fn=lambda a: f"three-pillars:{a}", now=T,
                      decisions_path=tmp_path / "decisions.md", repo_root=repo, **kw)
    assert out["status"] == "dispatch"
    return out["brief"]


def test_question_brief_uses_ruling_lines(tmp_path, monkeypatch):
    brief = _brief(tmp_path, _question(), monkeypatch)
    assert "- entry: run" in brief
    assert "Basis docs present:" in brief
    assert "- three-pillars-docs/vision.md" in brief
    assert "an uncited `resolved` escalates" not in brief
    assert "Grounding (read before ruling" not in brief


def test_seat_entry_brief(tmp_path, monkeypatch):
    brief = _brief(tmp_path, _question(), monkeypatch, entry="seat")
    assert "- entry: seat" in brief
    assert any(line.startswith("Seat entry:") for line in brief.splitlines())


def test_halt_brief_keeps_grounding_tail(tmp_path, monkeypatch):
    brief = _brief(tmp_path, _STOPS["halt"], monkeypatch)
    assert "Grounding (read before ruling" in brief
    assert "an uncited `resolved` escalates" in brief
    assert "- entry:" not in brief


def test_halt_hint_drops_unanswerable_question():
    assert "unanswerable" not in fin._HINTS["halt"]


@pytest.mark.parametrize("source", sorted(fin.SOURCES))
def test_brief_names_every_reply_key(tmp_path, monkeypatch, source):
    brief = _brief(tmp_path, _STOPS[source], monkeypatch)
    for key in fo.REPLY_KEYS:
        assert f"`{key}`" in brief, key


def test_cli_prepare_entry_flag(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    code = cli.main(["prepare", "--stop", json.dumps(_question()),
                     "--ledger", str(tmp_path / "finalizer-ledger.json"),
                     "--decisions", str(tmp_path / "decisions.md"),
                     "--entry", "seat"], resolve_fn=lambda a: f"three-pillars:{a}")
    assert code == 0
    out = json.loads(capsys.readouterr().out.strip())
    assert out["status"] == "dispatch"
    assert "- entry: seat" in out["brief"]


# --- Task 3.5: the agent file names the entries, ruling keys, operator kinds --

def test_agent_file_names_entries_keys_and_kinds():
    agent = (Path(__file__).resolve().parents[2] / "agents" / "tp-finalizer.md")
    text = agent.read_text(encoding="utf-8")
    for word in ("halt", "question", "seat"):
        assert f"`{word}`" in text, word
    for key in fr.RULING_KEYS:
        assert f"`{key}`" in text, key
    for kind in fr.OPERATOR_ONLY:
        assert f"`{kind}`" in text, kind
