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

_BASE = Path(__file__).resolve().parents[2]

LEARN_SKILL_MD = _BASE / "skills" / "tp-design-learn" / "SKILL.md"
PROTOCOL_MD = _BASE / "skills" / "_shared" / "reconcile-protocol.md"
ARCH_MD = _BASE / "three-pillars-docs" / "architecture.md"


def _read_learn() -> str:
    return LEARN_SKILL_MD.read_text(encoding="utf-8")


def _read_protocol() -> str:
    return PROTOCOL_MD.read_text(encoding="utf-8")


def _read_arch() -> str:
    return ARCH_MD.read_text(encoding="utf-8")


# ------------------------------------------------------------------ #
# Task 3.1 — reconcile-protocol.md existence and content
# ------------------------------------------------------------------ #


def test_reconcile_protocol_doc_exists():
    assert PROTOCOL_MD.is_file(), f"reconcile-protocol.md not found at {PROTOCOL_MD}"


def test_protocol_carries_amendment_template():
    text = _read_protocol()
    # Must have a dated amendment heading template
    assert re.search(r"\[amendment YYYY-MM-DD\]", text, re.IGNORECASE), (
        "reconcile-protocol.md must carry the dated amendment heading template"
    )
    # Must carry the required fields
    for field in ("**Supersedes**", "**Change**", "**Commit**", "**Why**"):
        assert field in text, f"Amendment template must include field: {field}"


def test_protocol_states_append_only_and_class_independence():
    text = _read_protocol()
    # Append-only: original text preserved
    assert re.search(r"never.{0,30}edit|original.{0,30}preserved|append.only", text, re.IGNORECASE), (
        "reconcile-protocol.md must state the append-only rule"
    )
    # Class independence: light/just-do-it included
    assert re.search(r"light|just.do.it", text, re.IGNORECASE), (
        "reconcile-protocol.md must state that the obligation applies to light/just-do-it"
    )


# ------------------------------------------------------------------ #
# Task 3.4 — tp-design-learn/SKILL.md wirings
# ------------------------------------------------------------------ #


def test_learn_step8_names_citation_liveness():
    text = _read_learn()
    assert "citation_liveness" in text or "citation_liveness.py" in text, (
        "tp-design-learn step 8 must name citation_liveness.py"
    )
    assert "--remote" in text, (
        "tp-design-learn step 8 must reference --remote flag for citation_liveness"
    )
    assert "--json" in text, (
        "tp-design-learn step 8 must reference --json flag"
    )


def test_learn_step8_stays_advisory():
    text = _read_learn()
    # Step 8 block — find the extended step 8 text
    step8_match = re.search(
        r"^8\.\s+.*?(?=^9\.\s+|^##|\Z)", text, re.DOTALL | re.MULTILINE
    )
    assert step8_match, "Step 8 block not found in tp-design-learn SKILL.md"
    block = step8_match.group(0)
    # Pin specifically to the citation_liveness paragraph within step 8
    # (not step 8 in general which also has verify_learn advisory text)
    cite_para_match = re.search(
        r"citation_liveness.*?(?=\n\n|\Z)", block, re.DOTALL
    )
    assert cite_para_match, (
        "Step 8 must contain a citation_liveness paragraph"
    )
    cite_para = cite_para_match.group(0)
    assert re.search(r"[Aa]dvisory|exits 0|fail.open", cite_para), (
        "citation_liveness paragraph in step 8 must state it is advisory (exits 0, fail-open)"
    )


def test_learn_step9_names_reconcile_protocol():
    text = _read_learn()
    assert "reconcile-protocol" in text or "reconcile_protocol" in text, (
        "tp-design-learn step 9 must reference reconcile-protocol.md"
    )
    # Should mention archived sibling and amendment
    assert re.search(r"archived.{0,50}sibling|amendment", text, re.IGNORECASE), (
        "tp-design-learn step 9 must reference the amendment obligation for archived siblings"
    )


# ------------------------------------------------------------------ #
# Task 4.1 — architecture.md reverse-walk section
# ------------------------------------------------------------------ #


def test_architecture_has_reverse_walk_section():
    text = _read_arch()
    assert "## Finding the spawning design" in text, (
        "three-pillars-docs/architecture.md must have a "
        "'## Finding the spawning design' section"
    )


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
