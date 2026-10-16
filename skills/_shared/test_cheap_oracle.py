"""Tests for cheap_oracle.py — the oracle contract and the classifier_schema oracle.

design: cheap-tier-offload (Task 2.1).
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_oracle as co  # noqa: E402
import cheap_tier as ct  # noqa: E402

CLAIMS = {"ok": True, "exit": 0, "ran": True, "passed": True}
FENCE = "\x60" * 3  # a Markdown code fence


class _Spy(dict):
    """A dict that records every key read through [] or get."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.read = set()

    def __getitem__(self, key):
        self.read.add(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self.read.add(key)
        return super().get(key, default)


def _reply(entries):
    return f"Here you go:\n{FENCE}json\n{json.dumps(entries)}\n{FENCE}\n"


def _entry(cid):
    return {"comment_id": cid, "reviewer": "alice", "verdict": "minor",
            "confidence": "High", "reason": "typo only"}


@pytest.fixture
def spy_oracle(monkeypatch):
    """Point the handoff slot at a registered test oracle; yield its call log."""
    calls = []

    def _oracle(artifact, ctx):
        calls.append((artifact, ctx))
        return ctx.get("result", (True, "fine"))

    monkeypatch.setitem(co.ORACLES, "t_spy", _oracle)
    monkeypatch.setitem(ct.SLOTS, "handoff", ct.SLOTS["handoff"]._replace(oracle="t_spy"))
    return calls


# --- check -----------------------------------------------------------------------


def test_check_looks_up_the_slot_oracle(spy_oracle):
    v = co.check("handoff", {"text": "x"}, {"result": (True, "fine")})
    assert v == {"ok": True, "oracle": "t_spy", "reason": "fine"}
    assert spy_oracle == [({"text": "x"}, {"result": (True, "fine")})]


def test_check_failing_oracle(spy_oracle):
    v = co.check("handoff", {}, {"result": (False, "missing heading")})
    assert v == {"ok": False, "oracle": "t_spy", "reason": "missing heading"}


def test_oracle_exception_becomes_oracle_error(monkeypatch):
    def _boom(artifact, ctx):
        raise RuntimeError("kaput")

    monkeypatch.setitem(co.ORACLES, "t_boom", _boom)
    monkeypatch.setitem(ct.SLOTS, "handoff", ct.SLOTS["handoff"]._replace(oracle="t_boom"))
    v = co.check("handoff", {}, {})
    assert v["ok"] is False and v["oracle"] == "t_boom"
    assert v["reason"].startswith("oracle-error: ") and "kaput" in v["reason"]


def test_unregistered_oracle_is_not_ok(monkeypatch):
    monkeypatch.setitem(ct.SLOTS, "handoff",
                        ct.SLOTS["handoff"]._replace(oracle="t_no_such_oracle"))
    v = co.check("handoff", {}, {})
    assert v["ok"] is False and v["oracle"] == "t_no_such_oracle"
    assert "unregistered" in v["reason"]


@pytest.mark.parametrize("slot", ["task", "no_such_slot", "review", "flake_triage"])
def test_unknown_slot_or_task_raises(slot):
    with pytest.raises(ValueError):
        co.check(slot, {}, {})


def test_check_never_reads_artifact_claims(spy_oracle):
    art = _Spy(CLAIMS)
    co.check("handoff", art, {"result": (False, "no")})
    assert art.read.isdisjoint(CLAIMS)


def test_register_decorator_adds_to_registry(monkeypatch):
    monkeypatch.setattr(co, "ORACLES", dict(co.ORACLES))

    @co.register("t_new")
    def _new(artifact, ctx):
        return True, ""

    assert co.ORACLES["t_new"] is _new


# --- settle ----------------------------------------------------------------------


@pytest.mark.parametrize("slot", sorted(set(ct.SLOTS) - {"task"}))
def test_settle(slot):
    assert co.settle(slot, {"ok": True, "oracle": "x", "reason": ""}) == "accept"
    failed = {"ok": False, "oracle": "x", "reason": "r"}
    assert co.settle(slot, failed) == ct.SLOTS[slot].on_fail


# --- classifier_schema -----------------------------------------------------------


def test_classifier_schema_pass():
    pytest.importorskip("jsonschema")
    art = {"response": _reply([_entry(11), _entry("c-2")])}
    v = co.check("classifier_judge", art, {"borderline_ids": [11, "c-2"]})
    assert v == {"ok": True, "oracle": "classifier_schema", "reason": ""}


def test_classifier_schema_extra_id_fails():
    pytest.importorskip("jsonschema")
    art = {"response": _reply([_entry(11), _entry(12)])}
    v = co.check("classifier_judge", art, {"borderline_ids": [11]})
    assert v["ok"] is False and "12" in v["reason"]


def test_classifier_schema_missing_id_and_duplicate_fail():
    pytest.importorskip("jsonschema")
    missing = co.check("classifier_judge", {"response": _reply([_entry(11)])},
                       {"borderline_ids": [11, 12]})
    dup = co.check("classifier_judge", {"response": _reply([_entry(11), _entry(11)])},
                   {"borderline_ids": [11]})
    assert missing["ok"] is False and dup["ok"] is False


def test_classifier_schema_invalid_entry_is_oracle_error():
    pytest.importorskip("jsonschema")
    bad = dict(_entry(11), extra="field")
    v = co.check("classifier_judge", {"response": _reply([bad])}, {"borderline_ids": [11]})
    assert v["ok"] is False and v["reason"].startswith("oracle-error: ")
    assert co.settle("classifier_judge", v) == "escalate"


def test_classifier_schema_ignores_claims():
    pytest.importorskip("jsonschema")
    art = _Spy(CLAIMS, response="no json here")
    v = co.check("classifier_judge", art, {"borderline_ids": [11]})
    assert v["ok"] is False
    assert art.read.isdisjoint(CLAIMS)


# --- stdlib-only import ----------------------------------------------------------


def test_import_is_stdlib_only_and_blocked_jsonschema_escalates(monkeypatch):
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    monkeypatch.delitem(sys.modules, "classifier_judge", raising=False)
    monkeypatch.delitem(sys.modules, "cheap_oracle", raising=False)
    fresh = importlib.import_module("cheap_oracle")
    assert "classifier_judge" not in sys.modules  # not imported at module load
    v = fresh.check("classifier_judge", {"response": _reply([_entry(1)])},
                    {"borderline_ids": [1]})
    assert v["ok"] is False and v["reason"].startswith("oracle-error: ")
    assert fresh.settle("classifier_judge", v) == "escalate"


# --- prose_shape (Task 7.1) -----------------------------------------------------


def test_prose_shape(tmp_path):
    """The prose slots route through check to prose_oracle's prose_shape, drop on fail."""
    assert {ct.SLOTS[s].oracle for s in ("handoff", "history_line", "docs_draft")} == {
        "prose_shape"}
    line = "- 2026-09-30 — the prose oracle landed."
    ctx = {"kind": "history_line", "root": str(tmp_path), "facts": {}}
    v = co.check("history_line", {"text": line}, ctx)
    assert v == {"ok": True, "oracle": "prose_shape", "reason": ""}
    assert co.settle("history_line", v) == "accept"
    draft = tmp_path / "draft.md"
    draft.write_text("## Phase\nTBD\n")
    v = co.check("handoff", {"path": str(draft), **CLAIMS}, dict(ctx, kind="handoff"))
    assert v["ok"] is False and v["oracle"] == "prose_shape" and "## State" in v["reason"]
    assert co.settle("handoff", v) == "drop"
    v = co.check("docs_draft", {"text": line}, {"root": str(tmp_path)})
    assert v["ok"] is False and v["reason"].startswith("oracle-error: ")
