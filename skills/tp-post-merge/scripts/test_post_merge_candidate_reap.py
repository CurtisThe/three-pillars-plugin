"""Prose tests pinning the tp-post-merge candidate-reap wire-in (B9, Task 3.2).

Read the *shipped* `skills/tp-post-merge/SKILL.md` (resolved from the git
toplevel) and assert teardown reaps ALL of the just-merged slug's candidate ids
via the reaper (fail-open), the two summary cite sites are generalized to "any
id", and the backfill sweep's `sweep_candidates.py`-only `/single` invariant is
left intact. Assertions key on content, not exact line numbers.
"""

import subprocess
from pathlib import Path

import pytest


def _toplevel() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


@pytest.fixture
def skill_md_text() -> str:
    path = _toplevel() / "skills" / "tp-post-merge" / "SKILL.md"
    return path.read_text(encoding="utf-8")


def _teardown_reaper_block(text: str) -> str:
    """The teardown step(s) that invoke the reaper — the paragraph(s) mentioning
    gc_candidate_branches.py within the teardown steps (5f/5g region)."""
    lines = text.splitlines()
    hits = [ln for ln in lines if "gc_candidate_branches.py" in ln]
    assert hits, (
        "expected a teardown step invoking `gc_candidate_branches.py`; found none"
    )
    return "\n".join(hits)


def test_teardown_invokes_reaper_with_slug_apply(skill_md_text: str) -> None:
    """Teardown invokes the reaper scoped to the merged slug with --apply,
    reaping ALL candidate ids (not just /single)."""
    block = _teardown_reaper_block(skill_md_text)
    assert "--slug {name}" in block, (
        "teardown reaper invocation must be scoped `--slug {name}`; got: " + block
    )
    assert "--apply" in block, (
        "teardown reaper invocation must pass `--apply`; got: " + block
    )
    # The whole point of B9: reap ANY candidate id, not the hard-coded /single.
    assert "/single" not in block, (
        "teardown reaper step must NOT hard-code the `/single` id — the reaper "
        "reaps all of the slug's candidate ids; got: " + block
    )


def test_teardown_reaper_is_fail_open(skill_md_text: str) -> None:
    """The reaper teardown step is explicitly fail-open (a reap failure never
    aborts teardown)."""
    lines = skill_md_text.splitlines()
    # Find the region around the reaper invocation and assert fail-open prose.
    idx = next(i for i, ln in enumerate(lines) if "gc_candidate_branches.py" in ln)
    window = "\n".join(lines[max(0, idx - 3) : idx + 4]).lower()
    assert "fail-open" in window, (
        "the reaper teardown step must be explicitly fail-open (a reap failure "
        "never aborts teardown)"
    )


def test_summary_cite_sites_generalized(skill_md_text: str) -> None:
    """The two summary cite sites are generalized away from the `/single`-only
    'removes candidate/{name}/single' prose to 'any id'."""
    lines = skill_md_text.splitlines()
    # Summary/prose cite sites: lines that describe teardown removing candidate
    # branches but are NOT the backfill sweep_candidates.py invariant.
    summary_lines = [
        ln
        for ln in lines
        if "candidate/*" in ln
        and "teardown" in ln.lower()
        and ("reaps" in ln.lower() or "removes" in ln.lower())
        and "sweep_candidates.py" not in ln
    ]
    assert len(summary_lines) >= 2, (
        "expected at least two summary cite sites describing candidate teardown; "
        f"found {len(summary_lines)}"
    )
    for ln in summary_lines:
        assert "candidate/{name}/single" not in ln, (
            "summary cite site must be generalized off the `/single`-only shape; "
            "got: " + ln
        )
        assert "any id" in ln.lower(), (
            "summary cite site must state teardown reaps the design's "
            "`candidate/*` branches (any id); got: " + ln
        )


def test_backfill_sweep_single_invariant_intact(skill_md_text: str) -> None:
    """The backfill sweep's `sweep_candidates.py`-only `candidate/{slug}/single`
    shape invariant is LEFT INTACT (that tool is out of scope)."""
    assert "the sweep only matches the `candidate/{slug}/single` shape" in skill_md_text, (
        "the backfill-sweep `sweep_candidates.py` `/single`-only invariant must "
        "remain intact"
    )
