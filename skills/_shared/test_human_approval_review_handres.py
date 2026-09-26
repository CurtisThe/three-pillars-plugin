"""Consumer wiring test (Phase 3, task 3.3): `human_approval_review.carried_review_approval`
resolves the default-ON `carry_handres` flag, passes it to `certified_noop_chain`, and appends
the K-files detail ONLY when `result.carry_paths` is non-empty (empty-K stays byte-compatible
with today's carry message). Split from the ~261-line `test_human_approval_review.py` to keep
both files under the cap; mirrors `test_approval_carry.py::TestCarriedReviewApproval`'s
fixture-repo + injected-runner idiom.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(HERE / "fixtures") not in sys.path:
    sys.path.insert(0, str(HERE / "fixtures"))

import base_sync_oracle  # noqa: E402
from base_sync_repo import (  # noqa: E402
    build_scenario,
    diverge_base_only,
    diverge_living_doc,
    force_merge_commit,
    make_certified_sync_merge,
)

KI = "three-pillars-docs/known_issues.md"
_HAND_KEEP_ALL = (
    "# Fixture Living Doc\n\n### Z0: seed entry\nseed body line.\n"
    "- **2026-01-01** — base-side change\n- **2026-01-02** — design-side change\n"
)
_CARRY_ON = {"review": {"approval_survives_safe_base_sync": True}}          # inner key absent → ON
_CARRY_OFF = {"review": {"approval_survives_safe_base_sync": True,
                         "living_doc_handres_preserves_approval": False}}   # literal False → OFF


def _review(commit_id, state="APPROVED", login="alice"):
    return {"user": {"login": login, "type": "User"}, "state": state,
            "submitted_at": "2026-06-08T14:00:00Z", "commit_id": commit_id}


def _head(oid):
    return {"headRefOid": oid, "commits": []}


def _seat(s, monkeypatch):
    s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
    s.git("checkout", "--quiet", "-B", s.base_ref, f"origin/{s.base_ref}", check=True)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)


def _handres_chain(tmp_path, monkeypatch):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h0 = s.head()
    h1 = force_merge_commit(s, {KI: _HAND_KEEP_ALL})
    _seat(s, monkeypatch)
    return s, h0, h1


def test_handres_default_on_appends_k_files_clause(tmp_path, monkeypatch):
    from human_approval_review import carried_review_approval

    s, h0, h1 = _handres_chain(tmp_path, monkeypatch)
    ok, detail = carried_review_approval(
        [_review(commit_id=h0)], _head(h1), automation=frozenset({"github-actions"}),
        config=_CARRY_ON, repo_root=str(s.repo_dir), base_ref=s.base_ref)
    assert ok is True
    assert detail == (
        f"approval carried across 1 certified base-sync merge(s) (anchor {h0[:7]}); "
        "living-doc hand-resolution certified code-unchanged (1 doc files)"
    )


def test_handres_literal_false_strict_only_refuses(tmp_path, monkeypatch):
    from human_approval_review import carried_review_approval

    s, h0, h1 = _handres_chain(tmp_path, monkeypatch)
    ok, detail = carried_review_approval(
        [_review(commit_id=h0)], _head(h1), automation=frozenset(),
        config=_CARRY_OFF, repo_root=str(s.repo_dir), base_ref=s.base_ref)
    assert ok is False
    assert detail == "resolved bytes do not match h1's committed blob"


def test_empty_k_omits_clause_byte_compatible(tmp_path, monkeypatch):
    """A pure mechanical no-op carry (K=0) under default-ON: the K-files clause is OMITTED, so
    the message is byte-identical to today's carry detail."""
    from human_approval_review import carried_review_approval

    s = build_scenario(tmp_path)
    diverge_base_only(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)   # clean strict-certifiable link, K=0
    _seat(s, monkeypatch)
    ok, detail = carried_review_approval(
        [_review(commit_id=h0)], _head(h1), automation=frozenset(),
        config=_CARRY_ON, repo_root=str(s.repo_dir), base_ref=s.base_ref)
    assert ok is True
    assert detail == f"approval carried across 1 certified base-sync merge(s) (anchor {h0[:7]})"
    assert "hand-resolution" not in detail
