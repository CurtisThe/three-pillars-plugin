"""Pins for the seat's Opus fallback when Fable is unavailable (design seat-escalate-first 2.5).

The CLI side (prepare/apply) is pinned; the /tp-escalate SKILL.md must name the flags.
Run with: python3 -m pytest skills/_shared/test_seat_fable_fallback.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import finalizer_cli as cli  # noqa: E402
import finalizer_ruling as fr  # noqa: E402
import ruling_file as rf  # noqa: E402

SKILL = Path(__file__).resolve().parents[1] / "tp-escalate" / "SKILL.md"
STOP = {"source": "question", "signal": "decision", "target": "seat",
        "detail": {"question": "Which rung owns the retry?"}}


def _repo(tmp_path, monkeypatch):
    docs = tmp_path / "three-pillars-docs"
    docs.mkdir()
    (docs / "vision.md").write_text("# Vision\n\n## Fleet\nA run reaches a PR.\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)


def _main(capsys, *argv):
    rc = cli.main([str(a) for a in argv])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    return rc, json.loads(lines[-1])


def test_prepare_seat_returns_opus_xhigh_fallback(capsys, tmp_path, monkeypatch):
    _repo(tmp_path, monkeypatch)
    rc, out = _main(capsys, "prepare", "--stop", json.dumps(STOP),
                    "--ledger", tmp_path / "ledger.json", "--entry", "seat")
    assert rc == 0
    assert out["fallback"] == {"model": "opus", "effort": "xhigh"}


def test_apply_opus_fallback_writes_opus_ruling(capsys, tmp_path, monkeypatch):
    _repo(tmp_path, monkeypatch)
    body = {"outcome": "escalate", "actions": [], "diagnosis": "no pillar basis",
            "reasoning": "r (vision.md)", "demoted": [], "blocked": [], **fr.EMPTY_RULING}
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps(body), encoding="utf-8")
    rc, out = _main(capsys, "apply", "--stop", json.dumps(STOP),
                    "--ledger", tmp_path / "ledger.json", "--reply", reply,
                    "--decisions", tmp_path / "decisions.md", "--model-used", "opus",
                    "--fallback-reason", "fable-unavailable", "--scope", "seat", "--entry", "seat")
    assert rc == 0
    parsed = rf.parse(out["ruling_path"])
    assert parsed["front"]["model"] == "opus"


def _step(n):
    """The text of /tp-escalate step `n` (its `N. **` line up to the next step's)."""
    text = SKILL.read_text(encoding="utf-8")
    start = re.search(r"(?m)^%d\. \*\*" % n, text).start()
    nxt = re.search(r"(?m)^%d\. \*\*" % (n + 1), text[start:])
    return text[start:start + nxt.start()] if nxt else text[start:]


def test_skill_step5_names_fallback_flags():
    step = _step(5)
    assert "--model-used opus" in step
    assert "--fallback-reason" in step


def test_skill_step4_names_operator_only_kinds():
    step = _step(4)
    assert "--kind base-sync-hunk" in step
    assert "--kind scope-growth" in step
