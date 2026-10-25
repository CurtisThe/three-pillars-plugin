"""Tests for finalizer_cli prepare / apply — grant, post-hoc, fallback, idempotence.

design: fable-first-stops (Task 2.1). Every seam is injected: no live `gh`, no git,
no agent spawn. The escalate side lives in test_finalizer_cli_escalate.py.
Run with: python3 -m pytest skills/_shared/test_finalizer_cli_apply.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
sys.path.insert(0, str(_SHARED))

import finalizer_cli as cli  # noqa: E402
import finalizer_ruling as fr  # noqa: E402

T = 1_800_000_000.0
URL = "https://github.com/acme/widgets/pull/42"
HEAD, CHILD = "a1" * 20, "b2" * 20
PHASE = {"round-cap": "budget-exhausted", "wall-clock": "cap-exhausted",
         "growth-lines": "budget-exhausted"}


class Rec:
    """Records the gh effects in call order; the state/git seams are canned."""

    def __init__(self, pr_state=None, ancestor=True):
        self.calls = []
        self.pr_state = pr_state or {"state": "OPEN", "headRefOid": CHILD}
        self.ancestor = ancestor

    def kwargs(self):
        return {"comment_fn": lambda u, b: self.calls.append(("comment", u, b)) or True,
                "label_fn": lambda u, lb: self.calls.append(("label", u, lb)) or True,
                "resolve_fn": lambda a: f"three-pillars:{a}",
                "pr_state_fn": lambda u: self.pr_state,
                "is_ancestor_fn": lambda a, b: self.ancestor, "now": T}

    def kinds(self):
        return [c[0] for c in self.calls]


def run(capsys, rec, *argv):
    rc = cli.main([str(a) for a in argv], **rec.kwargs())
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    return rc, (json.loads(lines[-1]) if lines else None)


def stop_of(signal="round-cap", measured=8, limit=6, **extra):
    detail = {"iteration": 8, "round_cap": 6, "signal": signal, "measured": measured,
              "limit": limit, "holding": [signal]}
    return {"source": "pr-iterate", "signal": signal, "target": URL, "head": HEAD,
            "detail": detail, **extra}


def reply_of(tmp, outcome="resolved", **extra):
    body = {"outcome": outcome, "actions": ["fix", "confirm"], "diagnosis": "d",
            "reasoning": "r (vision.md)",
            "demoted": ["L1 fragile needle"], "blocked": [], **fr.EMPTY_RULING, **extra}
    path = tmp / "reply.txt"
    path.write_text("```json\n" + json.dumps(body) + "\n```\n", encoding="utf-8")
    return path


def state_at(tmp, signal="round-cap", **extra):
    st = {"phase": PHASE[signal], "termination_reason": signal, "iteration": 8,
          "reproduced_blockers": 1, **extra}
    path = tmp / "iterate-state.json"
    path.write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")
    return path


def cap6(tmp):
    """keep-the-pin: the asserted 6→8/10 numbers predate the review-weight cap of 3."""
    path = tmp / "cap6.json"
    path.write_text(json.dumps({"pdw": {"guards": {"round_cap": 6}}}), encoding="utf-8")
    return path


def apply_args(tmp, stop, *more, reply=None):
    return ["apply", "--stop", json.dumps(stop), "--ledger", tmp / "ledger.json",
            "--reply", reply or reply_of(tmp), "--decisions", tmp / "decisions.md",
            "--config", cap6(tmp), *more]


def prep(capsys, rec, tmp, stop):
    rc, out = run(capsys, rec, "prepare", "--stop", json.dumps(stop), "--ledger", tmp / "ledger.json")
    assert (rc, out["status"]) == (0, "dispatch")
    return out


def ledger(tmp):
    return json.loads((tmp / "ledger.json").read_text(encoding="utf-8"))


def entries(tmp):
    return (tmp / "decisions.md").read_text(encoding="utf-8").count("### [finalizer]")


def test_prepare_prints_the_dispatch_spec(capsys, tmp_path):
    out = prep(capsys, Rec(), tmp_path, stop_of())
    assert out["agent_ref"] == "three-pillars:tp-finalizer" and out["model"] == "fable"
    assert ledger(tmp_path)["in_flight"]["key"] == out["key"]


def test_prepare_same_target_in_flight_is_a_silent_noop(capsys, tmp_path):
    rec = Rec()
    prep(capsys, rec, tmp_path, stop_of())
    rc, out = run(capsys, rec, "prepare", "--stop", json.dumps(stop_of("wall-clock")),
                  "--ledger", tmp_path / "ledger.json")
    assert (rc, out["status"], out["reason"]) == (0, "noop", "in-flight-same-target")
    assert rec.calls == []


def test_prepare_refusal_exits_3(capsys, tmp_path):
    rec = Rec()
    prep(capsys, rec, tmp_path, stop_of())
    other = dict(stop_of(), target="https://github.com/acme/widgets/pull/43")
    rc, out = run(capsys, rec, "prepare", "--stop", json.dumps(other), "--ledger", tmp_path / "ledger.json")
    assert (rc, out["status"], out["reason"]) == (3, "refused", "nested")


@pytest.mark.parametrize("signal,measured,limit,expect", [
    ("round-cap", 8, 6, {"signal": "round-cap", "from": 8, "to": 10}),
    ("wall-clock", 15000, 14400, {"signal": "wall-clock", "from": 14400, "to": 21600}),
    ("growth-lines", 200, 150, {"signal": "growth-lines", "from": 1.5, "to": 2.25}),
])
def test_resolved_writes_the_grant_and_leaves_phase(capsys, tmp_path, monkeypatch, signal, measured, limit, expect):
    monkeypatch.chdir(tmp_path)  # no repo config here: the loader falls back to the defaults
    stop, rec = stop_of(signal, measured, limit), Rec()
    prep(capsys, rec, tmp_path, stop)
    state = state_at(tmp_path, signal)
    rc, out = run(capsys, rec, *apply_args(tmp_path, stop, "--state", state))
    assert (rc, out) == (0, {"outcome": "resolved", "extension": expect})
    written = json.loads(state.read_text(encoding="utf-8"))
    assert written["budget_extensions"][signal]["limit"] == expect["to"]
    assert written["budget_extensions"][signal]["key"] == cli.fin.stop_key(stop)
    assert isinstance(written["budget_extensions"][signal]["at"], str)
    assert (written["phase"], written["termination_reason"]) == (PHASE[signal], signal)
    assert ledger(tmp_path)["in_flight"] is None and entries(tmp_path) == 1
    assert sorted(p.name for p in tmp_path.glob("iterate-state*")) == ["iterate-state.json"]


def test_limits_come_from_config_not_the_defaults(capsys, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"pdw": {"guards": {"wall_clock_sec": 28800}}}), encoding="utf-8")
    stop, rec = stop_of("wall-clock", 30000, 28800), Rec()
    prep(capsys, rec, tmp_path, stop)
    state = state_at(tmp_path, "wall-clock")
    _, out = run(capsys, rec, *apply_args(tmp_path, stop, "--state", state, "--config", cfg))
    assert out["extension"] == {"signal": "wall-clock", "from": 28800, "to": 36000}
    assert json.loads(state.read_text(encoding="utf-8"))["budget_extensions"]["wall-clock"]["limit"] == 36000


@pytest.mark.parametrize("signal,measured,limit,iteration", [
    ("growth-lines", 400, 150, 8),  # a fix pushed growth past the 2.25 step (225 lines)
    ("round-cap", 12, 6, 12),  # measured + 2 clamps at 2x configured = 12
])
def test_insufficient_grant_escalates_and_writes_nothing(capsys, tmp_path, monkeypatch, signal, measured, limit, iteration):
    monkeypatch.chdir(tmp_path)
    stop, rec = stop_of(signal, measured, limit), Rec()
    prep(capsys, rec, tmp_path, stop)
    state = state_at(tmp_path, signal, iteration=iteration)
    before = state.read_bytes()
    _, out = run(capsys, rec, *apply_args(tmp_path, stop, "--state", state, "--pr-url", URL))
    assert out["outcome"] == "escalate" and "extension-insufficient" in out["problems"]
    assert state.read_bytes() == before
    text = (tmp_path / "decisions.md").read_text(encoding="utf-8")
    assert "extension-insufficient" in text and "**Decided**: resolved" not in text
    assert rec.kinds() == ["comment", "label"]


@pytest.mark.parametrize("state_signal", [None, "wall-clock"])
def test_state_that_is_not_that_terminal_is_untouched(capsys, tmp_path, monkeypatch, state_signal):
    monkeypatch.chdir(tmp_path)
    stop, rec = stop_of(), Rec()
    prep(capsys, rec, tmp_path, stop)
    state = state_at(tmp_path, state_signal or "round-cap")
    if state_signal is None:  # already converged: back in review, no termination reason
        state.write_text(json.dumps({"phase": "awaiting-review", "termination_reason": None}), encoding="utf-8")
    before = state.read_bytes()
    rc, out = run(capsys, rec, *apply_args(tmp_path, stop, "--state", state))
    assert (rc, out) == (0, {"outcome": "resolved", "extension": None})
    assert state.read_bytes() == before


def test_resolved_with_a_pr_posts_exactly_one_note(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stop, rec = stop_of(), Rec()
    prep(capsys, rec, tmp_path, stop)
    run(capsys, rec, *apply_args(tmp_path, stop, "--state", state_at(tmp_path), "--pr-url", URL))
    assert rec.kinds() == ["comment"] and rec.calls[0][1] == URL
    body = rec.calls[0][2]
    assert "fix, confirm" in body and "round-cap 8 → 10" in body and "L1 fragile needle" in body


@pytest.mark.parametrize("rec,violation", [
    (Rec(pr_state={"state": "merged", "headRefOid": CHILD}), "pr-merged"),
    (Rec(ancestor=False), "head-rewritten"),
])
def test_posthoc_violation_escalates_before_any_grant(capsys, tmp_path, monkeypatch, rec, violation):
    monkeypatch.chdir(tmp_path)
    stop = stop_of()
    prep(capsys, rec, tmp_path, stop)
    state = state_at(tmp_path)
    before = state.read_bytes()
    _, out = run(capsys, rec, *apply_args(tmp_path, stop, "--state", state, "--pr-url", URL))
    assert out["outcome"] == "escalate" and f"finalizer-violation: {violation}" in out["problems"]
    assert state.read_bytes() == before and rec.kinds() == ["comment", "label"]


def test_unverifiable_posthoc_is_recorded_not_escalated(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rec = Rec()
    rec.kwargs = lambda base=rec.kwargs: {**base(), "pr_state_fn": lambda u: None}
    stop = stop_of()
    prep(capsys, rec, tmp_path, stop)
    _, out = run(capsys, rec, *apply_args(tmp_path, stop, "--state", state_at(tmp_path), "--pr-url", URL))
    assert out["outcome"] == "resolved"
    assert "post-hoc unverified" in (tmp_path / "decisions.md").read_text(encoding="utf-8")


def test_opus_fallback_is_logged(capsys, tmp_path):
    stop, rec = stop_of(), Rec()
    prep(capsys, rec, tmp_path, stop)
    run(capsys, rec, *apply_args(tmp_path, stop, "--model-used", "opus", "--fallback-reason", "fable-unavailable"))
    text = (tmp_path / "decisions.md").read_text(encoding="utf-8")
    assert "finalizer-fallback" in text and "fable-unavailable" in text


def test_second_apply_for_the_same_key_is_a_noop(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stop, rec = stop_of(), Rec()
    prep(capsys, rec, tmp_path, stop)
    state = state_at(tmp_path)
    argv = apply_args(tmp_path, stop, "--state", state, "--pr-url", URL)
    run(capsys, rec, *argv)
    after_first, calls = state.read_bytes(), list(rec.calls)
    rc, out = run(capsys, rec, *argv)
    assert (rc, out["status"], out["outcome"]) == (0, "noop", "resolved")
    assert entries(tmp_path) == 1 and rec.calls == calls and state.read_bytes() == after_first


def test_unparseable_reply_escalates(capsys, tmp_path):
    stop, rec = stop_of(), Rec()
    prep(capsys, rec, tmp_path, stop)
    bad = tmp_path / "bad.txt"
    bad.write_text("not json", encoding="utf-8")
    _, out = run(capsys, rec, *apply_args(tmp_path, stop, reply=bad))
    assert out["outcome"] == "escalate" and "finalizer-errored" in out["problems"][0]


def test_state_write_failure_escalates_and_keeps_the_state(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stop, rec = stop_of(), Rec()
    prep(capsys, rec, tmp_path, stop)
    state = state_at(tmp_path)
    before = state.read_bytes()

    def boom(*_a):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    _, out = run(capsys, rec, *apply_args(tmp_path, stop, "--state", state))
    assert out["outcome"] == "escalate" and "extension-unwritable" in out["problems"]
    assert state.read_bytes() == before


def test_malformed_stop_is_a_usage_error(capsys, tmp_path):
    rc, _ = run(capsys, Rec(), "prepare", "--stop", '{"source": "nope"}', "--ledger", tmp_path / "l.json")
    assert rc == 2 and not (tmp_path / "l.json").exists()


def test_pr_iterate_apply_without_state_escalates_extension_unwritable(capsys, tmp_path):
    stop, rec = stop_of(), Rec()
    prep(capsys, rec, tmp_path, stop)
    _, out = run(capsys, rec, *apply_args(tmp_path, stop))
    assert out["outcome"] == "escalate" and out["problems"] == ["extension-unwritable"], (
        f"stateless pr-iterate apply was not refused a grant: {out}")
    assert out["extension"] is None and ledger(tmp_path)["seen"][cli.fin.stop_key(stop)] == "escalate"
    assert [(c[0], c[1]) for c in rec.calls] == [("comment", URL), ("label", URL)]
    assert "--state" in rec.calls[0][2]


def test_pr_iterate_apply_without_pr_url_notes_the_target(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stop, rec = stop_of(), Rec()
    prep(capsys, rec, tmp_path, stop)
    _, out = run(capsys, rec, *apply_args(tmp_path, stop, "--state", state_at(tmp_path)))
    assert out["outcome"] == "resolved" and out["extension"] is not None
    assert rec.kinds() == ["comment"] and rec.calls[0][1] == URL
