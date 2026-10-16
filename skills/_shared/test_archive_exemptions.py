"""Tests for archive exemptions in the shipped predicates (task 1.6).

`architecture_archive.md` must be exempt in the same three places
`product_roadmap_archive.md` already is:

  - size-exempt in file_size_guard (EXEMPT_FILES / is_exempt / evaluate);
  - frozen for invariant cites in citation_frozen.is_frozen (clause 3);
  - a living doc in worktree_write_guard._LIVING_DOCS (writable on the seat).

EXEMPT_FILES covers every value of living_doc_archive.ARCHIVES — the
single-definition pin keeps the two sets in lock-step.

Run with: python -m pytest skills/_shared/test_archive_exemptions.py -q
"""
from __future__ import annotations

from citation_frozen import is_frozen
from file_size_guard import EXEMPT_FILES, evaluate, is_exempt
from living_doc_archive import ARCHIVES
from worktree_write_guard import _LIVING_DOCS, is_guarded_path

ARCH_ARCH = "three-pillars-docs/architecture_archive.md"
ARCH_KI = "three-pillars-docs/known_issues_resolved.md"
ARCH_PR = "three-pillars-docs/product_roadmap_archive.md"
ALL_ARCHIVES = (ARCH_ARCH, ARCH_KI, ARCH_PR)


def test_cold_files_exempt_low_and_new_archives():
    # D5: cold files stay exempt; *_archive.md is a glob so new archives
    # (known_issues_archive.md, vision_archive.md) need no list edit.
    for rel in (
        "three-pillars-docs/known_issues_low.md",
        "three-pillars-docs/known_issues_archive.md",
        "three-pillars-docs/vision_archive.md",
    ):
        assert is_exempt(rel), rel
        assert evaluate(rel, 1000, 60_000, grandfathered=False) is None


def test_archive_glob_is_top_level_only():
    assert not is_exempt("three-pillars-docs/sub/x_archive.md")
    assert not is_exempt("docs/vision_archive.md")


def test_is_exempt_true_for_all_three_archives():
    for rel in ALL_ARCHIVES:
        assert is_exempt(rel), rel


def test_evaluate_returns_none_for_oversized_architecture_archive():
    # 60,000 chars hard-violates the markdown cap (50,000); an exempt path
    # must yield no finding at all.
    assert evaluate(ARCH_ARCH, 1000, 60_000, grandfathered=False) is None


def test_exempt_files_covers_living_doc_archive_values():
    # Single-definition pin: every archive in the living-doc map must be in
    # the size-guard exemption set.
    assert set(ARCHIVES.values()) <= EXEMPT_FILES


def test_exempt_files_names_vision_archive():
    # skill-context-diet 1.9 added vision.md -> vision_archive.md to ARCHIVES, so
    # the named exemption set carries it too (the glob alone is not the pin).
    assert "three-pillars-docs/vision_archive.md" in EXEMPT_FILES


def test_architecture_archive_is_frozen_for_cites():
    # Clause 3 widened to the archive set: outside History/fences, a cite in
    # architecture_archive.md is still exempt.
    assert is_frozen(ARCH_ARCH, "invariant #3", in_history=False, in_fence=False)


def test_living_docs_include_both_archives():
    # Append-only archives, same governance class as known_issues_resolved.md:
    # pinned by name in the set, and unwritable-guarded through the predicate.
    assert "architecture_archive.md" in _LIVING_DOCS
    assert "product_roadmap_archive.md" in _LIVING_DOCS
    assert is_guarded_path(ARCH_ARCH) is False
    assert is_guarded_path(ARCH_PR) is False
