"""Exhaustive both-direction tests for citation_frozen.is_frozen.

A false "live" blocks every commit; a false "frozen" lets rot through. One
fixture per exemption clause + adversarial near-misses, plus the False-frozen
guard (live surfaces must classify live). History-boundary scenarios live in
test_citation_frozen_history.py.

design: invariant-citation-coherence
"""

from __future__ import annotations

import citation_frozen
from citation_frozen import LIVE_GLOBS, is_frozen
from citation_liveness import _in_history as liveness_in_history

# A representative live cite line (out-of-range invariant #99) used across cases.
CITE = "See invariant #99 for the rule."


# ------------------------------------------------------------------ #
# Reuse contract: citation_frozen re-exports citation_liveness._in_history.
# ------------------------------------------------------------------ #


def test_in_history_is_reused_not_reimplemented():
    # The boundary predicate is the SAME object as citation_liveness._in_history.
    assert citation_frozen._in_history is liveness_in_history


# ------------------------------------------------------------------ #
# False-live guard — each clause MUST classify FROZEN.
# ------------------------------------------------------------------ #


def test_clause1_completed_tp_designs_is_frozen():
    p = "three-pillars-docs/completed-tp-designs/some-design/design.md"
    assert is_frozen(p, CITE, in_history=False, in_fence=False) is True


def test_clause1_superseded_tp_designs_is_frozen():
    p = "three-pillars-docs/superseded-tp-designs/old-design/design.md"
    assert is_frozen(p, CITE, in_history=False, in_fence=False) is True


def test_clause2_in_flight_tp_designs_log_is_frozen():
    p = "three-pillars-docs/tp-designs/some-design/decisions.md"
    assert is_frozen(p, CITE, in_history=False, in_fence=False) is True


def test_clause3_known_issues_resolved_is_frozen():
    p = "three-pillars-docs/known_issues_resolved.md"
    assert is_frozen(p, CITE, in_history=False, in_fence=False) is True


def test_clause4_in_history_is_frozen():
    # A live-glob path, but the caller flagged in_history=True.
    p = "three-pillars-docs/architecture.md"
    assert is_frozen(p, CITE, in_history=True, in_fence=False) is True


def test_clause5_date_prefixed_bullet_is_frozen():
    p = "three-pillars-docs/known_issues.md"
    line = "- 2026-06-12 — bumped invariant #99 in the changelog."
    assert is_frozen(p, line, in_history=False, in_fence=False) is True


def test_clause5_date_prefixed_no_bullet_is_frozen():
    p = "three-pillars-docs/known_issues.md"
    line = "2026-06-12 invariant #99 landed."
    assert is_frozen(p, line, in_history=False, in_fence=False) is True


def test_clause5_date_prefixed_star_bullet_is_frozen():
    p = "three-pillars-docs/known_issues.md"
    line = "* 2026-06-12 invariant #99 was added."
    assert is_frozen(p, line, in_history=False, in_fence=False) is True


def test_clause6_in_fence_is_frozen():
    p = "SECURITY.md"
    assert is_frozen(p, CITE, in_history=False, in_fence=True) is True


# ------------------------------------------------------------------ #
# Adversarial near-misses.
# ------------------------------------------------------------------ #


def test_adversarial_mid_sentence_date_is_NOT_frozen():
    # A live line that merely CONTAINS a date mid-sentence must NOT be frozen
    # (the date is not at the start of the line).
    p = "SECURITY.md"
    line = "We added invariant #99 on 2026-06-12 to the suite."
    assert is_frozen(p, line, in_history=False, in_fence=False) is False


# ------------------------------------------------------------------ #
# False-frozen guard — live surfaces MUST classify LIVE.
# ------------------------------------------------------------------ #


def test_security_md_body_is_live():
    assert is_frozen("SECURITY.md", CITE, in_history=False, in_fence=False) is False


def test_claude_md_is_live():
    assert is_frozen("CLAUDE.md", CITE, in_history=False, in_fence=False) is False


def test_skill_md_is_live():
    p = "skills/tp-design/SKILL.md"
    assert is_frozen(p, CITE, in_history=False, in_fence=False) is False


def test_architecture_md_body_outside_history_is_live():
    p = "three-pillars-docs/architecture.md"
    assert is_frozen(p, CITE, in_history=False, in_fence=False) is False


def test_framework_check_self_cite_is_live():
    assert is_frozen("framework-check.sh", CITE, in_history=False, in_fence=False) is False


# ------------------------------------------------------------------ #
# LIVE_GLOBS sanity.
# ------------------------------------------------------------------ #


def test_live_globs_contains_core_surfaces():
    assert "SECURITY.md" in LIVE_GLOBS
    assert "CLAUDE.md" in LIVE_GLOBS
    assert "framework-check.sh" in LIVE_GLOBS
    assert "skills/**/*.md" in LIVE_GLOBS
    assert "skills/**/*.py" in LIVE_GLOBS
    assert "skills/**/*.sh" in LIVE_GLOBS
    assert "three-pillars-docs/architecture.md" in LIVE_GLOBS
    # The frozen archives are NOT scan globs.
    assert "three-pillars-docs/known_issues_resolved.md" not in LIVE_GLOBS
