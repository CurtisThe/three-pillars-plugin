"""Tests for finalizer.prepare — dispatch spec, ledger, refusals, stale marker.

design: fable-first-stops (Task 1.3). ``prepare`` builds the dispatch spec for
one stop, or refuses: a repeat key is ``already-finalized``, a stop for another
target while a finalizer is in flight is ``nested``, a same-target stop in flight
is a ``noop``, a corrupt ledger fails closed to ``ledger-unreadable``, and a
crashed finalizer's marker is cleared once older than ``STALE_SEC``.
Run with: python3 -m pytest skills/_shared/test_finalizer_prepare.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import finalizer as fin  # noqa: E402

T = 1_800_000_000.0
URL = "https://github.com/acme/widgets/pull/42"
OTHER = "https://github.com/acme/widgets/pull/43"


class FakeResolve:
    def __init__(self):
        self.calls = []

    def __call__(self, agent):
        self.calls.append(agent)
        return f"three-pillars:{agent}"


def _stop(signal="round-cap", target=URL, source="pr-iterate", **extra):
    return {"source": source, "signal": signal, "target": target, **extra}


@pytest.fixture
def ledger(tmp_path):
    return tmp_path / "design" / "finalizer-ledger.json"


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_empty_ledger_dispatches_and_marks_in_flight(ledger):
    resolve = FakeResolve()
    stop = _stop(head="abc123", detail={"measured": 8, "limit": 6})
    out = fin.prepare(stop, ledger, resolve_fn=resolve, now=T)
    assert out["status"] == "dispatch"
    assert out["agent_ref"] == "three-pillars:tp-finalizer"
    assert resolve.calls == ["tp-finalizer"]
    assert out["model"] == "fable"
    assert out["fallback"] == {"model": "opus", "effort": "xhigh"}
    assert out["key"] == fin.stop_key(stop)
    assert _read(ledger)["in_flight"] == {"key": out["key"], "at": T}


def test_brief_names_source_signal_target_detail_and_decisions_path(ledger):
    stop = _stop(head="abc123", detail={"measured": 8, "limit": 6})
    brief = fin.prepare(stop, ledger, resolve_fn=FakeResolve(), now=T)["brief"]
    for needle in ("pr-iterate", "round-cap", URL, "abc123", '"measured": 8'):
        assert needle in brief
    assert str(ledger.parent / "decisions.md") in brief


def test_explicit_decisions_path_overrides_the_default(ledger, tmp_path):
    decisions = tmp_path / "elsewhere" / "decisions.md"
    out = fin.prepare(_stop(), ledger, resolve_fn=FakeResolve(), now=T, decisions_path=decisions)
    assert str(decisions) in out["brief"]
    assert str(ledger.parent / "decisions.md") not in out["brief"]


@pytest.mark.parametrize(
    "stop",
    [
        _stop("wall-clock"),
        _stop("growth-lines"),
        _stop("design", target="my-design", source="audit-gate"),
        _stop("plan", target="my-design", source="audit-gate"),
        _stop("implementation", target="my-design", source="audit-gate"),
        _stop("env-error", target="my-design", source="halt", detail="router down"),
        _stop("question", target="my-design", source="halt", detail="which base branch?"),
    ],
)
def test_each_source_produces_one_dispatch_spec(ledger, stop):
    resolve = FakeResolve()
    out = fin.prepare(stop, ledger, resolve_fn=resolve, now=T)
    assert out["status"] == "dispatch" and len(resolve.calls) == 1
    assert stop["source"] in out["brief"] and stop["signal"] in out["brief"]


def test_missing_ledger_file_is_created(ledger):
    assert not ledger.exists()
    fin.prepare(_stop(), ledger, resolve_fn=FakeResolve(), now=T)
    assert ledger.is_file() and [p.name for p in ledger.parent.iterdir()] == [ledger.name]


def test_repeat_key_after_clear_is_already_finalized(ledger):
    stop = _stop()
    key = fin.prepare(stop, ledger, resolve_fn=FakeResolve(), now=T)["key"]
    fin.clear_in_flight(ledger, key, "resolved")
    resolve = FakeResolve()
    out = fin.prepare(stop, ledger, resolve_fn=resolve, now=T + 5)
    assert out["status"] == "refused" and out["reason"] == "already-finalized", (
        f"finalized stop key dispatched a second finalizer: {out}")
    assert resolve.calls == []
    assert _read(ledger)["in_flight"] is None


def test_head_moving_does_not_open_a_fresh_stop(ledger):
    key = fin.prepare(_stop(head="aaa"), ledger, resolve_fn=FakeResolve(), now=T)["key"]
    fin.clear_in_flight(ledger, key, "resolved")
    out = fin.prepare(_stop(head="bbb"), ledger, resolve_fn=FakeResolve(), now=T + 5)
    assert out["reason"] == "already-finalized"


def test_other_signal_on_same_target_after_clear_dispatches(ledger):
    key = fin.prepare(_stop("round-cap"), ledger, resolve_fn=FakeResolve(), now=T)["key"]
    fin.clear_in_flight(ledger, key, "resolved")
    out = fin.prepare(_stop("wall-clock"), ledger, resolve_fn=FakeResolve(), now=T + 5)
    assert out["status"] == "dispatch"


def test_same_target_stop_in_flight_is_a_noop_and_leaves_ledger_unchanged(ledger):
    fin.prepare(_stop("round-cap"), ledger, resolve_fn=FakeResolve(), now=T)
    before = ledger.read_bytes()
    resolve = FakeResolve()
    out = fin.prepare(_stop("wall-clock"), ledger, resolve_fn=resolve, now=T + 60)
    assert out == {"status": "noop", "reason": "in-flight-same-target"}
    assert resolve.calls == [] and ledger.read_bytes() == before


def test_same_key_while_in_flight_is_a_noop(ledger):
    fin.prepare(_stop(), ledger, resolve_fn=FakeResolve(), now=T)
    out = fin.prepare(_stop(), ledger, resolve_fn=FakeResolve(), now=T + 1)
    assert out["status"] == "noop"


def test_different_target_in_flight_is_refused_nested(ledger):
    fin.prepare(_stop(target=URL), ledger, resolve_fn=FakeResolve(), now=T)
    before = ledger.read_bytes()
    out = fin.prepare(_stop(target=OTHER), ledger, resolve_fn=FakeResolve(), now=T + 60)
    assert out["status"] == "refused" and out["reason"] == "nested"
    assert ledger.read_bytes() == before


def test_halt_in_flight_is_matched_by_target_not_by_hash(ledger):
    first = _stop("env-error", target="my-design", source="halt", detail="router down")
    fin.prepare(first, ledger, resolve_fn=FakeResolve(), now=T)
    same = _stop("question", target="my-design", source="halt", detail="other")
    other = _stop("env-error", target="another-design", source="halt", detail="x")
    assert fin.prepare(same, ledger, resolve_fn=FakeResolve(), now=T + 1)["status"] == "noop"
    assert fin.prepare(other, ledger, resolve_fn=FakeResolve(), now=T + 1)["reason"] == "nested"


def test_stale_marker_is_cleared_then_dispatch(ledger):
    old = fin.prepare(_stop(target=URL), ledger, resolve_fn=FakeResolve(), now=T)["key"]
    later = T + fin.STALE_SEC + 1
    out = fin.prepare(_stop(target=OTHER), ledger, resolve_fn=FakeResolve(), now=later)
    assert out["status"] == "dispatch" and out["stale_cleared"] == [old]
    data = _read(ledger)
    assert data["stale_cleared"] == [old]
    assert data["in_flight"] == {"key": out["key"], "at": later}


def test_marker_exactly_at_the_limit_is_not_yet_stale(ledger):
    fin.prepare(_stop(target=URL), ledger, resolve_fn=FakeResolve(), now=T)
    out = fin.prepare(_stop(target=OTHER), ledger, resolve_fn=FakeResolve(), now=T + fin.STALE_SEC)
    assert out["reason"] == "nested"


def test_stale_same_key_marker_redispatches_a_crashed_finalizer(ledger):
    key = fin.prepare(_stop(), ledger, resolve_fn=FakeResolve(), now=T)["key"]
    out = fin.prepare(_stop(), ledger, resolve_fn=FakeResolve(), now=T + fin.STALE_SEC + 1)
    assert out["status"] == "dispatch" and out["stale_cleared"] == [key]


def test_clear_stale_helper_records_and_reports_the_key(ledger):
    key = fin.prepare(_stop(), ledger, resolve_fn=FakeResolve(), now=T)["key"]
    assert fin.clear_stale(ledger, T + 10) is None
    assert fin.clear_stale(ledger, T + fin.STALE_SEC + 1) == key
    data = _read(ledger)
    assert data["in_flight"] is None and data["stale_cleared"] == [key]
    assert fin.clear_stale(ledger, T + fin.STALE_SEC + 2) is None


def test_stale_clear_survives_a_refusal_in_the_same_call(ledger):
    stop = _stop()
    key = fin.prepare(stop, ledger, resolve_fn=FakeResolve(), now=T)["key"]
    fin.clear_in_flight(ledger, key, "resolved")
    fin.prepare(_stop("wall-clock", target=OTHER), ledger, resolve_fn=FakeResolve(), now=T + 1)
    out = fin.prepare(stop, ledger, resolve_fn=FakeResolve(), now=T + fin.STALE_SEC + 5)
    assert out["reason"] == "already-finalized" and len(out["stale_cleared"]) == 1
    assert len(_read(ledger)["stale_cleared"]) == 1


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        '{"in_flight": "oops", "seen": {}, "stale_cleared": []}',
        '{"in_flight": {"key": "halt:x:y:12345678"}, "seen": {}, "stale_cleared": []}',
        '{"in_flight": null, "seen": "no", "stale_cleared": []}',
    ],
)
def test_corrupt_ledger_fails_closed_without_dispatch(ledger, content):
    ledger.parent.mkdir(parents=True)
    ledger.write_text(content, encoding="utf-8")
    resolve = FakeResolve()
    out = fin.prepare(_stop(), ledger, resolve_fn=resolve, now=T)
    assert out["status"] == "refused" and out["reason"] == "ledger-unreadable"
    assert resolve.calls == [] and ledger.read_text(encoding="utf-8") == content


def test_unresolvable_agent_refuses_without_marking_in_flight(ledger):
    def broken(agent):
        raise fin.agent_ref.AgentRefError(agent, "plugin.json not found")

    out = fin.prepare(_stop(), ledger, resolve_fn=broken, now=T)
    assert out["status"] == "refused" and out["reason"] == "agent-unresolved"
    assert "agent-unresolved" in out["detail"]
    assert not ledger.exists() or _read(ledger)["in_flight"] is None


def test_invalid_stop_raises_and_writes_nothing(ledger):
    with pytest.raises(ValueError):
        fin.prepare({"source": "cron", "signal": "x", "target": "t"}, ledger, resolve_fn=FakeResolve())
    assert not ledger.exists()


def test_default_resolve_fn_is_agent_ref_resolve(ledger, monkeypatch):
    monkeypatch.setattr(fin.agent_ref, "resolve", lambda agent, root=None: f"plug:{agent}")
    assert fin.prepare(_stop(), ledger, now=T)["agent_ref"] == "plug:tp-finalizer"


def test_clear_in_flight_records_the_key_as_seen_and_is_idempotent(ledger):
    key = fin.prepare(_stop(), ledger, resolve_fn=FakeResolve(), now=T)["key"]
    assert fin.clear_in_flight(ledger, key, "resolved") is True
    assert fin.clear_in_flight(ledger, key, "resolved") is False
    data = _read(ledger)
    assert data["in_flight"] is None and data["seen"] == {key: "resolved"}


def test_clear_in_flight_never_clears_another_keys_marker(ledger):
    key = fin.prepare(_stop(target=URL), ledger, resolve_fn=FakeResolve(), now=T)["key"]
    assert fin.clear_in_flight(ledger, "pr-iterate:round-cap:" + OTHER, "escalated") is False
    data = _read(ledger)
    assert data["in_flight"]["key"] == key and "pr-iterate:round-cap:" + OTHER in data["seen"]


def test_clear_helpers_on_a_corrupt_ledger_raise(ledger):
    ledger.parent.mkdir(parents=True)
    ledger.write_text("{oops", encoding="utf-8")
    with pytest.raises(fin.LedgerError):
        fin.clear_in_flight(ledger, "halt:a:b:12345678", "resolved")
    with pytest.raises(fin.LedgerError):
        fin.clear_stale(ledger, T)


def test_save_ledger_is_atomic_and_roundtrips(ledger):
    data = {"in_flight": None, "seen": {"k:s:t": "resolved"}, "stale_cleared": []}
    fin.save_ledger(ledger, data)
    assert fin.load_ledger(ledger) == data
    assert [p.name for p in ledger.parent.iterdir()] == [ledger.name]
