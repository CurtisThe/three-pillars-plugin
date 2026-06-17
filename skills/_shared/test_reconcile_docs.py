"""Tests for reconcile_docs.py — rewriter + sweep.

All hermetic: tmp-dir fixture repos, injected *_fn runners, no network.

Run with: python -m pytest skills/_shared/test_reconcile_docs.py -q

Design refs:
  design: post-merge-doc-reconcile
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


# ------------------------------------------------------------------ #
# Fixture helpers
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


def _roadmap(root: Path, text: str) -> Path:
    return _living_doc(root, "product_roadmap.md", text)


def _make_repo_with_dead_cite(tmp_path, slug="gone-slug"):
    """Create a minimal fixture with a dead code cite."""
    _completed(tmp_path, slug)
    _skills_file(
        tmp_path,
        "module.py",
        f"# See three-pillars-docs/tp-designs/{slug}/design.md\n",
    )
    return tmp_path


# ------------------------------------------------------------------ #
# Task 2.1 — repoint_cites
# ------------------------------------------------------------------ #


def test_repoint_rewrites_exactly_the_cite_substring(tmp_path):
    _make_repo_with_dead_cite(tmp_path, "gone-slug")
    from reconcile_docs import repoint_cites, Edit

    edits = repoint_cites(tmp_path, slugs=None, apply=True)
    assert len(edits) >= 1
    e = edits[0]
    assert isinstance(e, Edit)
    assert "tp-designs/gone-slug" in e.before
    assert "completed-tp-designs/gone-slug" in e.after
    assert e.kind == "repoint"
    # Verify file was actually changed — check via regex that it's not a bare tp-designs/ cite
    content = (tmp_path / "skills" / "module.py").read_text()
    assert "completed-tp-designs/gone-slug" in content
    # The bare (non-completed) prefix should no longer appear
    import re as _re
    assert not _re.search(r"(?<!completed-)tp-designs/gone-slug", content)


def test_no_apply_leaves_files_byte_identical(tmp_path):
    _make_repo_with_dead_cite(tmp_path, "gone-slug")
    original = (tmp_path / "skills" / "module.py").read_bytes()
    from reconcile_docs import repoint_cites

    edits = repoint_cites(tmp_path, slugs=None, apply=False)
    assert len(edits) >= 1
    after = (tmp_path / "skills" / "module.py").read_bytes()
    assert original == after


def test_edit_plan_returned_without_apply(tmp_path):
    _make_repo_with_dead_cite(tmp_path, "gone-slug")
    from reconcile_docs import repoint_cites, Edit

    edits = repoint_cites(tmp_path, slugs=None, apply=False)
    assert len(edits) >= 1
    assert all(isinstance(e, Edit) for e in edits)


def test_history_lines_and_archived_dirs_untouched(tmp_path):
    _completed(tmp_path, "gone-slug")
    # Dead cite in a History section of a living doc
    _living_doc(
        tmp_path,
        "product_roadmap.md",
        "*Last updated: 2026-01-01*\n\n"
        "## History\n\n"
        "- 2026-01-01 — see three-pillars-docs/tp-designs/gone-slug/design.md\n",
    )
    from reconcile_docs import repoint_cites

    edits = repoint_cites(tmp_path, slugs=None, apply=True)
    assert edits == []
    content = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text()
    assert "tp-designs/gone-slug" in content  # untouched


def test_idempotent_second_apply_returns_empty(tmp_path):
    _make_repo_with_dead_cite(tmp_path, "gone-slug")
    from reconcile_docs import repoint_cites

    first = repoint_cites(tmp_path, slugs=None, apply=True)
    assert len(first) >= 1
    second = repoint_cites(tmp_path, slugs=None, apply=True)
    assert second == []


def test_slugs_filter_restricts_scope(tmp_path):
    _completed(tmp_path, "slug-a")
    _completed(tmp_path, "slug-b")
    _skills_file(
        tmp_path,
        "a.py",
        "# three-pillars-docs/tp-designs/slug-a/design.md\n",
    )
    _skills_file(
        tmp_path,
        "b.py",
        "# three-pillars-docs/tp-designs/slug-b/design.md\n",
    )
    from reconcile_docs import repoint_cites

    edits = repoint_cites(tmp_path, slugs={"slug-a"}, apply=True)
    # Only slug-a repointed
    assert all(e.slug == "slug-a" for e in edits)
    assert len(edits) == 1
    # slug-b file untouched
    content_b = (tmp_path / "skills" / "b.py").read_text()
    assert "tp-designs/slug-b" in content_b


# ------------------------------------------------------------------ #
# Task 2.2 — flip_status
# ------------------------------------------------------------------ #


def test_flip_tier6_variant_to_merged_pr_nn(tmp_path):
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending (Tier 6) |\n",
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "my-design", pr_number=7, apply=True)
    assert len(edits) >= 1
    content = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text()
    assert "merged PR #7" in content
    assert "Completion PR pending" not in content


def test_flip_bare_lowercase_variant(tmp_path):
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | completion PR pending |\n",
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "my-design", pr_number=7, apply=True)
    assert len(edits) >= 1
    content = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text()
    assert "merged PR #7" in content


def test_no_pr_number_uses_plain_merged_label(tmp_path):
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending (Tier 6) |\n",
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "my-design", pr_number=None, apply=True)
    assert len(edits) >= 1
    content = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text()
    assert "merged" in content
    # Should not have a PR number
    assert "merged PR #" not in content


def test_flip_only_rows_naming_the_slug(tmp_path):
    _completed(tmp_path, "slug-a")
    _completed(tmp_path, "slug-b")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `slug-a` | Completion PR pending (Tier 6) |\n"
        "| `slug-b` | Completion PR pending (Tier 6) |\n",
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "slug-a", pr_number=5, apply=True)
    content = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text()
    # slug-a flipped
    lines = content.splitlines()
    slug_a_line = next(l for l in lines if "slug-a" in l)
    slug_b_line = next(l for l in lines if "slug-b" in l)
    assert "merged PR #5" in slug_a_line
    assert "Completion PR pending" in slug_b_line


def test_last_updated_date_bumped_on_touched_living_doc(tmp_path):
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2020-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending (Tier 6) |\n",
    )
    from reconcile_docs import flip_status
    import datetime

    edits = flip_status(tmp_path, "my-design", pr_number=7, apply=True)
    content = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text()
    today = datetime.date.today().isoformat()
    assert today in content


def test_flip_is_idempotent(tmp_path):
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending (Tier 6) |\n",
    )
    from reconcile_docs import flip_status

    first = flip_status(tmp_path, "my-design", pr_number=7, apply=True)
    assert len(first) >= 1
    second = flip_status(tmp_path, "my-design", pr_number=7, apply=True)
    assert second == []


def test_flip_adds_no_history_line(tmp_path):
    """The script does NOT append History lines — that's the calling SKILL's job."""
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending (Tier 6) |\n\n"
        "## History\n\n"
        "- 2026-01-01 — initial.\n",
    )
    history_before = (
        tmp_path / "three-pillars-docs" / "product_roadmap.md"
    ).read_text().split("## History")[1]
    from reconcile_docs import flip_status

    flip_status(tmp_path, "my-design", pr_number=7, apply=True)
    content_after = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text()
    history_after = content_after.split("## History")[1]
    # History section unchanged
    assert history_before == history_after


def test_flip_stale_row_in_history_section_never_flipped(tmp_path):
    """A STALE_STATUS_RE row naming the slug INSIDE ## History must survive --apply.

    Mutation-kill test: deleting 'if in_history: continue' must fail this test.
    The History section is append-only truth — rows there must never be rewritten.
    """
    _completed(tmp_path, "my-design")
    history_row = "| `my-design` | Completion PR pending (Tier 6) |"
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Roadmap History\n\n"
        f"{history_row}\n",
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "my-design", pr_number=7, apply=True)
    assert edits == [], (
        "rows inside ## History / ## Roadmap History must never be flipped"
    )
    # Verify file content is unchanged
    content = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text()
    assert history_row in content, "history row must survive --apply untouched"


# ------------------------------------------------------------------ #
# Task 2.3 — merged_pr_number
# ------------------------------------------------------------------ #


def _make_gh_fn(returncode: int, stdout: str, raises=None):
    class _Result:
        def __init__(self):
            self.returncode = returncode
            self.stdout = stdout

    def _fn(*args, **kwargs):
        if raises:
            raise raises
        return _Result()

    return _fn


def test_takes_max_of_multiple_merged_prs(tmp_path):
    fake = _make_gh_fn(0, '[{"number":70},{"number":71}]')
    from reconcile_docs import merged_pr_number

    result = merged_pr_number(tmp_path, "my-design", gh_fn=fake)
    assert result == 71


def test_none_on_gh_nonzero_exit(tmp_path):
    fake = _make_gh_fn(1, "")
    from reconcile_docs import merged_pr_number

    result = merged_pr_number(tmp_path, "my-design", gh_fn=fake)
    assert result is None


def test_none_on_gh_missing(tmp_path):
    fake = _make_gh_fn(0, "", raises=FileNotFoundError("gh not found"))
    from reconcile_docs import merged_pr_number

    result = merged_pr_number(tmp_path, "my-design", gh_fn=fake)
    assert result is None


# ------------------------------------------------------------------ #
# Task 2.4 — reconcile_slug, sweep, CLI
# ------------------------------------------------------------------ #


def test_reconcile_slug_repoints_and_flips(tmp_path):
    _completed(tmp_path, "my-design")
    _skills_file(
        tmp_path,
        "foo.py",
        "# three-pillars-docs/tp-designs/my-design/design.md\n",
    )
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending (Tier 6) |\n",
    )
    from reconcile_docs import reconcile_slug

    edits = reconcile_slug(tmp_path, "my-design", pr_number=7, apply=True)
    kinds = {e.kind for e in edits}
    assert "repoint" in kinds
    assert "status-flip" in kinds


def test_archive_cites_mode_performs_no_status_flip(tmp_path):
    _completed(tmp_path, "my-design")
    _skills_file(
        tmp_path,
        "foo.py",
        "# three-pillars-docs/tp-designs/my-design/design.md\n",
    )
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending (Tier 6) |\n",
    )
    from reconcile_docs import archive_cites

    edits = archive_cites(tmp_path, "my-design", apply=True)
    kinds = {e.kind for e in edits}
    assert "repoint" in kinds
    assert "status-flip" not in kinds
    # Roadmap status unchanged
    content = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text()
    assert "Completion PR pending" in content


def test_sweep_repoints_all_archived_slugs(tmp_path):
    _completed(tmp_path, "slug-a")
    _completed(tmp_path, "slug-b")
    _skills_file(
        tmp_path,
        "a.py",
        "# three-pillars-docs/tp-designs/slug-a/design.md\n",
    )
    _skills_file(
        tmp_path,
        "b.py",
        "# three-pillars-docs/tp-designs/slug-b/design.md\n",
    )
    from reconcile_docs import sweep

    edits = sweep(tmp_path, apply=True, remote=False)
    slugs_repointed = {e.slug for e in edits if e.kind == "repoint"}
    assert "slug-a" in slugs_repointed
    assert "slug-b" in slugs_repointed


def test_sweep_flips_only_confirmed_absent_branch_slugs(tmp_path):
    _completed(tmp_path, "slug-a")  # absent branch
    _completed(tmp_path, "slug-b")  # live branch
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `slug-a` | Completion PR pending (Tier 6) |\n"
        "| `slug-b` | Completion PR pending (Tier 6) |\n",
    )

    def _fake_live_branches(repo_root, ls_remote_fn=None):
        return {"tp/slug-b"}  # slug-b is live

    from reconcile_docs import sweep

    edits = sweep(tmp_path, apply=True, remote=True, _live_branches_fn=_fake_live_branches)
    flip_slugs = {e.slug for e in edits if e.kind == "status-flip"}
    assert "slug-a" in flip_slugs
    assert "slug-b" not in flip_slugs


def test_sweep_with_none_live_branches_flips_nothing(tmp_path):
    _completed(tmp_path, "slug-a")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `slug-a` | Completion PR pending (Tier 6) |\n",
    )

    def _fake_live_branches_none(repo_root, ls_remote_fn=None):
        return None  # offline

    from reconcile_docs import sweep

    edits = sweep(tmp_path, apply=True, remote=True, _live_branches_fn=_fake_live_branches_none)
    flip_slugs = {e.slug for e in edits if e.kind == "status-flip"}
    assert "slug-a" not in flip_slugs


def test_cli_modes_mutually_exclusive(tmp_path, capsys):
    from reconcile_docs import main

    # Passing both --slug and --sweep should trigger mutual exclusion error from argparse.
    # argparse prints an error and calls sys.exit(2) which is caught and returns 0.
    # Observable behavior: stderr must carry a mutually-exclusive error message.
    ret = main(["reconcile_docs.py", "--slug", "foo", "--sweep", "--repo", str(tmp_path)])
    assert ret == 0  # always exits 0 (SystemExit caught)
    captured = capsys.readouterr()
    # argparse writes "error: argument ... not allowed with argument ..." to stderr
    assert "not allowed" in captured.err or "mutually exclusive" in captured.err, (
        "--slug and --sweep must conflict (argparse mutual-exclusion group)"
    )


def test_cli_modes_mutually_exclusive_observable_sweep_suppressed(tmp_path, capsys):
    """When --slug and --sweep are passed together, the sweep does NOT run.

    The argparse mutual-exclusion fires before any mode runs, so stdout should
    be empty (argparse error to stderr only) — no sweep edits are emitted.
    """
    _completed(tmp_path, "gone-slug")
    _skills_file(
        tmp_path,
        "foo.py",
        "# three-pillars-docs/tp-designs/gone-slug/design.md\n",
    )
    from reconcile_docs import main

    ret = main([
        "reconcile_docs.py",
        "--slug", "gone-slug",
        "--sweep",
        "--repo", str(tmp_path),
        "--json",
    ])
    assert ret == 0
    captured = capsys.readouterr()
    # argparse mutual-exclusion fires before any mode runs: stdout must be empty
    # (no JSON edits payload emitted by a sweep or slug mode).
    assert captured.out.strip() == "", (
        "When --slug and --sweep conflict, stdout must be empty (no sweep edits emitted)"
    )
    # Additionally confirm the mutual-exclusion error went to stderr
    assert "not allowed" in captured.err or "mutually exclusive" in captured.err, (
        "argparse must report the mutual-exclusion error on stderr"
    )


def test_cli_always_exit_zero_and_writes_only_under_apply(tmp_path):
    _completed(tmp_path, "gone-slug")
    _skills_file(
        tmp_path,
        "foo.py",
        "# three-pillars-docs/tp-designs/gone-slug/design.md\n",
    )
    original = (tmp_path / "skills" / "foo.py").read_bytes()

    from reconcile_docs import main

    # Without --apply: no writes
    ret = main([
        "reconcile_docs.py",
        "--sweep",
        "--repo", str(tmp_path),
        "--json",
    ])
    assert ret == 0
    after = (tmp_path / "skills" / "foo.py").read_bytes()
    assert original == after


# ------------------------------------------------------------------ #
# REGRESSION — structural fix 1: repoint_cites boundary-aware
# ------------------------------------------------------------------ #


def test_repoint_does_not_double_prefix_already_correct_cite(tmp_path):
    """A line with a CORRECT completed-tp-designs cite must NOT be prefixed again."""
    _completed(tmp_path, "gone-slug")
    # File has BOTH a dead cite AND an already-correct cite on the same line
    _skills_file(
        tmp_path,
        "mixed.py",
        "# tp-designs/gone-slug and completed-tp-designs/gone-slug on same line\n",
    )
    from reconcile_docs import repoint_cites

    edits = repoint_cites(tmp_path, slugs=None, apply=True)
    content = (tmp_path / "skills" / "mixed.py").read_text()
    assert "completed-completed-" not in content, (
        "repoint_cites must not double-prefix an already-correct cite"
    )
    assert content.count("completed-tp-designs/gone-slug") >= 1


def test_repoint_two_same_slug_cites_on_one_line(tmp_path):
    """Two dead cites for the same slug on one line — both repointed, no double-prefix."""
    _completed(tmp_path, "gone-slug")
    _skills_file(
        tmp_path,
        "double.py",
        "# tp-designs/gone-slug and tp-designs/gone-slug\n",
    )
    from reconcile_docs import repoint_cites

    edits = repoint_cites(tmp_path, slugs=None, apply=True)
    content = (tmp_path / "skills" / "double.py").read_text()
    assert "completed-completed-" not in content
    # Both should be corrected
    import re as _re
    assert not _re.search(r"(?<!completed-)tp-designs/gone-slug", content)


def test_repoint_prefix_sharing_slug_not_clobbered(tmp_path):
    """Archived 'foo' must NOT clobber live 'foo-bar' cite on the same line."""
    _completed(tmp_path, "foo")
    # foo-bar is a LIVE (tp-designs) design — not yet archived
    _tp_design(tmp_path, "foo-bar")
    _skills_file(
        tmp_path,
        "cites.py",
        # Both cites on the same line — exercises the line-local regex boundary guard.
        "# tp-designs/foo/design.md and tp-designs/foo-bar/design.md on same line\n",
    )
    from reconcile_docs import repoint_cites

    edits = repoint_cites(tmp_path, slugs=None, apply=True)
    content = (tmp_path / "skills" / "cites.py").read_text()
    # foo cite should be repointed
    assert "completed-tp-designs/foo/" in content
    # foo-bar cite must remain as-is (live design, not dead; lookahead blocks repoint of foo)
    assert "tp-designs/foo-bar" in content, (
        "foo-bar cite must not be clobbered by the foo repoint on the same line"
    )


def test_repoint_archived_prefix_slug_only_not_longer_slug(tmp_path):
    """Archived 'foo' repoint must not mangle a 'foo-bar' cite on the same line."""
    _completed(tmp_path, "foo")
    _completed(tmp_path, "foo-bar")
    # Both cites on the same line — the dead 'foo' cite and a correct 'foo-bar' cite.
    # The lookahead (?![a-z0-9-]) must prevent 'foo' from matching inside 'foo-bar'.
    _skills_file(
        tmp_path,
        "boundary.py",
        "# tp-designs/foo/design.md dead and completed-tp-designs/foo-bar/ok same line\n",
    )
    from reconcile_docs import repoint_cites

    edits = repoint_cites(tmp_path, slugs={"foo"}, apply=True)
    content = (tmp_path / "skills" / "boundary.py").read_text()
    assert "completed-completed-" not in content, (
        "double-prefix must never occur"
    )
    # The correct foo-bar cite must survive unchanged
    assert "completed-tp-designs/foo-bar" in content, (
        "existing foo-bar cite must not be mangled by the foo repoint"
    )
    # The dead foo cite must be corrected
    import re as _re
    assert not _re.search(r"(?<!completed-)tp-designs/foo(?![a-z0-9-])", content), (
        "dead foo cite must be repointed"
    )


# ------------------------------------------------------------------ #
# REGRESSION — structural fix 2: flip_status boundary-aware
# ------------------------------------------------------------------ #


def test_flip_status_does_not_affect_prefixed_live_design(tmp_path):
    """flip_status('foo') must not flip the row of 'foo-bar' (prefix containment)."""
    _completed(tmp_path, "foo")
    # foo-bar has its own live/pending row
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `foo` | Completion PR pending |\n"
        "| `foo-bar` | Completion PR pending |\n",
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "foo", pr_number=9, apply=True)
    content = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text()
    lines = content.splitlines()
    foo_line = next(l for l in lines if "`foo`" in l and "`foo-bar`" not in l)
    foo_bar_line = next(l for l in lines if "`foo-bar`" in l)
    assert "merged PR #9" in foo_line, "foo row must be flipped"
    assert "Completion PR pending" in foo_bar_line, "foo-bar row must NOT be flipped"


def test_flip_status_does_not_affect_substring_in_suffix(tmp_path):
    """flip_status('post-merge') must not flip 'post-merge-doc-reconcile' row."""
    _completed(tmp_path, "post-merge")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `post-merge` | Completion PR pending |\n"
        "| `post-merge-doc-reconcile` | Completion PR pending |\n",
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "post-merge", pr_number=42, apply=True)
    content = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text()
    lines = content.splitlines()
    short_line = next(l for l in lines if "`post-merge`" in l and "`post-merge-doc-reconcile`" not in l)
    long_line = next(l for l in lines if "`post-merge-doc-reconcile`" in l)
    assert "merged PR #42" in short_line, "post-merge row must be flipped"
    assert "Completion PR pending" in long_line, "post-merge-doc-reconcile must NOT be flipped"


def test_flip_status_slug_mentioned_in_notes_not_flipped(tmp_path):
    """A row that only mentions an archived slug in a notes column is not flipped."""
    _completed(tmp_path, "foo")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `bar` | Completion PR pending | relates to foo |\n",
    )
    from reconcile_docs import flip_status

    # flip_status for foo — the bar row should NOT be flipped just because
    # it mentions "foo" in the notes column (bar is the owning slug, not foo)
    edits = flip_status(tmp_path, "foo", pr_number=5, apply=True)
    content = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text()
    assert "Completion PR pending" in content, (
        "bar row must not be flipped just because it mentions foo in notes"
    )


# ------------------------------------------------------------------ #
# REGRESSION — minor fix 3: main() except preserves accumulated edits
# ------------------------------------------------------------------ #


def test_main_exception_emits_accumulated_edits_and_error(tmp_path, capsys):
    """Under --json: if mode dispatch raises after partial work, emits edits + error.

    Hermetic: --pr NN avoids merged_pr_number firing a real gh subprocess.
    The pre-exception repoint edit must SURVIVE in the edits payload (not just
    key presence — the actual edit content must reflect the repoint).
    """
    _completed(tmp_path, "gone-slug")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `gone-slug` | Completion PR pending |\n",
    )
    _skills_file(
        tmp_path,
        "foo.py",
        "# three-pillars-docs/tp-designs/gone-slug/design.md\n",
    )
    import reconcile_docs as _rd
    original_flip = _rd.flip_status_with_skipped

    def _exploding_flip(root, slug, pr_number, *, apply):
        raise RuntimeError("injected failure")

    _rd.flip_status_with_skipped = _exploding_flip
    try:
        from reconcile_docs import main
        ret = main([
            "reconcile_docs.py",
            "--slug", "gone-slug",
            "--pr", "77",       # hermetic: skip real gh subprocess
            "--repo", str(tmp_path),
            "--json",
        ])
    finally:
        _rd.flip_status_with_skipped = original_flip

    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    # Must carry an error field (flip_status_with_skipped exploded)
    assert "error" in data, "exception must be reported in JSON output"
    # Must preserve previously-accumulated edits (repoint ran before flip exploded)
    assert "edits" in data, "edits key must be present"
    # Verify the pre-exception repoint edit CONTENT survives — not just key presence
    repoint_edits = [e for e in data["edits"] if e.get("kind") == "repoint"]
    assert len(repoint_edits) >= 1, (
        "the repoint edit that ran before the flip exception must survive in edits"
    )
    assert "completed-tp-designs/gone-slug" in repoint_edits[0]["after"], (
        "pre-exception repoint edit must reflect the correct repoint text"
    )


# ------------------------------------------------------------------ #
# REGRESSION — minor fix 4: --archive-cites validation and mode group
# ------------------------------------------------------------------ #


def test_cli_archive_cites_without_slug_errors_plain_mode(tmp_path, capsys):
    """--archive-cites without --slug must print an error in plain mode (not silent)."""
    from reconcile_docs import main

    ret = main(["reconcile_docs.py", "--archive-cites", "--repo", str(tmp_path)])
    assert ret == 0  # always exits 0
    captured = capsys.readouterr()
    # Must print an error message (not silently exit)
    assert "error" in captured.out.lower() or "require" in captured.out.lower(), (
        "--archive-cites without --slug must not silently exit in plain mode"
    )


def test_cli_sweep_and_archive_cites_are_exclusive(tmp_path, capsys):
    """--sweep --archive-cites must emit an error JSON and NOT run sweep.

    With the reordered validation (sweep+archive-cites check runs BEFORE
    requires-slug check), this path is now reachable and always hits the
    sweep+archive-cites conflict block (not the requires-slug block).
    """
    _completed(tmp_path, "my-slug")
    _skills_file(tmp_path, "foo.py", "# tp-designs/my-slug/design.md\n")
    from reconcile_docs import main

    # --sweep and --archive-cites together (no --slug: avoids argparse mutex,
    # hits the post-parse sweep+archive-cites validation block first)
    ret = main([
        "reconcile_docs.py",
        "--sweep",
        "--archive-cites",
        "--repo", str(tmp_path),
        "--json",
    ])
    assert ret == 0
    captured = capsys.readouterr()
    # Must emit error JSON (the sweep+archive-cites conflict block runs)
    out = captured.out.strip()
    assert out, "sweep+archive-cites must emit JSON output (not be silently swallowed)"
    data = json.loads(out)
    assert "error" in data, "sweep+archive-cites must emit error in JSON mode"
    assert "mutually exclusive" in data["error"], (
        "error message must identify the sweep+archive-cites conflict"
    )
    assert data["edits"] == [], "sweep+archive-cites must NOT run sweep (no edits)"


# ------------------------------------------------------------------ #
# REGRESSION — minor fix 7: reconcile_slug resolves PR in plan mode
# ------------------------------------------------------------------ #


def test_reconcile_slug_plan_mode_shows_pr_resolution(tmp_path):
    """dry-run plan mode should preview the merged PR #99 text, not generic 'merged'.

    Asserts:
    - The planned flip edit text contains 'merged PR #99' (not 'merged' alone).
    - The fake gh function was actually called (PR lookup fired in plan mode).
    """
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending |\n",
    )

    import reconcile_docs as _rd
    # Inject a fake gh function that returns PR 99
    gh_calls = []

    def _fake_gh(*args, **kwargs):
        gh_calls.append((args, kwargs))
        class _R:
            returncode = 0
            stdout = '[{"number": 99}]'
        return _R()

    original_merged_pr = _rd.merged_pr_number

    def _patched_merged_pr(root, slug, gh_fn=None):
        return original_merged_pr(root, slug, gh_fn=_fake_gh)

    _rd.merged_pr_number = _patched_merged_pr
    try:
        from reconcile_docs import reconcile_slug
        edits = reconcile_slug(tmp_path, "my-design", pr_number=None, apply=False)
    finally:
        _rd.merged_pr_number = original_merged_pr

    # Plan mode edits should reflect that the status flip is planned
    flip_edits = [e for e in edits if e.kind == "status-flip"]
    assert len(flip_edits) >= 1, (
        "reconcile_slug plan mode must include the status-flip edit in the plan"
    )
    # The planned edit text must contain 'merged PR #99', NOT just 'merged'
    flip_after = flip_edits[0].after
    assert "merged PR #99" in flip_after, (
        f"planned edit text must contain 'merged PR #99', got: {flip_after!r}"
    )
    # The fake gh function must have been called (PR lookup runs in plan mode)
    assert len(gh_calls) >= 1, (
        "fake gh must be called in plan mode — merged_pr_number must fire before apply"
    )


# ------------------------------------------------------------------ #
# REGRESSION — structural fix R2.1: flip_status owner-cell attribution
# (table-cell position, not token hunting)
# ------------------------------------------------------------------ #


def test_flip_status_unbackticked_owner_cell_is_attributed(tmp_path):
    """An unbackticked owner cell ('foo' not '`foo`') must be correctly attributed."""
    _completed(tmp_path, "foo")
    # Owner cell is unbackticked: 'foo' not '`foo`'
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| foo | Completion PR pending |\n",
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "foo", pr_number=7, apply=False)
    assert len(edits) == 1, (
        "unbackticked owner cell must be attributed by cell position, not backtick hunt"
    )
    assert "merged PR #7" in edits[0].after


def test_flip_status_backtick_in_notes_column_does_not_attribute(tmp_path):
    """A backticked slug in a notes column must NOT attribute the row to that slug.

    Row: | bar | Completion PR pending | supersedes `foo` |
    flip_status('foo') must NOT flip this row — bar is the owner.
    """
    _completed(tmp_path, "foo")
    _completed(tmp_path, "bar")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `bar` | Completion PR pending | supersedes `foo` |\n",
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "foo", pr_number=5, apply=False)
    assert edits == [], (
        "backticked slug in notes column must not attribute the row to that slug"
    )


def test_flip_status_backtick_in_notes_owner_row_unaffected(tmp_path):
    """When flip_status('foo') runs, it must flip the `foo` row, not the `bar` row
    that has `foo` in a notes column.

    Verifies both directions: foo flipped, bar untouched.
    """
    _completed(tmp_path, "foo")
    _completed(tmp_path, "bar")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `foo` | Completion PR pending |\n"
        "| `bar` | Completion PR pending | see `foo` results |\n",
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "foo", pr_number=3, apply=True)
    content = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text()
    lines_with_foo = [l for l in content.splitlines() if "foo" in l and "bar" not in l]
    lines_with_bar = [l for l in content.splitlines() if "`bar`" in l]
    assert any("merged PR #3" in l for l in lines_with_foo), "foo row must be flipped"
    assert any("Completion PR pending" in l for l in lines_with_bar), (
        "bar row must NOT be flipped when only foo mentions appear in notes"
    )


def test_flip_status_prose_line_never_flipped(tmp_path):
    """A non-table, non-bullet prose line mentioning the slug MUST NOT be flipped.

    With the directory-resolution design, owner_slug_of_row returns None for
    non-table/non-bullet lines, so they are always SKIPPED. No whole-line
    fallback exists.
    """
    _completed(tmp_path, "my-design")
    # Plain prose line — NOT a table row and NOT a bullet
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "my-design status: Completion PR pending\n",
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "my-design", pr_number=11, apply=False)
    assert edits == [], (
        "non-table non-bullet prose lines mentioning the slug must NEVER be flipped "
        "(no whole-line fallback exists in the directory-resolution design)"
    )


def test_flip_status_notes_column_slug_never_attributed(tmp_path):
    """'| **bar** | Completion PR pending | supersedes `foo` |' must NOT flip for foo.

    The table owner cell is 'bar' (resolves via its design dir); the notes cell
    mentions foo (backticked). flip_status(foo) must skip this row entirely.
    """
    _completed(tmp_path, "foo")
    _completed(tmp_path, "bar")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| **`bar`** | Completion PR pending | supersedes `foo` |\n",
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "foo", pr_number=5, apply=False)
    assert edits == [], (
        "slug mentioned only in a notes cell must NOT cause its row to be flipped"
    )


def test_flip_status_owner_cell_resolves_notes_slug_cannot_outattribute(tmp_path):
    """When owner cell resolves to 'bar', notes cell mentioning 'foo' must not attribute.

    Construct: bar in owner cell (resolves), foo in notes cell.
    flip_status(foo) must return no edits.
    flip_status(bar) must return the edit.
    """
    _completed(tmp_path, "foo")
    _completed(tmp_path, "bar")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| bar | Completion PR pending | relates to foo |\n",
    )
    from reconcile_docs import flip_status

    # foo must NOT be attributed (bar is the owner)
    edits_foo = flip_status(tmp_path, "foo", pr_number=5, apply=False)
    assert edits_foo == [], (
        "foo in notes cell must not attribute when bar resolves as owner cell"
    )
    # bar MUST be attributed (bar is the owner)
    edits_bar = flip_status(tmp_path, "bar", pr_number=5, apply=False)
    assert len(edits_bar) == 1, (
        "bar in owner cell must be attributed correctly"
    )


# ------------------------------------------------------------------ #
# REGRESSION — structural fix R2.2: flip_status anchored substitution
# (replace only the last STALE_STATUS_RE match — prose survives)
# ------------------------------------------------------------------ #


def test_flip_status_prose_mention_survives_status_flip(tmp_path):
    """When a row contains a quoted prose mention of 'Completion PR pending' AND
    a real trailing status on the same line, only the status (last match) is
    replaced — the prose mention must survive intact.

    This is the exact shape of product_roadmap.md line ~96 for this design's row.
    """
    _completed(tmp_path, "post-merge-doc-reconcile")
    # Reproduce the real line-96 shape: prose mention + real trailing status
    prose_line = (
        '| `post-merge-doc-reconcile` | Done (2026-06-10) — fixes stale '
        '"Completion PR pending" rows and dead cites. Completion PR pending (Tier 6). |'
    )
    _roadmap(
        tmp_path,
        f"*Last updated: 2026-01-01*\n\n## Designs\n\n{prose_line}\n",
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "post-merge-doc-reconcile", pr_number=76, apply=True)
    assert len(edits) == 1, "exactly one flip edit must be produced"
    after = edits[0].after
    # Prose mention must survive
    assert '"Completion PR pending"' in after, (
        "quoted prose mention of 'Completion PR pending' must NOT be rewritten"
    )
    # Real trailing status must be replaced
    assert "merged PR #76" in after, (
        "real trailing status must be replaced with 'merged PR #76'"
    )
    # The last occurrence must not remain as the original status
    import re as _re
    remaining = list(_re.finditer(r"Completion PR pending", after))
    # Only the quoted prose mention should remain, not a bare trailing status
    for m in remaining:
        context = after[max(0, m.start()-1):m.end()+1]
        assert '"' in context or "'" in context, (
            f"remaining 'Completion PR pending' at pos {m.start()} must be quoted/prose, "
            f"not a bare status cell: {context!r}"
        )


# ------------------------------------------------------------------ #
# REGRESSION — double-apply idempotency on real line-96 shape
# ------------------------------------------------------------------ #


def test_flip_double_apply_idempotent_on_prose_plus_status_line(tmp_path):
    """Double-apply on line-96 shape must be a no-op on the second pass.

    Shape: quoted prose mention of 'Completion PR pending' + trailing real status.
    First apply flips the real status. Second apply must find zero unquoted matches
    (the surviving mention is inside quotes) and make no edit.

    This pins the quote-aware flip against re-run corruption.
    """
    _completed(tmp_path, "post-merge-doc-reconcile")
    prose_line = (
        '| `post-merge-doc-reconcile` | Done (2026-06-10) — fixes stale '
        '"Completion PR pending" rows and dead cites. Completion PR pending (Tier 6). |'
    )
    _roadmap(
        tmp_path,
        f"*Last updated: 2026-01-01*\n\n## Designs\n\n{prose_line}\n",
    )
    from reconcile_docs import flip_status

    first = flip_status(tmp_path, "post-merge-doc-reconcile", pr_number=76, apply=True)
    assert len(first) == 1, "first apply must flip exactly one match"

    second = flip_status(tmp_path, "post-merge-doc-reconcile", pr_number=76, apply=True)
    assert second == [], (
        "second apply on already-flipped line must be a no-op "
        "(quoted prose mention must not be re-flipped)"
    )


def test_flip_status_before_notes_layout(tmp_path):
    """Status-before-Notes layout: real status cell comes before a notes cell.

    Row: | bar | Completion PR pending | fixes stale "Completion PR pending" rows |
    The notes column contains a quoted prose mention of the status text.
    Only the status cell (the unquoted match) must be flipped; the quoted notes
    mention must survive.
    """
    _completed(tmp_path, "bar")
    status_line = (
        '| `bar` | Completion PR pending | fixes stale "Completion PR pending" rows |'
    )
    _roadmap(
        tmp_path,
        f"*Last updated: 2026-01-01*\n\n## Designs\n\n{status_line}\n",
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "bar", pr_number=99, apply=True)
    assert len(edits) == 1, "exactly one edit must be produced"
    after = edits[0].after
    # Real status must be replaced
    assert "merged PR #99" in after, "real status cell must be replaced"
    # Quoted prose mention must survive
    assert '"Completion PR pending"' in after, (
        "quoted prose mention in notes column must survive"
    )


def test_flip_status_priority_first_table_owner_resolution(tmp_path):
    """Priority-first table: '| seeded | **`my-design`** | ... |' must flip for my-design.

    Cell 1 'seeded' does not directory-resolve, cell 2 'my-design' does.
    The first directory-resolving cell is the owner.
    """
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| seeded | **`my-design`** | Completion PR pending |\n",
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "my-design", pr_number=42, apply=False)
    assert len(edits) == 1, (
        "priority-first table: my-design in cell 2 must resolve as owner "
        "when cell 1 'seeded' does not directory-resolve"
    )
    assert "merged PR #42" in edits[0].after


def test_flip_status_bold_owner_cell_resolves(tmp_path):
    """A bold owner cell '**`my-design`**' must resolve correctly.

    The strip_markup step removes ** and `` to expose the slug.
    """
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| **`my-design`** | Completion PR pending |\n",
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "my-design", pr_number=7, apply=False)
    assert len(edits) == 1, "bold owner cell must be correctly attributed"
    assert "merged PR #7" in edits[0].after


# ------------------------------------------------------------------ #
# REGRESSION — repoint_cites Last-updated bump pin
# ------------------------------------------------------------------ #


def test_repoint_cites_bumps_last_updated_on_living_doc(tmp_path):
    """repoint_cites must bump *Last updated:* when applying to a living doc.

    Mutation-kill test: deleting the _bump_last_updated call must fail this test.
    """
    _completed(tmp_path, "gone-slug")
    _living_doc(
        tmp_path,
        "product_roadmap.md",
        "*Last updated: 2020-01-01*\n\n"
        "See three-pillars-docs/tp-designs/gone-slug/design.md\n",
    )
    import datetime
    from reconcile_docs import repoint_cites

    edits = repoint_cites(tmp_path, slugs=None, apply=True)
    assert len(edits) >= 1
    content = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text()
    today = datetime.date.today().isoformat()
    assert today in content, (
        "repoint_cites must bump *Last updated:* date when touching a living doc"
    )


# ------------------------------------------------------------------ #
# REGRESSION — structural fix R2.3: merged_pr_number uses repo_root cwd
# ------------------------------------------------------------------ #


def test_merged_pr_number_passes_cwd_to_gh(tmp_path):
    """merged_pr_number must pass cwd=str(repo_root) to the gh subprocess.

    Injected gh_fn captures kwargs; asserts cwd is set to the repo_root path.
    """
    captured_kwargs = {}

    def _fake_gh(*args, **kwargs):
        captured_kwargs.update(kwargs)
        class _R:
            returncode = 0
            stdout = '[{"number": 42}]'
        return _R()

    from reconcile_docs import merged_pr_number

    result = merged_pr_number(tmp_path, "my-slug", gh_fn=_fake_gh)
    assert result == 42
    assert "cwd" in captured_kwargs, (
        "merged_pr_number must pass cwd= to the gh subprocess"
    )
    assert captured_kwargs["cwd"] == str(tmp_path), (
        f"cwd must be str(repo_root)={str(tmp_path)!r}, got {captured_kwargs['cwd']!r}"
    )


# ------------------------------------------------------------------ #
# Round-4 findings — F1: skipped collection surfaced in CLI + flip_status
# ------------------------------------------------------------------ #


def test_flip_status_with_skipped_returns_tuple(tmp_path):
    """flip_status_with_skipped must return (edits, skipped)."""
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending |\n",
    )
    from reconcile_docs import flip_status_with_skipped

    edits, skipped = flip_status_with_skipped(tmp_path, "my-design", pr_number=5, apply=False)
    assert isinstance(edits, list)
    assert isinstance(skipped, list)
    assert len(edits) == 1
    assert skipped == []


def test_flip_status_with_skipped_ambiguous(tmp_path):
    """A row with >1 unquoted STALE_STATUS_RE matches must be in skipped."""
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending | also Completion PR pending |\n",
    )
    from reconcile_docs import flip_status_with_skipped

    edits, skipped = flip_status_with_skipped(tmp_path, "my-design", pr_number=5, apply=False)
    assert len(edits) == 0
    assert len(skipped) == 1
    s = skipped[0]
    assert s["reason"] == "ambiguous-multi-match"
    assert "line_no" in s or "line" in s
    assert "file" in s


def test_reconcile_slug_returns_skipped(tmp_path):
    """reconcile_slug must expose skipped entries from flip_status."""
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending | also Completion PR pending |\n",
    )
    from reconcile_docs import reconcile_slug_with_skipped

    edits, skipped = reconcile_slug_with_skipped(tmp_path, "my-design", pr_number=5, apply=False)
    assert any(s["reason"] == "ambiguous-multi-match" for s in skipped)


def test_sweep_returns_skipped(tmp_path):
    """sweep must expose skipped entries."""
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending | also Completion PR pending |\n",
    )

    def _fake_live_branches(repo_root, ls_remote_fn=None):
        return set()  # all branches absent

    from reconcile_docs import sweep_with_skipped

    edits, skipped = sweep_with_skipped(
        tmp_path, apply=False, remote=True, _live_branches_fn=_fake_live_branches
    )
    assert any(s["reason"] == "ambiguous-multi-match" for s in skipped)


def test_cli_json_skipped_key_in_slug_mode(tmp_path, capsys):
    """CLI --json payload must include 'skipped' key in --slug mode."""
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


def test_cli_json_skipped_key_in_sweep_mode(tmp_path, capsys):
    """CLI --json payload must include 'skipped' key in --sweep mode."""
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
        "--sweep",
        "--no-remote",
        "--repo", str(tmp_path),
        "--json",
    ])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "skipped" in data, "CLI --json payload must include 'skipped' key in sweep mode"


def test_cli_plain_text_skipped_reported(tmp_path, capsys):
    """CLI plain-text output must report skipped rows."""
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
    ])
    assert ret == 0
    captured = capsys.readouterr()
    assert "skip" in captured.out.lower(), (
        "plain-text output must report skipped rows"
    )


# ------------------------------------------------------------------ #
# Round-4 findings — F6: decode-failure write path (U+FFFD guard)
# ------------------------------------------------------------------ #


def test_write_path_skips_file_with_undecodable_bytes(tmp_path):
    """Writer must skip a file that would introduce U+FFFD and add it to skipped."""
    _completed(tmp_path, "my-design")
    roadmap_path = tmp_path / "three-pillars-docs" / "product_roadmap.md"
    roadmap_path.parent.mkdir(parents=True, exist_ok=True)
    # Valid content + invalid UTF-8 bytes
    content = (
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending |\n"
    )
    roadmap_path.write_bytes(content.encode("utf-8") + b"\xff\xfe garbage\n")
    from reconcile_docs import flip_status_with_skipped

    edits, skipped = flip_status_with_skipped(tmp_path, "my-design", pr_number=5, apply=True)
    # File must NOT have been written with U+FFFD
    written = roadmap_path.read_bytes()
    assert b"\xef\xbf\xbd" not in written, (
        "writer must not introduce U+FFFD into the written file"
    )
    # Skipped must contain decode-failure entry
    reasons = [s["reason"] for s in skipped]
    assert "decode-failure" in reasons, (
        "decode-failure must be reported in skipped when file has undecodable bytes"
    )


# ------------------------------------------------------------------ #
# Round-6 findings — F1: repoint_cites skipped channel (decode-failure)
# ------------------------------------------------------------------ #


def test_repoint_cites_undecodable_file_emits_skipped(tmp_path):
    """repoint_cites_with_skipped must emit a decode-failure skipped entry for a
    corrupted file in BOTH plan and apply modes — not silently drop it.

    The pre-fix silent-skip behavior: repoint_cites returned [] with no skipped
    channel, so a dead cite in a corrupted file was silently dropped.
    Now repoint_cites_with_skipped must return ([], [{"reason": "decode-failure"}]).
    """
    _completed(tmp_path, "my-design")
    # Create a corrupted skills file with a dead cite
    skills_file = tmp_path / "skills" / "module.py"
    skills_file.parent.mkdir(parents=True, exist_ok=True)
    content = b"# See three-pillars-docs/tp-designs/my-design/design.md\n"
    skills_file.write_bytes(content + b"\xff\xfe bad\n")

    from reconcile_docs import repoint_cites_with_skipped

    # Plan mode
    plan_edits, plan_skipped = repoint_cites_with_skipped(tmp_path, apply=False)
    assert len(plan_edits) == 0, "corrupted file must produce 0 edits in plan mode"
    assert any(s["reason"] == "decode-failure" for s in plan_skipped), (
        "plan mode must emit decode-failure skipped for corrupted file with dead cite"
    )

    # Apply mode
    apply_edits, apply_skipped = repoint_cites_with_skipped(tmp_path, apply=True)
    assert len(apply_edits) == 0, "corrupted file must produce 0 edits in apply mode"
    assert any(s["reason"] == "decode-failure" for s in apply_skipped), (
        "apply mode must emit decode-failure skipped for corrupted file with dead cite"
    )


def test_archive_cites_slug_mode_skipped_in_cli_payload(tmp_path, capsys):
    """CLI --slug --archive-cites mode must include 'skipped' with decode-failure
    when the cited file is undecodable.
    """
    _completed(tmp_path, "my-design")
    skills_file = tmp_path / "skills" / "module.py"
    skills_file.parent.mkdir(parents=True, exist_ok=True)
    skills_file.write_bytes(
        b"# See three-pillars-docs/tp-designs/my-design/design.md\n"
        b"\xff\xfe corrupt\n"
    )
    from reconcile_docs import main

    ret = main([
        "reconcile_docs.py",
        "--slug", "my-design",
        "--archive-cites",
        "--repo", str(tmp_path),
        "--json",
    ])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "skipped" in data, "CLI --archive-cites --json payload must include 'skipped' key"
    assert any(s.get("reason") == "decode-failure" for s in data["skipped"]), (
        "CLI --archive-cites must surface decode-failure skipped for corrupted file"
    )


def test_slug_cli_skipped_in_payload(tmp_path, capsys):
    """CLI plain --slug mode must include 'skipped' with decode-failure when the
    cited file is undecodable.

    This pins the plain --slug CLI branch (not --archive-cites). Reverting that
    branch to discard repoint skipped entries must fail this test.
    """
    _completed(tmp_path, "my-design")
    skills_file = tmp_path / "skills" / "module.py"
    skills_file.parent.mkdir(parents=True, exist_ok=True)
    skills_file.write_bytes(
        b"# See three-pillars-docs/tp-designs/my-design/design.md\n"
        b"\xff\xfe corrupt\n"
    )
    from reconcile_docs import main

    ret = main([
        "reconcile_docs.py",
        "--slug", "my-design",
        "--repo", str(tmp_path),
        "--json",
    ])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "skipped" in data, "CLI --slug --json payload must include 'skipped' key"
    assert any(s.get("reason") == "decode-failure" for s in data["skipped"]), (
        "CLI --slug must surface decode-failure skipped for corrupted cited file"
    )


def test_reconcile_slug_with_skipped_surfaces_repoint_decode_failure(tmp_path):
    """reconcile_slug_with_skipped (library API) must surface repoint decode-failure
    entries when the cited file is undecodable.

    Docstring contract: 'decode-failure entries from both sub-steps are surfaced here'.
    Discarding repoint_skipped in the library function must fail this test.
    """
    _completed(tmp_path, "my-design")
    skills_file = tmp_path / "skills" / "module.py"
    skills_file.parent.mkdir(parents=True, exist_ok=True)
    skills_file.write_bytes(
        b"# See three-pillars-docs/tp-designs/my-design/design.md\n"
        b"\xff\xfe corrupt\n"
    )
    from reconcile_docs import reconcile_slug_with_skipped

    edits, skipped = reconcile_slug_with_skipped(tmp_path, "my-design", apply=False)
    assert len(edits) == 0, (
        "corrupted cited file must produce 0 edits in plan mode"
    )
    assert any(s.get("reason") == "decode-failure" for s in skipped), (
        "reconcile_slug_with_skipped must surface decode-failure from repoint sub-step"
    )


def test_reconcile_slug_with_skipped_dedupes_skipped_entries(tmp_path):
    """A decode-broken file that also carries a dead cite produces exactly one
    decode-failure entry — not two — in the reconcile_slug_with_skipped payload.

    This pins the (file, line_no, reason) dedupe sweep on the concatenated
    repoint+flip skipped lists.

    The fixture uses product_roadmap.md because that file is scanned by BOTH
    sub-steps:
      - repoint_cites_with_skipped scans it via dead_design_cites (living-doc scope)
      - flip_status_with_skipped reads it directly for status-row rewriting
    Both sub-steps encounter the undecodable bytes and each emit a decode-failure
    entry for the roadmap.  Without the dedupe sweep the count would be 2; with it
    the count must be exactly 1.
    """
    _completed(tmp_path, "my-design")
    # product_roadmap.md: carries a dead cite (triggering repoint) AND undecodable
    # bytes (triggering decode-failure in both repoint and flip sub-steps).
    roadmap_file = tmp_path / "three-pillars-docs" / "product_roadmap.md"
    roadmap_file.parent.mkdir(parents=True, exist_ok=True)
    roadmap_file.write_bytes(
        b"# Product Roadmap\n\n"
        b"See three-pillars-docs/tp-designs/my-design/design.md\n"
        b"\xff corrupt byte\n"
    )
    from reconcile_docs import reconcile_slug_with_skipped

    edits, skipped = reconcile_slug_with_skipped(tmp_path, "my-design", apply=False)
    decode_failures = [s for s in skipped if s.get("reason") == "decode-failure"]
    # Dedupe must collapse the two sub-step entries to exactly one.
    assert len(decode_failures) == 1, (
        "reconcile_slug_with_skipped must deduplicate decode-failure entries: "
        f"got {len(decode_failures)} entries, expected exactly 1"
    )


def test_repoint_cites_sweep_skipped_in_cli_payload(tmp_path, capsys):
    """CLI --sweep mode must include decode-failure skipped for corrupted files."""
    _completed(tmp_path, "my-design")
    skills_file = tmp_path / "skills" / "module.py"
    skills_file.parent.mkdir(parents=True, exist_ok=True)
    skills_file.write_bytes(
        b"# See three-pillars-docs/tp-designs/my-design/design.md\n"
        b"\xff\xfe corrupt\n"
    )
    from reconcile_docs import main

    ret = main([
        "reconcile_docs.py",
        "--sweep",
        "--no-remote",
        "--repo", str(tmp_path),
        "--json",
    ])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "skipped" in data
    assert any(s.get("reason") == "decode-failure" for s in data["skipped"]), (
        "CLI --sweep must surface decode-failure skipped for corrupted file"
    )


# ------------------------------------------------------------------ #
# Round-6 findings — F2: bullet-flip positive path pinned
# ------------------------------------------------------------------ #


def test_bullet_status_flip_positive_path(tmp_path):
    """An unquoted bullet stale status must flip to 'merged PR #N'.

    This pins the positive flip path for bullet rows. Mutation-deleting bullet
    flipping from the flip loop must fail this test.
    """
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "- `my-design` — Completion PR pending\n",
    )
    from reconcile_docs import flip_status_with_skipped

    edits, skipped = flip_status_with_skipped(tmp_path, "my-design", pr_number=42, apply=False)
    assert len(edits) == 1, (
        "unquoted bullet stale status must produce exactly 1 edit"
    )
    assert "merged PR #42" in edits[0].after, (
        "bullet status flip must rewrite to 'merged PR #42'"
    )
    assert skipped == [], "no skipped entries expected for clean bullet flip"


# ------------------------------------------------------------------ #
# Round-6 findings — F3: sweep N-fold duplicate skips deduplication
# ------------------------------------------------------------------ #


def test_sweep_deduplicates_unattributable_skipped_entries(tmp_path):
    """sweep_with_skipped must deduplicate skipped entries by (file, line_no, reason).

    When multiple archived slugs are absent from live branches, the per-slug
    flip_status loop emits one identical 'unattributable' entry per slug for the
    same unattributable row. With N absent slugs, this produces N duplicates.
    After the fix, exactly 1 skipped entry must appear for the row.
    """
    # Create 3 archived slugs
    for slug in ("alpha", "beta", "gamma"):
        _completed(tmp_path, slug)

    # Roadmap has one unattributable row (no cell resolves to a directory)
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| unresolvable-row | Completion PR pending |\n",
    )

    def _no_live_branches(repo_root, ls_remote_fn=None):
        return set()  # all 3 slugs absent

    from reconcile_docs import sweep_with_skipped

    edits, skipped = sweep_with_skipped(
        tmp_path, apply=False, remote=True, _live_branches_fn=_no_live_branches
    )
    unattributable = [s for s in skipped if s["reason"] == "unattributable"]
    assert len(unattributable) == 1, (
        f"Expected exactly 1 deduplicated unattributable entry, got {len(unattributable)}: "
        f"{unattributable}"
    )


# ------------------------------------------------------------------ #
# Round-6 findings — F4: quoted-prose vs attribution ordering
# ------------------------------------------------------------------ #


def test_quoted_only_non_attributable_line_not_skipped(tmp_path):
    """A fully-quoted status mention on a non-attributable line must NOT produce a
    skipped entry.

    Without the ordering fix, attribution runs first: the line is unattributable
    → emits 'unattributable' skipped entry. With the fix, zero-unquoted-matches
    is checked BEFORE attribution, so quoted-only mentions are silently suppressed.
    """
    _completed(tmp_path, "my-design")
    # The row has no cell that resolves to a directory (unattributable) BUT
    # the status mention is fully inside quotes (should be suppressed silently).
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        '| some-note | "Completion PR pending" |\n',
    )
    from reconcile_docs import flip_status_with_skipped

    edits, skipped = flip_status_with_skipped(
        tmp_path, "my-design", pr_number=1, apply=False
    )
    assert len(edits) == 0, "quoted-only status must produce no edits"
    assert skipped == [], (
        "quoted-only non-attributable status must NOT produce an unattributable "
        "skipped entry — zero-unquoted-matches check must run before attribution"
    )


def test_genuine_unattributable_stale_row_still_reported(tmp_path):
    """A genuinely unquoted unattributable stale row must still be reported.

    This ensures the ordering fix doesn't suppress real unattributable rows.
    """
    _completed(tmp_path, "my-design")
    # The row has an unquoted status mention but no resolving cell
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| unresolvable-row | Completion PR pending |\n",
    )
    from reconcile_docs import flip_status_with_skipped

    edits, skipped = flip_status_with_skipped(
        tmp_path, "my-design", pr_number=1, apply=False
    )
    assert len(edits) == 0, "unattributable row must produce no edits"
    assert any(s["reason"] == "unattributable" for s in skipped), (
        "genuine unquoted unattributable row must still be reported as 'unattributable'"
    )


# ------------------------------------------------------------------ #
# Round-6 findings — F6: superseded- prefix — repoint_cites must not rewrite
# ------------------------------------------------------------------ #


def test_repoint_cites_does_not_rewrite_superseded_path(tmp_path):
    """repoint_cites must NOT rewrite superseded-tp-designs/{slug} paths.

    Without the (?<!superseded-) lookbehind in _repoint_line, a cite like
    'superseded-tp-designs/my-design' would be rewritten to
    'superseded-completed-tp-designs/my-design' (invalid path).
    """
    _completed(tmp_path, "my-design")
    # Create a living doc with a superseded- cite (not a dead cite)
    _living_doc(
        tmp_path,
        "product_roadmap.md",
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "See three-pillars-docs/superseded-tp-designs/my-design for prior art.\n",
    )
    from reconcile_docs import repoint_cites_with_skipped

    edits, skipped = repoint_cites_with_skipped(tmp_path, apply=False)
    # Must produce 0 edits — superseded- path must not be touched
    assert len(edits) == 0, (
        "repoint_cites must NOT rewrite superseded-tp-designs/{slug} paths"
    )


def test_repoint_cites_mixed_line_dead_and_superseded(tmp_path):
    """repoint_cites on a line with BOTH a dead cite AND a superseded cite must
    rewrite only the dead cite; the superseded cite must be byte-identical.

    This pins the (?<!superseded-) lookbehind in _repoint_line. Removing it causes
    the superseded cite to be rewritten to 'superseded-completed-tp-designs/{slug}'
    (invalid path), which must fail this test.
    """
    _completed(tmp_path, "my-design")
    # Line carries two cites for the same slug:
    #   dead:       three-pillars-docs/tp-designs/my-design/design.md
    #   superseded: three-pillars-docs/superseded-tp-designs/my-design
    mixed_line = (
        "See three-pillars-docs/tp-designs/my-design/design.md "
        "and three-pillars-docs/superseded-tp-designs/my-design for prior art.\n"
    )
    _living_doc(
        tmp_path,
        "product_roadmap.md",
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        + mixed_line,
    )
    from reconcile_docs import repoint_cites_with_skipped

    edits, skipped = repoint_cites_with_skipped(tmp_path, apply=False)
    # Exactly one edit: the dead tp-designs/ cite is rewritten
    assert len(edits) == 1, (
        "mixed line must produce exactly 1 edit (dead cite only)"
    )
    assert "completed-tp-designs/my-design" in edits[0].after, (
        "dead cite must be rewritten to completed-tp-designs/my-design"
    )
    # superseded- cite must remain byte-identical in the rewritten line
    assert "superseded-tp-designs/my-design" in edits[0].after, (
        "(?<!superseded-) lookbehind must preserve the superseded cite unchanged"
    )
    # The superseded cite must NOT be doubled/corrupted
    assert "superseded-completed-tp-designs" not in edits[0].after, (
        "removing (?<!superseded-) lookbehind would mangle superseded cite — "
        "this test must fail if the lookbehind is absent"
    )


# ------------------------------------------------------------------ #
# Round-6 findings — F8: tautology test repairs
# ------------------------------------------------------------------ #

# test_flip_status_plan_and_apply_agree_on_undecodable is above in F4 section
# (test is repaired below — it must use apply=True for the second call)


def test_flip_status_plan_and_apply_differ_correctly_on_decode(tmp_path):
    """flip_status plan (apply=False) and apply (apply=True) must both skip
    undecodable files with a decode-failure entry.

    The old tautology: both calls used apply=False (comparing a call to itself).
    This test uses apply=True for the second call. The apply call must still
    return 0 edits + decode-failure skip (not attempt to write and corrupt).
    """
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
        tmp_path, "my-design", pr_number=5, apply=True  # apply=True — not a tautology
    )
    assert len(plan_edits) == 0, "plan mode: undecodable file must produce 0 edits"
    assert len(apply_edits) == 0, "apply mode: undecodable file must produce 0 edits"
    assert any(s["reason"] == "decode-failure" for s in plan_skipped), (
        "plan mode must report decode-failure for undecodable file"
    )
    assert any(s["reason"] == "decode-failure" for s in apply_skipped), (
        "apply mode must report decode-failure for undecodable file"
    )
    # File must NOT have been written with corruption
    written = roadmap_path.read_bytes()
    assert b"\xef\xbf\xbd" not in written, (
        "apply mode must not write U+FFFD into undecodable file"
    )
