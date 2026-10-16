"""test_operator_accept_roster.py — the review-proof slot takes PROOF or ACCEPT (E3).

Hermetic `evaluate_gate` runs: the runner dict mirrors test_deterministic_gate.py
(`reviews_fn(url)` / `self_login_fn()` / `head_fn(url)` signatures verbatim) with a
`comments_fn` that carries NO proof digest, plus the `r["accept_fn"]` seam. The accept
stands in for the `review_proof_on_head` slot ONLY — the human-approval predicate stays
required — and a hermetic run with no `accept_fn` never evaluates the accept at all (no
live `gh`, no reading the shared `reviews_fn`). Also unit-pins the `proof_or_accept` fold
(it RETURNS a zero-arg callable — call it) and the `accept_for` seam resolver.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
_PRI = HERE.parent / "tp-pr-iterate" / "scripts"
if str(_PRI) not in sys.path:
    sys.path.insert(0, str(_PRI))

import operator_accept  # noqa: E402
from deterministic_gate import GateVerdict, PredicateResult  # noqa: E402

PR = "https://github.com/o/r/pull/1"
HEAD = "0123456789abcdef0123456789abcdef01234567"  # 40-hex: an accept binds to it exactly
SELF = "framework-bot"  # the runners' gh self login — its digests are trusted
ACCEPT_DETAIL = f"operator-accept by curtis on {HEAD[:7]}: gate lows are fine"


def _copilot_commented():
    return {
        "user": {"login": "copilot-pull-request-reviewer[bot]"},
        "submitted_at": "2026-10-01T00:00:00Z",
        "commit_id": HEAD, "body": "ok", "state": "COMMENTED",
    }


def _approved_human(login="alice", body="LGTM"):
    """A real human APPROVED review current on HEAD — the p5 currency path."""
    return {
        "user": {"login": login, "type": "User"},
        "submitted_at": "2026-10-02T00:00:00Z",
        "commit_id": HEAD, "body": body, "state": "APPROVED",
    }


def _accept_review():
    """An APPROVED human review whose body carries the tp-accept line for HEAD."""
    return _approved_human(login="curtis", body=f"tp-accept: {HEAD} gate lows are fine")


def _proof_comments_fn():
    """comments_fn yielding a head-bound proof digest by the trusted self login."""
    import review_proof  # noqa: E402 — tp-pr-iterate/scripts, on sys.path above

    body = review_proof.format_proof_digest({
        "base": "base000", "head": HEAD, "files_changed": 3,
        "insertions": 5, "deletions": 1, "degraded": False, "reason": None,
    }, [("correctness", 0)])
    return lambda _url: [{"author": SELF, "body": body}]


def _runners(**extra):
    """All-PASS-except-proof runners: comments_fn carries NO proof digest."""
    runners = {
        "pr_state_fn": lambda url: {
            "mergeable": "MERGEABLE",
            "headRefOid": HEAD,
            "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        },
        "threads_fn": lambda url: [],
        "reviews_fn": lambda url: [_copilot_commented()],
        "ci_head_fn": lambda url: (HEAD, True),
        "requested_fn": lambda url: [],
        "self_login_fn": lambda: SELF,
        "head_fn": lambda url: {"headRefOid": HEAD, "commits": []},
        "comments_fn": lambda _url: [],
    }
    runners.update(extra)
    return runners


def _accept_pass():
    return PredicateResult("operator_accept", GateVerdict.PASS, ACCEPT_DETAIL)


def _accept_missing():
    return PredicateResult("operator_accept", GateVerdict.INDETERMINATE,
                           operator_accept.NO_ACCEPT_DETAIL)


def _cfg(**review):
    review.setdefault("require_human_approval", True)
    return {"review": review, "ci": {"expects_github_checks": True}}


def _entry(outcome, name):
    return next((e for e in outcome.roster if e.name == name), None)


# ---------- the roster slot: proof OR accept ----------


def test_accept_makes_the_proof_slot_pass_verbatim():
    from deterministic_gate import evaluate_gate

    outcome = evaluate_gate(PR, config=_cfg(), runners=_runners(accept_fn=_accept_pass))
    entry = _entry(outcome, "review_proof_on_head")
    assert entry is not None and entry.status == "PASS", entry
    assert entry.detail == ACCEPT_DETAIL  # verbatim, so it starts "operator-accept" (11.4)


def test_accept_alone_does_not_pass_the_gate():
    """The accept stands in for p7 ONLY — human approval is still required."""
    from deterministic_gate import GateVerdict, evaluate_gate

    outcome = evaluate_gate(PR, config=_cfg(), runners=_runners(accept_fn=_accept_pass))
    assert outcome.verdict is not GateVerdict.PASS
    assert any(p.name == "human_approved" for p in outcome.blocking), (
        f"human_approved must still block; got {[p.name for p in outcome.blocking]}"
    )


def test_accept_plus_a_real_human_approval_passes_the_gate():
    from deterministic_gate import GateVerdict, evaluate_gate

    outcome = evaluate_gate(
        PR, config=_cfg(),
        runners=_runners(accept_fn=_accept_pass,
                         reviews_fn=lambda url: [_copilot_commented(), _approved_human()]),
    )
    assert outcome.verdict is GateVerdict.PASS, [p.name for p in outcome.blocking]
    assert _entry(outcome, "human_approved").status == "PASS"


def test_proof_pass_wins_and_the_accept_is_never_consulted():
    from deterministic_gate import GateVerdict, evaluate_gate

    consulted = []

    def accept_fn():
        consulted.append(True)
        return _accept_pass()

    outcome = evaluate_gate(
        PR, config=_cfg(require_human_approval=False),
        runners=_runners(comments_fn=_proof_comments_fn(), accept_fn=accept_fn),
    )
    entry = _entry(outcome, "review_proof_on_head")
    assert entry is not None and entry.status == "PASS", entry
    assert entry.detail == "a head-bound proof comment exists on this head", entry.detail
    assert consulted == [], "a PASSing proof must not consult the accept"
    assert outcome.verdict is GateVerdict.PASS, [p.name for p in outcome.blocking]


def test_no_proof_and_no_accept_appends_the_accept_note():
    from deterministic_gate import evaluate_gate

    outcome = evaluate_gate(PR, config=_cfg(),
                            runners=_runners(accept_fn=_accept_missing))
    entry = _entry(outcome, "review_proof_on_head")
    assert entry is not None and entry.status == "INDETERMINATE", entry
    assert entry.detail.endswith("; no operator-accept on head"), entry.detail
    assert any(p.name == "review_proof_on_head" for p in outcome.blocking)


def test_hermetic_run_without_accept_fn_evaluates_no_accept(monkeypatch):
    """No `accept_fn` + hermetic runners → the accept side is a plain INDETERMINATE note.

    Strongest form of the pin: the shared `reviews_fn` here DOES carry a valid
    operator-accept review, so an implementation that quietly ran
    `pred_operator_accept(runners=r)` in a hermetic run would report PASS-by-accept. The
    slot must stay INDETERMINATE, and `operator_accept._build_live_runners` must never be
    reached (no live `gh` from a hermetic run)."""
    from deterministic_gate import evaluate_gate

    hits = []

    def boom(pr_url):
        hits.append(pr_url)
        raise AssertionError("live runners built in a hermetic run")

    monkeypatch.setattr(operator_accept, "_build_live_runners", boom)
    outcome = evaluate_gate(
        PR, config=_cfg(),
        runners=_runners(reviews_fn=lambda url: [_copilot_commented(), _accept_review()]),
    )
    entry = _entry(outcome, "review_proof_on_head")
    assert entry is not None and entry.status == "INDETERMINATE", entry
    assert entry.detail.endswith("; no operator-accept on head"), entry.detail
    assert hits == [], "operator_accept._build_live_runners must never be reached"


# ---------- the fold itself ----------


def test_proof_or_accept_returns_a_callable_and_proof_pass_wins():
    folded = operator_accept.proof_or_accept(
        lambda: PredicateResult("review_proof_on_head", GateVerdict.PASS, "proof detail"),
        lambda: _accept_pass())
    result = folded()
    assert result.verdict is GateVerdict.PASS
    assert result.name == "review_proof_on_head"
    assert result.detail == "proof detail"


def test_proof_or_accept_accept_pass_keeps_the_slots_name():
    result = operator_accept.proof_or_accept(
        lambda: PredicateResult("review_proof_on_head", GateVerdict.INDETERMINATE,
                                "no proof"),
        lambda: _accept_pass())()
    assert result.name == "review_proof_on_head"
    assert result.verdict is GateVerdict.PASS
    assert result.detail == ACCEPT_DETAIL


def test_proof_or_accept_neither_pass_appends_the_note():
    result = operator_accept.proof_or_accept(
        lambda: PredicateResult("review_proof_on_head", GateVerdict.INDETERMINATE,
                                "no proof"),
        lambda: _accept_missing())()
    assert result.verdict is GateVerdict.INDETERMINATE
    assert result.name == "review_proof_on_head"
    assert result.detail == "no proof; no operator-accept on head"


def test_proof_or_accept_is_total_when_both_sides_raise():
    def boom():
        raise RuntimeError("boom")

    result = operator_accept.proof_or_accept(boom, boom)()
    assert result.verdict is GateVerdict.INDETERMINATE
    assert result.name == "review_proof_on_head"
    assert result.detail.endswith("; no operator-accept on head"), result.detail


# ---------- the accept_for seam resolver ----------


def test_accept_for_prefers_the_injected_seam():
    thunk = operator_accept.accept_for(PR, HEAD, {"accept_fn": _accept_pass}, {}, False)
    assert thunk().detail == ACCEPT_DETAIL


def test_accept_for_live_calls_the_predicate_with_the_same_runners(monkeypatch):
    seen = {}

    def fake_pred(pr_url, head_oid, *, runners=None, config=None):
        seen["args"] = (pr_url, head_oid)
        seen["runners"] = runners
        seen["config"] = config
        return _accept_pass()

    monkeypatch.setattr(operator_accept, "pred_operator_accept", fake_pred)
    runners = {"self_login_fn": lambda: SELF}
    config = {"review": {}}
    assert operator_accept.accept_for(PR, HEAD, runners, config, True)().verdict is (
        GateVerdict.PASS)
    assert seen["args"] == (PR, HEAD)
    assert seen["runners"] is runners
    assert seen["config"] is config


def test_accept_for_hermetic_without_seam_is_a_plain_indeterminate():
    result = operator_accept.accept_for(PR, HEAD, {}, None, False)()
    assert result.verdict is GateVerdict.INDETERMINATE
    assert result.detail == operator_accept.NO_ACCEPT_DETAIL


# ---------- own guards ----------


def test_roster_and_helper_files_stay_within_their_caps():
    for name, cap in (("gate_roster.py", 485), ("operator_accept.py", 260),
                      ("test_operator_accept_roster.py", 300)):
        src = (HERE / name).read_text(encoding="utf-8")
        lines = src.count("\n") + 1
        assert lines <= cap, f"{name} is {lines} lines (cap={cap})"
        assert len(src) <= 50000, f"{name} is {len(src)} chars"
