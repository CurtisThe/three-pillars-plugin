"""test_proof_predicate_handres.py — task 10.1: the review-proof carry passes `carry_handres`.

design: review-convergence (detailed-design-gates.md, gates consumer of the
livingdoc-handres-preserves-approval carry). Oracle: example.

`proof_predicate` walks a certified base-sync chain at TWO sites — `_evaluate`'s direct
carry and `_round_log_carry`'s composed carry. Both must resolve the default-ON
`review.living_doc_handres_preserves_approval` flag through
`living_doc_carry.carry_livingdoc_handres_enabled(config)` and hand it to
`base_sync_cert.find_certified_anchor(carry_handres=...)`, so a living-doc
hand-resolution base-sync keeps carrying the review proof exactly like it keeps carrying
the approval (`human_approval_review.carried_review_approval`, the sibling consumer).

Hermetic: the chain walk and the round-log walk are both replaced by recorders, so no git
subprocess and no live `gh` call is made.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
_PR_ITERATE = HERE.parent / "tp-pr-iterate" / "scripts"
if str(_PR_ITERATE) not in sys.path:
    sys.path.insert(0, str(_PR_ITERATE))

import base_sync_cert  # noqa: E402
import proof_predicate  # noqa: E402
import review_proof  # noqa: E402
import round_log_carry  # noqa: E402
from deterministic_gate import GateVerdict  # noqa: E402

PR = "https://github.com/o/r/pull/1"
AUTHOR = "tp-loop-bot"
DIGEST_HEAD = "a" * 40     # the reviewed head the posted digest binds
RL_ANCHOR = "b" * 40       # the round-log anchor (NOT proof-bearing itself)
HEAD = "c" * 40            # the head under verification


def _c(body, author=AUTHOR):
    return {"author": author, "body": body}


def _digest_for(head):
    meta = {"base": "base000", "head": head, "files_changed": 3, "insertions": 5,
            "deletions": 1, "degraded": False, "reason": None}
    return review_proof.format_proof_digest(meta, [("correctness", 0)])


@dataclass(frozen=True)
class _FakeChain:
    """The shape `base_sync_cert.ChainResult` is read with: never certified here, so the
    predicate stays INDETERMINATE while BOTH call sites are still reached."""
    certified: bool
    anchor: "str | None"
    links: int
    reason: str


def _config(handres):
    """Carry enabled; `handres` None omits the inner key entirely (the default-ON case)."""
    review = {"approval_survives_safe_base_sync": True}
    if handres is not None:
        review["living_doc_handres_preserves_approval"] = handres
    return {"review": review}


def _install_recorders(monkeypatch):
    """Replace both chain walks with recorders. Returns the anchor-call list: one entry per
    `find_certified_anchor` call, in call order."""
    calls = []

    def fake_anchor(repo_root, head, candidates, **kw):
        calls.append({"head": head, "kw": kw})
        return _FakeChain(False, None, 0, "x")

    monkeypatch.setattr(base_sync_cert, "find_certified_anchor", fake_anchor)
    monkeypatch.setattr(
        round_log_carry, "strip_round_log_commits",
        lambda repo_root, head, **kw: round_log_carry.StripResult(RL_ANCHOR, 1, ""),
    )
    return calls


def _run(config, tmp_path):
    return proof_predicate.pred_review_proof_on_head(
        PR, HEAD,
        comments_fn=lambda _u: [_c(_digest_for(DIGEST_HEAD))],
        config=config,
        self_login_fn=lambda: AUTHOR,
        repo_root=str(tmp_path),
        derive_base_ref_fn=lambda _u: "main",
    )


@pytest.mark.parametrize("handres,expected", [
    (True, True),      # literal True → ON
    (False, False),    # literal False → strict-only
    (None, True),      # key absent → default ON
], ids=["on", "off", "absent-default-on"])
def test_both_anchor_calls_receive_carry_handres(monkeypatch, tmp_path, handres, expected):
    """Both `find_certified_anchor` sites — `_evaluate`'s direct carry (head) and
    `_round_log_carry`'s composed carry (the round-log anchor) — receive the resolved flag."""
    calls = _install_recorders(monkeypatch)
    r = _run(_config(handres), tmp_path)

    assert r.verdict == GateVerdict.INDETERMINATE   # the fake chain never certifies
    assert len(calls) == 2, f"expected 2 anchor calls, got {len(calls)}"
    assert calls[0]["head"] == HEAD, "site 1 must be _evaluate's direct carry on head"
    assert calls[1]["head"] == RL_ANCHOR, "site 2 must be _round_log_carry's carry on its anchor"
    for site, call in enumerate(calls, start=1):
        assert call["kw"].get("carry_handres") is expected, (
            f"site {site}: carry_handres={call['kw'].get('carry_handres')!r}, "
            f"expected {expected!r}"
        )


def test_carry_handres_threads_with_the_other_chain_kwargs(monkeypatch, tmp_path):
    """The new kwarg does not disturb the existing chain args (base_ref / max_links /
    run_git still thread through both sites)."""
    calls = _install_recorders(monkeypatch)
    run_git_calls = []

    def run_git(args):
        run_git_calls.append(args)
        return 0, "", ""

    proof_predicate.pred_review_proof_on_head(
        PR, HEAD,
        comments_fn=lambda _u: [_c(_digest_for(DIGEST_HEAD))],
        config=_config(True),
        self_login_fn=lambda: AUTHOR,
        repo_root=str(tmp_path),
        derive_base_ref_fn=lambda _u: "main",
        run_git=run_git,
    )
    assert len(calls) == 2
    for call in calls:
        assert call["kw"].get("base_ref") == "main"
        assert call["kw"].get("max_links") == 5
        assert call["kw"].get("run_git") is run_git
    assert run_git_calls == []   # the fake chain never spawned git
