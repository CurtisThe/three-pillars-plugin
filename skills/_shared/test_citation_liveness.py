"""Tests for citation_liveness.py — dead-cite detector + stale-row scanner.

All hermetic: tmp-dir fixture repos, injected *_fn runners, no network.

Run with: python -m pytest skills/_shared/test_citation_liveness.py -q

Design refs:
  design: post-merge-doc-reconcile
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest


# ------------------------------------------------------------------ #
# Helpers — build fixture repos under tmp_path
# ------------------------------------------------------------------ #


def _tp_design(root: Path, slug: str) -> Path:
    d = root / "three-pillars-docs" / "tp-designs" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def _completed(root: Path, slug: str) -> Path:
    d = root / "three-pillars-docs" / "completed-tp-designs" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def _skills_file(root: Path, rel: str, text: str) -> Path:
    p = root / "skills" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _living_doc(root: Path, name: str, text: str) -> Path:
    p = root / "three-pillars-docs" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


# ------------------------------------------------------------------ #
# Task 1.1 — dead_design_cites core matching
# ------------------------------------------------------------------ #


def test_dead_cite_found_in_code(tmp_path):
    _completed(tmp_path, "gone-slug")
    _skills_file(
        tmp_path,
        "foo.py",
        "# see three-pillars-docs/tp-designs/gone-slug/design.md\n",
    )
    from citation_liveness import dead_design_cites, DeadCite

    results = dead_design_cites(tmp_path)
    assert len(results) == 1
    r = results[0]
    assert isinstance(r, DeadCite)
    assert "gone-slug" in r.path or r.slug == "gone-slug"
    assert r.slug == "gone-slug"
    assert r.line == 1
    assert r.kind == "code"


def test_dead_cite_found_in_living_doc(tmp_path):
    _completed(tmp_path, "gone-slug")
    _living_doc(
        tmp_path,
        "product_roadmap.md",
        "*Last updated: 2026-01-01*\n\nsome text\n\n"
        "See three-pillars-docs/tp-designs/gone-slug/design.md for details.\n",
    )
    from citation_liveness import dead_design_cites, DeadCite

    results = dead_design_cites(tmp_path)
    assert len(results) == 1
    r = results[0]
    assert r.slug == "gone-slug"
    assert r.kind == "living-doc"


def test_completed_prefix_not_matched(tmp_path):
    _completed(tmp_path, "gone-slug")
    _skills_file(
        tmp_path,
        "foo.py",
        "# archived at completed-tp-designs/gone-slug/design.md\n",
    )
    from citation_liveness import dead_design_cites

    results = dead_design_cites(tmp_path)
    assert results == []


def test_live_design_not_flagged(tmp_path):
    _tp_design(tmp_path, "live-slug")
    _skills_file(
        tmp_path,
        "foo.py",
        "# see three-pillars-docs/tp-designs/live-slug/design.md\n",
    )
    from citation_liveness import dead_design_cites

    results = dead_design_cites(tmp_path)
    assert results == []


def test_unknown_slug_not_flagged(tmp_path):
    # typo-slug matches neither tp-designs nor completed-tp-designs
    _skills_file(
        tmp_path,
        "foo.py",
        "# see three-pillars-docs/tp-designs/typo-slug/design.md\n",
    )
    from citation_liveness import dead_design_cites

    results = dead_design_cites(tmp_path)
    assert results == []


# ------------------------------------------------------------------ #
# Task 1.2 — scan-scope exclusions
# ------------------------------------------------------------------ #


def test_history_section_lines_excluded(tmp_path):
    _completed(tmp_path, "gone-slug")
    # cite is inside a ## History section
    _living_doc(
        tmp_path,
        "product_roadmap.md",
        "*Last updated: 2026-01-01*\n\n"
        "## Active\n\n"
        "Normal content.\n\n"
        "## History\n\n"
        "Old: three-pillars-docs/tp-designs/gone-slug/design.md\n",
    )
    from citation_liveness import dead_design_cites

    results = dead_design_cites(tmp_path)
    assert results == []


def test_roadmap_history_heading_variant_excluded(tmp_path):
    _completed(tmp_path, "gone-slug")
    _living_doc(
        tmp_path,
        "product_roadmap.md",
        "*Last updated: 2026-01-01*\n\n"
        "## Roadmap History\n\n"
        "Old: three-pillars-docs/tp-designs/gone-slug/design.md\n",
    )
    from citation_liveness import dead_design_cites

    results = dead_design_cites(tmp_path)
    assert results == []


def test_dead_cite_after_non_history_heading_flagged(tmp_path):
    """After a non-History heading, state flips back to active scanning."""
    _completed(tmp_path, "gone-slug")
    _living_doc(
        tmp_path,
        "product_roadmap.md",
        "*Last updated: 2026-01-01*\n\n"
        "## Roadmap History\n\n"
        "Old: three-pillars-docs/tp-designs/gone-slug/design.md\n\n"
        "## Active Designs\n\n"
        "New: three-pillars-docs/tp-designs/gone-slug/design.md\n",
    )
    from citation_liveness import dead_design_cites

    results = dead_design_cites(tmp_path)
    # The second cite (after ## Active Designs) should be flagged
    assert len(results) == 1
    assert results[0].kind == "living-doc"


def test_fixtures_eval_pycache_excluded(tmp_path):
    _completed(tmp_path, "gone-slug")
    _skills_file(
        tmp_path,
        "tp-foo/fixtures/sample.py",
        "# three-pillars-docs/tp-designs/gone-slug/design.md\n",
    )
    _skills_file(
        tmp_path,
        "tp-bar/eval/run.py",
        "# three-pillars-docs/tp-designs/gone-slug/design.md\n",
    )
    _skills_file(
        tmp_path,
        "tp-baz/__pycache__/module.py",
        "# three-pillars-docs/tp-designs/gone-slug/design.md\n",
    )
    from citation_liveness import dead_design_cites

    results = dead_design_cites(tmp_path)
    assert results == []


def test_archived_and_inflight_design_dirs_never_scanned(tmp_path):
    """Files under tp-designs/** and completed-tp-designs/** are never scanned."""
    _completed(tmp_path, "gone-slug")
    # Put a dead cite inside the completed-tp-designs dir itself
    archived_file = (
        tmp_path
        / "three-pillars-docs"
        / "completed-tp-designs"
        / "other-slug"
        / "design.md"
    )
    archived_file.parent.mkdir(parents=True, exist_ok=True)
    archived_file.write_text(
        "See three-pillars-docs/tp-designs/gone-slug/design.md\n"
    )
    # Put a dead cite inside tp-designs dir
    inflight_file = (
        tmp_path / "three-pillars-docs" / "tp-designs" / "live-slug" / "design.md"
    )
    inflight_file.parent.mkdir(parents=True, exist_ok=True)
    inflight_file.write_text(
        "See three-pillars-docs/tp-designs/gone-slug/design.md\n"
    )
    from citation_liveness import dead_design_cites

    results = dead_design_cites(tmp_path)
    assert results == []


# ------------------------------------------------------------------ #
# Task 1.3 — live_remote_branches
# ------------------------------------------------------------------ #


def _make_ls_remote_fn(returncode: int, stdout: str):
    """Build a fake ls_remote_fn that returns a CompletedProcess-like object."""

    class _Result:
        def __init__(self):
            self.returncode = returncode
            self.stdout = stdout

    def _fn(*args, **kwargs):
        return _Result()

    return _fn


def test_live_remote_branches_parses_heads(tmp_path):
    fake = _make_ls_remote_fn(
        0,
        "abc123\trefs/heads/tp/foo\n"
        "def456\trefs/heads/tp/bar\n",
    )
    from citation_liveness import live_remote_branches

    result = live_remote_branches(tmp_path, ls_remote_fn=fake)
    assert result is not None
    assert "tp/foo" in result
    assert "tp/bar" in result


def test_nonzero_exit_returns_none(tmp_path):
    fake = _make_ls_remote_fn(1, "")
    from citation_liveness import live_remote_branches

    result = live_remote_branches(tmp_path, ls_remote_fn=fake)
    assert result is None


def test_empty_success_returns_empty_set(tmp_path):
    fake = _make_ls_remote_fn(0, "")
    from citation_liveness import live_remote_branches

    result = live_remote_branches(tmp_path, ls_remote_fn=fake)
    assert result == set()


# ------------------------------------------------------------------ #
# Task 1.4 — stale_status_rows
# ------------------------------------------------------------------ #


def _roadmap(root: Path, text: str) -> Path:
    return _living_doc(root, "product_roadmap.md", text)


def test_stale_row_flagged_when_archived_and_branch_absent(tmp_path):
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending (Tier 6) |\n",
    )
    from citation_liveness import stale_status_rows

    results = stale_status_rows(tmp_path, live_branches=set())
    assert len(results) == 1
    assert results[0].slug == "my-design"


def test_row_with_live_branch_not_flagged(tmp_path):
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending (Tier 6) |\n",
    )
    from citation_liveness import stale_status_rows

    # Branch is still live
    results = stale_status_rows(tmp_path, live_branches={"tp/my-design"})
    assert results == []


def test_row_with_unarchived_slug_not_flagged(tmp_path):
    # slug is NOT in completed-tp-designs
    _tp_design(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending (Tier 6) |\n",
    )
    from citation_liveness import stale_status_rows

    results = stale_status_rows(tmp_path, live_branches=set())
    assert results == []


def test_live_branches_none_returns_empty(tmp_path):
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending (Tier 6) |\n",
    )
    from citation_liveness import stale_status_rows

    results = stale_status_rows(tmp_path, live_branches=None)
    assert results == []


def test_unresolvable_slug_row_skipped(tmp_path):
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| no slug here | completion PR pending |\n",
    )
    from citation_liveness import stale_status_rows

    results = stale_status_rows(tmp_path, live_branches=set())
    assert results == []


def test_history_rows_excluded_from_stale_scan(tmp_path):
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Roadmap History\n\n"
        "| `my-design` | Completion PR pending (Tier 6) |\n",
    )
    from citation_liveness import stale_status_rows

    results = stale_status_rows(tmp_path, live_branches=set())
    assert results == []


def test_bare_lowercase_completion_pr_pending_flagged(tmp_path):
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | completion PR pending |\n",
    )
    from citation_liveness import stale_status_rows

    results = stale_status_rows(tmp_path, live_branches=set())
    assert len(results) == 1
    assert results[0].slug == "my-design"


# ------------------------------------------------------------------ #
# Task 1.5 — CLI main
# ------------------------------------------------------------------ #


def test_cli_exit_zero_with_findings(tmp_path):
    _completed(tmp_path, "gone-slug")
    _skills_file(
        tmp_path,
        "foo.py",
        "# three-pillars-docs/tp-designs/gone-slug/design.md\n",
    )
    from citation_liveness import main

    ret = main(["citation_liveness.py", "--repo", str(tmp_path), "--json"])
    assert ret == 0


def test_cli_exit_zero_on_broken_repo(tmp_path):
    broken = tmp_path / "nonexistent"
    from citation_liveness import main

    ret = main(["citation_liveness.py", "--repo", str(broken), "--json"])
    assert ret == 0


def test_cli_json_shape(tmp_path, capsys):
    _completed(tmp_path, "gone-slug")
    _skills_file(
        tmp_path,
        "foo.py",
        "# three-pillars-docs/tp-designs/gone-slug/design.md\n",
    )
    from citation_liveness import main

    ret = main(["citation_liveness.py", "--repo", str(tmp_path), "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "dead_cites" in data
    assert "stale_rows" in data
    assert isinstance(data["dead_cites"], list)
    assert isinstance(data["stale_rows"], list)
    # Should have at least 1 dead cite
    assert len(data["dead_cites"]) >= 1


def test_cli_without_remote_skips_stale_check(tmp_path):
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending (Tier 6) |\n",
    )
    from citation_liveness import main

    ret = main(["citation_liveness.py", "--repo", str(tmp_path), "--json"])
    assert ret == 0
