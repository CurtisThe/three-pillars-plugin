"""Tests for T1.5: dispose pointer in /tp-merge refusal.

When the merge gate blocks because threads_resolved is in the blocking set,
land() must additionally print a pointer to:
  `/tp-pr-iterate {design} --dispose-only`

When the blocking set does NOT include threads_resolved, no pointer is printed
(no spurious noise).

pred_threads_resolved and require_merge_gate_pass are NOT modified.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_MD = HERE.parent / "SKILL.md"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "tp-merge-from-main" / "scripts"))
sys.path.insert(0, str(HERE.parent.parent / "_shared"))

import land  # noqa: E402
from merge_gate import MergeGateBlocked  # noqa: E402


PR_URL = "https://github.com/example/repo/pull/7"


class _FakePred:
    def __init__(self, name, detail):
        self.name = name
        self.detail = detail


class _FakeOutcome:
    def __init__(self, blocking):
        self.blocking = blocking

        class _V:
            value = "FAIL"

        self.verdict = _V()


def _blocked_on_threads(extra_preds=None):
    blockers = [_FakePred("threads_resolved", "1 unresolved thread(s)")]
    if extra_preds:
        blockers.extend(extra_preds)
    return _FakeOutcome(blockers)


def _blocked_on_human_only():
    return _FakeOutcome([_FakePred("human_approved",
                                   "get an APPROVED PR review on the current head from a "
                                   "non-automation human (see human-approval-howto.md)")])


# ---------- positive: dispose pointer printed when threads_resolved blocks ----------


def test_dispose_pointer_printed_when_threads_resolved_blocks(capsys):
    """When threads_resolved is in the blocking set, the dispose pointer is printed."""
    def require_fn(pr_url, *, config=None):
        raise MergeGateBlocked(_blocked_on_threads())

    rc = land.land(PR_URL, require_fn=require_fn, merge_fn=lambda u: None)
    assert rc == 2
    out = capsys.readouterr().out
    assert "--dispose-only" in out, (
        "When threads_resolved blocks, land() must print a pointer to --dispose-only"
    )
    assert "/tp-pr-iterate" in out, (
        "When threads_resolved blocks, land() must name /tp-pr-iterate in the pointer"
    )


def test_dispose_pointer_includes_design_placeholder(capsys):
    """The dispose pointer must include a {design} placeholder so operators know
    how to run it: `/tp-pr-iterate {design} --dispose-only`."""
    def require_fn(pr_url, *, config=None):
        raise MergeGateBlocked(_blocked_on_threads())

    land.land(PR_URL, require_fn=require_fn, merge_fn=lambda u: None)
    out = capsys.readouterr().out
    # Should contain something like "/tp-pr-iterate {design} --dispose-only"
    assert "--dispose-only" in out and "/tp-pr-iterate" in out, (
        "dispose pointer must include both /tp-pr-iterate and --dispose-only"
    )


# ---------- negative: no pointer when threads_resolved does NOT block ----------


def test_no_dispose_pointer_when_only_human_approved_blocks(capsys):
    """When threads_resolved is NOT in the blocking set, dispose pointer is NOT printed."""
    def require_fn(pr_url, *, config=None):
        raise MergeGateBlocked(_blocked_on_human_only())

    rc = land.land(PR_URL, require_fn=require_fn, merge_fn=lambda u: None)
    assert rc == 2
    out = capsys.readouterr().out
    # Should mention human_approved in the refusal
    assert "human_approved" in out
    # Must NOT spuriously print the dispose pointer
    assert "--dispose-only" not in out, (
        "When only human_approved blocks (not threads_resolved), "
        "the dispose pointer must NOT be printed (no spurious noise)"
    )


def test_no_dispose_pointer_on_gate_pass(capsys):
    """On a PASSING gate, no dispose pointer is emitted."""
    def require_fn(pr_url, *, config=None):
        return object()  # PASS

    rc = land.land(PR_URL, require_fn=require_fn, merge_fn=lambda u: None)
    assert rc == 0
    out = capsys.readouterr().out
    assert "--dispose-only" not in out, (
        "On a PASSING gate, no dispose pointer should be emitted"
    )


# ---------- SKILL.md invariant: threads_resolved line documents the pointer ----------


def test_skill_md_threads_resolved_documents_dispose_pointer():
    """The threads_resolved predicate line in SKILL.md must reference --dispose-only."""
    text = SKILL_MD.read_text(encoding="utf-8")
    # Find the threads_resolved predicate description
    assert "threads_resolved" in text, "SKILL.md must document the threads_resolved predicate"
    assert "--dispose-only" in text, (
        "SKILL.md must document that threads_resolved refusal points to --dispose-only"
    )
    # Both must appear in the same vicinity (within the predicate list or merge gate section)
    tr_idx = text.find("threads_resolved")
    do_idx = text.find("--dispose-only")
    # The dispose-only reference should appear close to threads_resolved (within 1000 chars)
    assert abs(tr_idx - do_idx) < 2000, (
        "The --dispose-only pointer must be documented near the threads_resolved predicate "
        "in SKILL.md (within 2000 chars)"
    )
