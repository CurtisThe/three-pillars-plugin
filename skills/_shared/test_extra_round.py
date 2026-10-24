"""Tests for extra_round — the pinned per-(slug, slot) extra-round question.

design: escalation-threshold (Task 1.2). The one-grant cap is the finalizer
ledger's at-most-once stop key over this pinned text.
Run with: python3 -m pytest skills/_shared/test_extra_round.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extra_round as er  # noqa: E402
import finalizer  # noqa: E402

RESOLVE = lambda n: "three-pillars:tp-finalizer"  # noqa: E731


def test_question_names_slot_and_differs():
    q = er.question("design")
    assert isinstance(q, str) and q and "design" in q
    assert q != er.question("plan")


def test_stop_shape_and_keys():
    s = er.stop("my-design", "design")
    assert s["source"] == "question" and s["signal"] == "decision"
    assert s["target"] == "my-design"
    assert s["detail"]["question"] == er.question("design")
    names = [o["name"] if isinstance(o, dict) else o for o in s["detail"]["options"]]
    assert "grant-one-round" in str(names) and "stop-here" in str(names)
    key = finalizer.stop_key(s)
    assert key == finalizer.stop_key(er.stop("my-design", "design"))
    assert key != finalizer.stop_key(er.stop("my-design", "plan"))
    assert key != finalizer.stop_key(er.stop("other", "design"))


def test_aliases_and_bad_slots():
    for alias, slot in [("design-audit", "design"), ("plan-audit", "plan"),
                        ("impl-audit", "implementation")]:
        assert finalizer.stop_key(er.stop("x", alias)) == finalizer.stop_key(er.stop("x", slot))
    for bad in ("tier-3.5", "", "../y"):
        with pytest.raises(ValueError):
            er.stop("x", bad)


def test_cap_one_grant(tmp_path):
    ledger = tmp_path / "finalizer-ledger.json"
    s = er.stop("x", "design")
    first = finalizer.prepare(s, ledger, resolve_fn=RESOLVE)
    assert first["status"] == "dispatch"
    assert finalizer.clear_in_flight(ledger, finalizer.stop_key(s), "resolved")
    second = finalizer.prepare(s, ledger, resolve_fn=RESOLVE)
    assert second["status"] == "refused" and second["reason"] == "already-finalized"
    other = finalizer.prepare(er.stop("x", "plan"), ledger, resolve_fn=RESOLVE)
    assert other["status"] == "dispatch"


def test_cli(tmp_path, capsys):
    assert er.main(["stop", "--slug", "x", "--slot", "design-audit"]) == 0
    assert json.loads(capsys.readouterr().out) == er.stop("x", "design")
    assert er.main(["stop", "--slug", "x", "--slot", "tier-3.5"]) == 2
    err = capsys.readouterr().err
    assert len(err.strip().splitlines()) == 1
    out = tmp_path / "s.json"
    assert er.main(["stop", "--slug", "x", "--slot", "plan", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == er.stop("x", "plan")
