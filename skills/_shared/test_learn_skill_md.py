"""Prose-pin tests for tp-design-learn/SKILL.md, reconcile-protocol.md,
and three-pillars-docs/architecture.md (reverse-walk section).

Tasks 3.1, 3.4, 4.1.

Run with: python -m pytest skills/_shared/test_learn_skill_md.py -q

Design refs:
  design: post-merge-doc-reconcile
"""

from __future__ import annotations

import re
from pathlib import Path
import pytest

_DEV_ROOT = Path(__file__).resolve().parents[2]
_needs_architecture = pytest.mark.skipif(
    not (_DEV_ROOT / "three-pillars-docs/architecture.md").exists(),
    reason="reads the dev repo's architecture.md (dev-repo only)")

_BASE = Path(__file__).resolve().parents[2]

PROTOCOL_MD = _BASE / "skills" / "_shared" / "reconcile-protocol.md"
ARCH_MD = _BASE / "three-pillars-docs" / "architecture.md"


def _read_arch() -> str:
    return ARCH_MD.read_text(encoding="utf-8")


# ------------------------------------------------------------------ #
# Task 3.1 — reconcile-protocol.md existence and content
# ------------------------------------------------------------------ #


def test_reconcile_protocol_doc_exists():
    assert PROTOCOL_MD.is_file(), f"reconcile-protocol.md not found at {PROTOCOL_MD}"


# The wording of reconcile-protocol.md and tp-design-learn/SKILL.md is not pinned
# here. Every path, script and flag they name is covered by invariant 46
# (`skill_refs`), run in-suite below.


@pytest.mark.parametrize("doc", [
    "skills/tp-design-learn/SKILL.md",
    "skills/_shared/reconcile-protocol.md",
])
def test_learn_docs_references_resolve(doc, tmp_path):
    """Every reference in the learn skill and its protocol resolves through invariant 46."""
    skill_refs = pytest.importorskip("skill_refs")
    report = skill_refs.check(_BASE, [_BASE / doc], cache_dir=tmp_path)
    assert report.issues == []


# ------------------------------------------------------------------ #
# Task 4.1 — architecture.md reverse-walk section
# ------------------------------------------------------------------ #


@_needs_architecture
def test_architecture_has_reverse_walk_section():
    text = _read_arch()
    # tp-allow-fragile: the heading is the citation anchor reconcile-protocol.md names (architecture.md §"Finding the spawning design"); a dev-repo living-doc read, outside the four prose-pin rules
    assert "## Finding the spawning design" in text, (
        "three-pillars-docs/architecture.md must have a "
        "'## Finding the spawning design' section"
    )


@_needs_architecture
def test_reverse_walk_section_names_git_log_follow():
    text = _read_arch()
    # Find the section
    match = re.search(
        r"^## Finding the spawning design.*?(?=^## |\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match, "## Finding the spawning design section not found"
    section = match.group(0)
    assert "git log --follow" in section, (
        "The reverse-walk section must name 'git log --follow'"
    )
    assert re.search(r"design:\s*\{slug\}|`design: ", section), (
        "The reverse-walk section must document the 'design: {slug}' convention"
    )
