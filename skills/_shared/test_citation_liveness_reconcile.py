"""Tests for citation_liveness.py via reconcile_docs — write-path regression suite.

Carved from test_citation_liveness.py (Task 3.1 — invariant-citation-coherence).
Covers: fenced-row flip, decode-failure on write path, skipped collection
(ambiguous + unattributable), CLI skipped payload, repoint_cites UTF-8 guard,
and flip_status plan/apply decode parity.

All hermetic: tmp-dir fixture repos, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ------------------------------------------------------------------ #
# Helpers — build fixture repos under tmp_path
# ------------------------------------------------------------------ #


def _completed(root: Path, slug: str) -> Path:
    d = root / "three-pillars-docs" / "completed-tp-designs" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def _living_doc(root: Path, name: str, text: str) -> Path:
    p = root / "three-pillars-docs" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _roadmap(root: Path, text: str) -> Path:
    return _living_doc(root, "product_roadmap.md", text)


# ------------------------------------------------------------------ #
# Round-4 — F5: fenced code block stale row not flipped (write path)
# ------------------------------------------------------------------ #


def test_fenced_code_block_stale_row_not_flipped(tmp_path):
    """A stale-status line inside a fenced code block must survive --apply."""
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending |\n\n"
        "```\n"
        "| `my-design` | Completion PR pending |\n"
        "```\n",
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "my-design", pr_number=5, apply=True)
    content = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text(encoding="utf-8")
    # The real row outside the fence must be flipped
    assert "merged PR #5" in content
    # But the fenced copy must survive unchanged
    assert content.count("Completion PR pending") >= 1, (
        "the fenced example row must survive --apply unchanged"
    )


# ------------------------------------------------------------------ #
# Round-4 — F6: decode-failure on write path
# ------------------------------------------------------------------ #


def test_flip_status_skips_undecodable_file(tmp_path, capsys):
    """Writer must skip a file with undecodable bytes and add it to skipped."""
    _completed(tmp_path, "my-design")
    roadmap_path = tmp_path / "three-pillars-docs" / "product_roadmap.md"
    roadmap_path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending |\n"
    )
    roadmap_path.write_bytes(content.encode("utf-8") + b"\xff\xfe invalid bytes\n")
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "my-design", pr_number=5, apply=True)
    written = roadmap_path.read_bytes()
    assert b"\xef\xbf\xbd" not in written, (
        "writer must not introduce U+FFFD (replacement character) into the written file"
    )


# ------------------------------------------------------------------ #
# Round-4 — F1: skipped collection (ambiguous + unattributable)
# ------------------------------------------------------------------ #


def test_flip_status_ambiguous_row_in_skipped(tmp_path):
    """A row with >1 unquoted STALE_STATUS_RE matches must appear in skipped."""
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending | also Completion PR pending |\n",
    )
    from reconcile_docs import flip_status_with_skipped

    edits, skipped = flip_status_with_skipped(tmp_path, "my-design", pr_number=5, apply=False)
    assert len(edits) == 0, "ambiguous row must produce no edits"
    assert len(skipped) == 1, "ambiguous row must be in skipped"
    assert skipped[0]["reason"] == "ambiguous-multi-match"


def test_flip_status_unattributable_row_in_skipped(tmp_path):
    """A stale-status row that cannot be attributed (owner=None) must appear in skipped."""
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "no-owner-here Completion PR pending\n",
    )
    from reconcile_docs import flip_status_with_skipped

    edits, skipped = flip_status_with_skipped(tmp_path, "my-design", pr_number=5, apply=False)
    assert len(edits) == 0, "unattributable row must produce no edits"
    assert len(skipped) >= 1, "unattributable row must be in skipped list"
    reasons = [s["reason"] for s in skipped]
    assert "unattributable" in reasons, (
        "unattributable row must be in skipped with reason 'unattributable'"
    )


def test_cli_json_skipped_key_present(tmp_path, capsys):
    """The CLI --json payload must include a 'skipped' key."""
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending |\n",
    )
    from reconcile_docs import main

    ret = main([
        "reconcile_docs.py",
        "--slug", "my-design",
        "--pr", "5",
        "--repo", str(tmp_path),
        "--json",
    ])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "skipped" in data, "CLI --json payload must include 'skipped' key"
    assert isinstance(data["skipped"], list)


def test_cli_json_ambiguous_row_in_skipped_payload(tmp_path, capsys):
    """An ambiguous row must appear in the CLI --json 'skipped' payload."""
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending | also Completion PR pending |\n",
    )
    from reconcile_docs import main

    ret = main([
        "reconcile_docs.py",
        "--slug", "my-design",
        "--pr", "5",
        "--repo", str(tmp_path),
        "--json",
    ])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "skipped" in data
    assert len(data["skipped"]) >= 1
    reasons = [s["reason"] for s in data["skipped"]]
    assert "ambiguous-multi-match" in reasons


def test_mutation_ambiguous_branch_deletion_fails(tmp_path):
    """Mutation pin: deleting the >1 unquoted branch must cause this test to fail."""
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending | also Completion PR pending |\n",
    )
    from reconcile_docs import flip_status_with_skipped

    edits, skipped = flip_status_with_skipped(tmp_path, "my-design", pr_number=5, apply=False)
    assert len(edits) == 0, (
        "ambiguous row must produce NO edits — if this fails, the ambiguous branch was deleted"
    )
    assert any(s["reason"] == "ambiguous-multi-match" for s in skipped), (
        "ambiguous row must be in skipped with reason 'ambiguous-multi-match'"
    )


# ------------------------------------------------------------------ #
# Round-5 — F1(structural): repoint_cites strict-UTF8 guard
# ------------------------------------------------------------------ #


def test_repoint_cites_skips_undecodable_file_on_apply(tmp_path):
    """repoint_cites must not rewrite a file with undecodable bytes (apply mode)."""
    _completed(tmp_path, "gone-slug")
    p = tmp_path / "skills" / "_shared" / "corrupt.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    valid_part = "# See three-pillars-docs/tp-designs/gone-slug/design.md\n"
    p.write_bytes(valid_part.encode("utf-8") + b"\xff invalid\n")
    from reconcile_docs import repoint_cites

    edits = repoint_cites(tmp_path, slugs={"gone-slug"}, apply=True)
    assert len(edits) == 0, (
        "repoint_cites must skip files with undecodable bytes on apply — no edits"
    )
    written = p.read_bytes()
    assert b"\xef\xbf\xbd" not in written, (
        "repoint_cites must not introduce U+FFFD into files with invalid bytes"
    )


def test_repoint_cites_plan_mode_skips_undecodable_file(tmp_path):
    """repoint_cites plan mode must also skip undecodable files (plan/apply parity)."""
    _completed(tmp_path, "gone-slug")
    p = tmp_path / "skills" / "_shared" / "corrupt.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    valid_part = "# See three-pillars-docs/tp-designs/gone-slug/design.md\n"
    p.write_bytes(valid_part.encode("utf-8") + b"\xff invalid\n")
    from reconcile_docs import repoint_cites

    plan_edits = repoint_cites(tmp_path, slugs={"gone-slug"}, apply=False)
    assert len(plan_edits) == 0, (
        "plan mode must skip undecodable files: 0 edits (faithful preview of apply)"
    )


# ------------------------------------------------------------------ #
# Round-5 — F4: flip_status plan/apply decode parity
# ------------------------------------------------------------------ #


def test_flip_status_plan_and_apply_agree_on_undecodable(tmp_path):
    """flip_status plan and apply must both skip undecodable files identically."""
    _completed(tmp_path, "my-design")
    roadmap_path = tmp_path / "three-pillars-docs" / "product_roadmap.md"
    roadmap_path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending |\n"
    )
    roadmap_path.write_bytes(content.encode("utf-8") + b"\xff\xfe invalid\n")
    from reconcile_docs import flip_status_with_skipped

    plan_edits, plan_skipped = flip_status_with_skipped(
        tmp_path, "my-design", pr_number=5, apply=False
    )
    apply_edits, apply_skipped = flip_status_with_skipped(
        tmp_path, "my-design", pr_number=5, apply=True
    )
    assert len(plan_edits) == 0, "plan mode must produce 0 edits for undecodable file"
    assert len(apply_edits) == 0, "apply mode must produce 0 edits for undecodable file"
    assert len(plan_skipped) == len(apply_skipped), (
        "plan and apply must agree on skipped count for undecodable file"
    )
    assert any(s["reason"] == "decode-failure" for s in plan_skipped), (
        "plan mode must report decode-failure skip for undecodable file"
    )
    assert any(s["reason"] == "decode-failure" for s in apply_skipped), (
        "apply mode must report decode-failure skip for undecodable file"
    )


def test_flip_status_plan_skips_undecodable_file(tmp_path):
    """flip_status in plan mode (apply=False) must emit decode-failure skip."""
    _completed(tmp_path, "my-design")
    roadmap_path = tmp_path / "three-pillars-docs" / "product_roadmap.md"
    roadmap_path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending |\n"
    )
    roadmap_path.write_bytes(content.encode("utf-8") + b"\xff\xfe invalid\n")
    from reconcile_docs import flip_status_with_skipped

    edits, skipped = flip_status_with_skipped(
        tmp_path, "my-design", pr_number=5, apply=False
    )
    assert len(edits) == 0, "plan mode must produce 0 edits for undecodable file"
    assert any(s["reason"] == "decode-failure" for s in skipped), (
        "plan mode must report decode-failure in skipped for undecodable file"
    )
