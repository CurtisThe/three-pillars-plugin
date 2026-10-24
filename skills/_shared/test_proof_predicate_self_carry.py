"""test_proof_predicate_self_carry.py — the carries see the same trust set under `self`.

design: per-developer-automation-account, Task 1.5 (behaviours 6, 8)

The round-log carry and the base-sync carry both read the trusted heads, so the PR author's digest
on the anchor carries too, and the carry detail names the self-attested anchor, but only when no
base-set digest is on that anchor. Hermetic: the chain walk and the round-log walk are recorders.

Run with: pytest skills/_shared/test_proof_predicate_self_carry.py -q
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

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
H = "a" * 40
OLD = "b" * 40
SELF_DETAIL = "self-attested digest by Alice (per_developer_author: self)"
CFG = {"github": {"pr_author_account": "TeamBot", "per_developer_author": "self"}}
CFG_CARRY = {**CFG, "review": {"approval_survives_safe_base_sync": True}}


@dataclass(frozen=True)
class _Chain:
    certified: bool
    anchor: "str | None"
    links: int
    reason: str


def _boom(*_a, **_k):
    raise AssertionError("must not be called")


def _digest(head):
    meta = {"base": "base000", "head": head, "files_changed": 3, "insertions": 5,
            "deletions": 1, "degraded": False, "reason": None}
    return review_proof.format_proof_digest(meta, [("correctness", 0)])


def _comments(*pairs):
    items = [{"author": a, "body": "summary\n" + _digest(h)} for a, h in pairs]
    return lambda _url: items


def _run(config, comments_fn, tmp_path):
    return proof_predicate.pred_review_proof_on_head(
        PR, H, comments_fn=comments_fn, config=config, self_login_fn=_boom,
        head_fn=lambda _u: {"author": {"login": "Alice"}, "isCrossRepository": False},
        repo_root=str(tmp_path), derive_base_ref_fn=lambda _u: "main")


def _patch_strip(monkeypatch):
    monkeypatch.setattr(round_log_carry, "strip_round_log_commits",
                        lambda root, head, **kw: round_log_carry.StripResult(OLD, 1, ""))


def _patch_chain(monkeypatch):
    monkeypatch.setattr(base_sync_cert, "find_certified_anchor",
                        lambda root, head, heads, **kw: _Chain(True, OLD, 1, ""))


def test_the_round_log_carry_names_the_self_attested_anchor(monkeypatch, tmp_path):
    _patch_strip(monkeypatch)
    r = _run(CFG, _comments(("alice", OLD)), tmp_path)
    assert r.verdict == GateVerdict.PASS
    assert r.detail == (f"proof comment carried across 1 round-log commit(s) "
                        f"(anchor {OLD[:7]}); {SELF_DETAIL}")


def test_the_base_sync_carry_names_the_self_attested_anchor(monkeypatch, tmp_path):
    _patch_chain(monkeypatch)
    r = _run(CFG_CARRY, _comments(("alice", OLD)), tmp_path)
    assert r.verdict == GateVerdict.PASS
    assert r.detail.endswith(f"; {SELF_DETAIL}")


def test_a_base_set_digest_on_the_anchor_keeps_todays_carry_detail(monkeypatch, tmp_path):
    _patch_chain(monkeypatch)
    r = _run(CFG_CARRY, _comments(("alice", OLD), ("teambot", OLD)), tmp_path)
    assert r.verdict == GateVerdict.PASS
    assert "self-attested" not in r.detail
