"""test_proof_gate_fold.py — review-proof predicate folds into evaluate_gate (B6, B7).

Hermetic: inject runners (incl. comments_fn + self_login_fn) + config; never
calls live gh/git. Covers the gate-fold (B6), the config require-toggle /
OMITTED path (B7), the _require_review_proof interpreter, the trusted-author
fold (review finding on PR #109), and the hermetic-activation guard (p7 is
INACTIVE — never a silent live `gh pr view` — when a hermetic run omits
comments_fn). New file (test_gate_roster_wiring.py is at 478 lines, too close
to the 500 cap to extend).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
_PR_ITERATE = HERE.parent / "tp-pr-iterate" / "scripts"
if str(_PR_ITERATE) not in sys.path:
    sys.path.insert(0, str(_PR_ITERATE))

import review_proof  # noqa: E402
from gate_roster import _require_review_proof  # noqa: E402

PR_URL = "https://github.com/o/r/pull/1"
HEAD = "abc123"
SELF = "framework-bot"  # the runners' gh self login — digests it posts are trusted


def _proof_body(head=HEAD):
    return review_proof.format_proof_digest({
        "base": "base000", "head": head, "files_changed": 3,
        "insertions": 5, "deletions": 1, "degraded": False, "reason": None,
    }, [("correctness", 0)])


def _pc(head=HEAD, author=SELF):
    """One posted proof comment ({"author", "body"}) as the loop would post it."""
    return {"author": author, "body": _proof_body(head)}


def _all_pass_runners(**extra):
    """Runners that yield all-PASS for the OTHER predicates (proof handled per test)."""
    runners = {
        "pr_state_fn": lambda url: {
            "mergeable": "MERGEABLE",
            "headRefOid": HEAD,
            "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        },
        "threads_fn": lambda url: [],
        "reviews_fn": lambda url: [{
            "user": {"login": "copilot-pull-request-reviewer[bot]"},
            "submitted_at": "2024-01-01T00:00:00Z",
            "commit_id": HEAD, "body": "ok", "state": "COMMENTED",
        }],
        "ci_head_fn": lambda url: (HEAD, True),
        "requested_fn": lambda url: [],
        # p7's trusted-author set resolves self hermetically via this shared key.
        "self_login_fn": lambda: SELF,
    }
    runners.update(extra)
    return runners


# require_human_approval:False keeps p5 out so these isolate the proof predicate.
def _cfg(**review):
    r = {"require_human_approval": False}
    r.update(review)
    return {"review": r, "ci": {"expects_github_checks": True}}


def _roster_entry(outcome, name):
    return next((e for e in outcome.roster if e.name == name), None)


# ---------- B6: gate folds the predicate ----------


def test_gate_folds_proof_indeterminate_when_no_comment():
    from deterministic_gate import GateVerdict, evaluate_gate
    outcome = evaluate_gate(
        PR_URL, config=_cfg(), runners=_all_pass_runners(comments_fn=lambda _u: []),
    )
    assert outcome.verdict == GateVerdict.INDETERMINATE
    entry = _roster_entry(outcome, "review_proof_on_head")
    assert entry is not None and entry.status == "INDETERMINATE"


def test_gate_passes_proof_when_head_bound_comment():
    from deterministic_gate import GateVerdict, evaluate_gate
    outcome = evaluate_gate(
        PR_URL, config=_cfg(),
        runners=_all_pass_runners(comments_fn=lambda _u: [_pc()]),
    )
    assert outcome.verdict == GateVerdict.PASS, [p.name for p in outcome.blocking]
    entry = _roster_entry(outcome, "review_proof_on_head")
    assert entry is not None and entry.status == "PASS"


def test_gate_proof_indeterminate_on_moved_head_comment():
    from deterministic_gate import GateVerdict, evaluate_gate
    # Digest for a DIFFERENT head than the live head → not current → INDETERMINATE.
    outcome = evaluate_gate(
        PR_URL, config=_cfg(),
        runners=_all_pass_runners(comments_fn=lambda _u: [_pc("9999999")]),
    )
    assert outcome.verdict == GateVerdict.INDETERMINATE
    entry = _roster_entry(outcome, "review_proof_on_head")
    assert entry.status == "INDETERMINATE"


def test_gate_proof_passes_config_extras_author_with_unresolvable_self():
    """Round-2 mutation pin: gate_roster must THREAD config into p7 — binding
    config=None there passed every gate suite while permanently INDETERMINATE-ing
    repos whose digests are posted by a review.automation_identities identity
    (loop converges via its own config, gate refuses — the divergence bug class)."""
    from deterministic_gate import GateVerdict, evaluate_gate
    outcome = evaluate_gate(
        PR_URL, config=_cfg(automation_identities=["org-ci-bot"]),
        runners=_all_pass_runners(
            comments_fn=lambda _u: [{"author": "org-ci-bot", "body": _proof_body()}],
            self_login_fn=lambda: None,  # unresolvable self — extras carry trust alone
        ),
    )
    entry = _roster_entry(outcome, "review_proof_on_head")
    assert entry is not None and entry.status == "PASS", entry
    assert outcome.verdict == GateVerdict.PASS, [p.name for p in outcome.blocking]


def test_gate_proof_indeterminate_on_untrusted_author():
    """A perfect head-bound digest from a drive-by author does NOT satisfy p7
    (review finding on PR #109) — the gate stays blocked, INDETERMINATE."""
    from deterministic_gate import GateVerdict, evaluate_gate
    outcome = evaluate_gate(
        PR_URL, config=_cfg(),
        runners=_all_pass_runners(
            comments_fn=lambda _u: [_pc(author="drive-by-account")],
        ),
    )
    assert outcome.verdict == GateVerdict.INDETERMINATE
    entry = _roster_entry(outcome, "review_proof_on_head")
    assert entry.status == "INDETERMINATE"
    assert any(p.name == "review_proof_on_head" for p in outcome.blocking)


# ---------- B7: config toggle / OMITTED ----------


def test_proof_predicate_omitted_when_require_false():
    from deterministic_gate import GateVerdict, evaluate_gate
    outcome = evaluate_gate(
        PR_URL, config=_cfg(require_review_proof=False),
        runners=_all_pass_runners(comments_fn=lambda _u: []),  # no proof at all
    )
    # OMITTED → not folded → gate still PASS on the rest.
    assert outcome.verdict == GateVerdict.PASS, [p.name for p in outcome.blocking]
    entry = _roster_entry(outcome, "review_proof_on_head")
    assert entry is not None and entry.status == "OMITTED"
    assert not any(p.name == "review_proof_on_head" for p in outcome.blocking)


def test_proof_default_required_when_absent():
    from deterministic_gate import evaluate_gate
    # Key absent → predicate PRESENT (folded) → roster carries it.
    outcome = evaluate_gate(
        PR_URL, config=_cfg(), runners=_all_pass_runners(comments_fn=lambda _u: []),
    )
    entry = _roster_entry(outcome, "review_proof_on_head")
    assert entry is not None and entry.status != "OMITTED"


def test_proof_inactive_when_hermetic_run_omits_comments_fn():
    """Hermetic runners with NO comments_fn → p7 is INACTIVE (OMITTED with the
    hermetic note), NEVER a silent fallback to live `gh pr view` mid-test
    (review finding on PR #109). Mirrors the stamp/balloon activation guard."""
    from deterministic_gate import GateVerdict, evaluate_gate
    outcome = evaluate_gate(PR_URL, config=_cfg(), runners=_all_pass_runners())
    entry = _roster_entry(outcome, "review_proof_on_head")
    assert entry is not None and entry.status == "OMITTED"
    assert "comments_fn" in entry.detail, entry.detail
    assert not any(p.name == "review_proof_on_head" for p in outcome.blocking)
    # With every ACTIVE predicate passing, the inactive p7 must not block PASS.
    assert outcome.verdict == GateVerdict.PASS, [p.name for p in outcome.blocking]


def test_proof_explicit_none_comments_fn_is_inactive():
    """runners {"comments_fn": None} (key PRESENT, value None) → p7 INACTIVE.

    Round-2 finding on PR #109: with a `"comments_fn" in r` activation check,
    explicit None activated the arm and `comments_fn or _default_comments_fn`
    then fell through to the LIVE gh default mid-hermetic-run. Explicit None
    must read as not-injected (mirrors evaluate_gate's `v is not None`
    COPILOT_KEYS filter)."""
    from deterministic_gate import evaluate_gate
    outcome = evaluate_gate(
        PR_URL, config=_cfg(), runners=_all_pass_runners(comments_fn=None),
    )
    entry = _roster_entry(outcome, "review_proof_on_head")
    assert entry is not None and entry.status == "OMITTED", entry
    assert "comments_fn" in entry.detail
    assert not any(p.name == "review_proof_on_head" for p in outcome.blocking)


def test_proof_active_in_pure_live_mode(monkeypatch):
    """running_live=True with NO comments_fn injected → p7 ACTIVE (not OMITTED).

    Mutation pin (round-2 STRUCTURAL finding on PR #109): deleting
    `or running_live` from gate_roster's p7 activation silently OMITs the
    predicate from every real production gate run — the design's entire
    merge-gate enforcement vanishes while the suite stays green. Sibling of the
    stamp predicate's live-path pin. Hermetic: pred_review_proof_on_head is
    stubbed (find_project_root nulled so balloon/stamp go INDETERMINATE without
    live calls); no live gh."""
    import gate_roster
    import proof_predicate
    from deterministic_gate import FailureClass, GateVerdict, PredicateResult

    monkeypatch.setattr(gate_roster, "find_project_root", lambda: None, raising=False)

    calls = {}

    def fake_pred(pr_url, head_oid, *, comments_fn=None, config=None, self_login_fn=None,
                 run_git=None, derive_base_ref_fn=None, repo_root=None):
        calls["ran"] = True
        calls["comments_fn"] = comments_fn
        return PredicateResult(name="review_proof_on_head",
                               verdict=GateVerdict.PASS, detail="stubbed")

    monkeypatch.setattr(proof_predicate, "pred_review_proof_on_head", fake_pred)

    predicates, roster = gate_roster.build_predicates_and_roster(
        pr_url=PR_URL, rollup=[], failure_class=FailureClass.INDETERMINATE,
        threads=[], mergeable="MERGEABLE", head_oid=HEAD,
        config=_cfg(expects_copilot=False), r={}, copilot_runners=None,
        running_live=True, shared_dir=None,
    )
    entry = next((e for e in roster if e.name == "review_proof_on_head"), None)
    assert entry is not None and entry.status == "PASS", (
        f"p7 must be ACTIVE in pure live mode, got {entry}"
    )
    assert calls.get("ran") is True, "predicate must actually be evaluated live"
    assert calls.get("comments_fn") is None  # live default seam (stubbed here)
    assert any(p.name == "review_proof_on_head" for p in predicates)


# ---------- _require_review_proof interpreter ----------


def test_require_review_proof_default_true():
    assert _require_review_proof(None) is True
    assert _require_review_proof({}) is True
    assert _require_review_proof({"review": {}}) is True


def test_require_review_proof_non_dict_review_true():
    assert _require_review_proof({"review": "garbage"}) is True


def test_require_review_proof_explicit_false():
    assert _require_review_proof({"review": {"require_review_proof": False}}) is False


def test_require_review_proof_explicit_true():
    assert _require_review_proof({"review": {"require_review_proof": True}}) is True


# ---------- own guards ----------


def test_proof_gate_fold_under_cap():
    src = (HERE / "test_proof_gate_fold.py").read_text(encoding="utf-8")
    lines = src.count("\n") + 1
    assert lines <= 500, f"test_proof_gate_fold.py is {lines} lines (cap=500)"
    assert len(src) <= 50000


def test_proof_gate_fold_c1_clean():
    src = (HERE / "test_proof_gate_fold.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = (alias.name or "").lower()
                assert "anthropic" not in name and "claude_agent" not in name
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").lower()
            assert "anthropic" not in module and "claude_agent" not in module
