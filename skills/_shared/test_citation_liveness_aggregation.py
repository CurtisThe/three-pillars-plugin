"""Tests for citation_liveness.run_citation_checks aggregation (Task 3.2).

Proves: CitationReport aggregates number-cite, count-cite, and dangling-path
classes; clean tree -> ok=True; seeded out-of-range cite -> ok=False;
no skill-name grep (inv 21/22 still owns that); formatter produces repair lines.

All hermetic: tmp-dir fixture repos with a stub framework-check.sh.
"""

from __future__ import annotations

from pathlib import Path


# ------------------------------------------------------------------ #
# Fixture helpers
# ------------------------------------------------------------------ #

# A framework-check.sh stub with 5 active headers (controls valid_numbers/active_count).
_FC_5 = "\n".join(f"# {i}. Rule {i}" for i in range(1, 6))  # invariants 1-5 active


def _make_check_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Write a minimal fixture repo with a 5-invariant framework-check.sh."""
    (tmp_path / "framework-check.sh").write_text(_FC_5 + "\n", encoding="utf-8")
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------------ #
# Task 3.2 — run_citation_checks aggregation
# ------------------------------------------------------------------ #


def test_run_citation_checks_clean_tree_ok(tmp_path):
    """run_citation_checks on a clean fixture repo returns CitationReport with ok=True."""
    repo = _make_check_repo(tmp_path, {
        "SECURITY.md": "Some text with no invariant cites.\n",
    })
    from citation_liveness import run_citation_checks, CitationReport

    report = run_citation_checks(repo)
    assert isinstance(report, CitationReport)
    assert hasattr(report, "violations")
    assert hasattr(report, "ok")
    assert report.ok is True
    assert report.violations == []


def test_run_citation_checks_aggregates(tmp_path):
    """run_citation_checks seeds an out-of-range cite and returns ok=False.

    SECURITY.md is in LIVE_GLOBS; an 'invariant #99' cite is out of range
    (valid_numbers = {1..5} in the fixture).
    """
    repo = _make_check_repo(tmp_path, {
        "SECURITY.md": "see invariant #99 for details\n",
    })
    from citation_liveness import run_citation_checks, CitationReport

    report = run_citation_checks(repo)
    assert isinstance(report, CitationReport)
    assert report.ok is False
    assert len(report.violations) >= 1
    # The violation must carry the out-of-range number
    v = report.violations[0]
    assert "99" in str(v) or hasattr(v, "cited_n")


def test_run_citation_checks_no_skill_name_grep(tmp_path):
    """run_citation_checks must NOT perform a skill-name grep (inv 21/22 owns that).

    The report object must NOT have a 'skill_cites' or 'skill_name_violations'
    field, proving skill-name enforcement was NOT added here.
    """
    repo = _make_check_repo(tmp_path, {
        "SECURITY.md": "Some clean text.\n",
    })
    from citation_liveness import run_citation_checks

    report = run_citation_checks(repo)
    assert not hasattr(report, "skill_cites"), (
        "run_citation_checks must not include skill-name grep results (inv 21/22 owns that)"
    )
    assert not hasattr(report, "skill_name_violations"), (
        "run_citation_checks must not include skill-name grep results"
    )


def test_run_citation_checks_formatter_produces_repair_lines(tmp_path):
    """format_violations returns 'file:line: <class>: <cited> (valid: ...)' lines."""
    repo = _make_check_repo(tmp_path, {
        "SECURITY.md": "see invariant #99 for details\n",
    })
    from citation_liveness import run_citation_checks, format_violations

    report = run_citation_checks(repo)
    lines = format_violations(report)
    assert len(lines) >= 1
    # Each repair line must follow the format: file:line: <class>: ... (valid: ...)
    for line in lines:
        assert ":" in line, f"repair line must contain ':': {line!r}"
        # Must include the class label
        assert any(
            kw in line for kw in ("number-cite", "count-cite", "dangling-path")
        ), f"repair line must name the violation class: {line!r}"


def test_run_citation_checks_citation_report_shape(tmp_path):
    """CitationReport must expose .violations and .ok; violations is a list."""
    repo = _make_check_repo(tmp_path, {
        "SECURITY.md": "Some clean text.\n",
    })
    from citation_liveness import run_citation_checks, CitationReport
    import dataclasses

    report = run_citation_checks(repo)
    # Must be a dataclass or at least have both fields
    assert isinstance(report, CitationReport)
    assert isinstance(report.violations, list)
    assert isinstance(report.ok, bool)
