"""Count-cite allowlist tests for citation_scan + the live-tree integration.

Proves: count-cites are evaluated ONLY at allowlisted sites; non-allowlisted
`N invariants` prose is never flagged; the allowlist names exactly the
SECURITY.md count line + the framework-check banner; a missing entry fails OPEN;
zero false positives on the current tree.

design: invariant-citation-coherence
"""

from __future__ import annotations

import re
from pathlib import Path

from citation_scan import (
    COUNT_ALLOWLIST,
    scan_count_cites,
    scan_number_cites,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# A framework-check.sh stub with N active headers (N controls active_count()).
_FC_HEADERS = "\n".join(f"# {i}. Rule {i}" for i in range(1, 6))  # 5 active


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Write a fake repo tree; always includes a 5-invariant framework-check.sh."""
    (tmp_path / "framework-check.sh").write_text(_FC_HEADERS + "\n", encoding="utf-8")
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------------ #
# Allowlist composition.
# ------------------------------------------------------------------ #


def test_allowlist_has_exactly_security_and_banner():
    paths = [rel for rel, _ in COUNT_ALLOWLIST]
    assert paths == ["SECURITY.md", "framework-check.sh"]


# ------------------------------------------------------------------ #
# Allowlisted SECURITY.md line IS evaluated.
# ------------------------------------------------------------------ #


def test_security_count_line_flagged_when_stale(tmp_path):
    repo = _make_repo(
        tmp_path,
        {"SECURITY.md": "framework invariant checker (`framework-check.sh`, 26 invariants)\n"},
    )
    cites = scan_count_cites(repo)
    assert len(cites) == 1
    c = cites[0]
    assert c.path == "SECURITY.md"
    assert c.cited_n == 26
    assert c.expected == 5  # active_count of the 5-header stub


def test_security_count_line_not_flagged_when_correct(tmp_path):
    repo = _make_repo(
        tmp_path,
        {"SECURITY.md": "framework invariant checker (`framework-check.sh`, 5 invariants)\n"},
    )
    assert scan_count_cites(repo) == []


# ------------------------------------------------------------------ #
# Non-allowlisted `N invariants` prose is NEVER flagged.
# ------------------------------------------------------------------ #


def test_non_allowlisted_count_prose_not_flagged(tmp_path):
    repo = _make_repo(
        tmp_path,
        {
            # architecture.md historical narration — NOT on the allowlist.
            "three-pillars-docs/architecture.md":
                "the banner now reads 'all 33 invariants passed' after the sync.\n"
                "As of 2026-06-11 it enumerates 35 invariants.\n",
            # a test-fixture style banner literal — NOT on the allowlist.
            "skills/_shared/test_thing.py":
                'assert out == "framework-check: all 37 invariants passed"\n',
            # a subset count — NOT on the allowlist.
            "README.md": "the 6 W6 invariants shipped together.\n",
        },
    )
    assert scan_count_cites(repo) == []


def test_security_unrelated_invariant_line_not_flagged(tmp_path):
    # A `N invariants` line in SECURITY.md that does NOT match the matcher
    # (no "framework invariant checker" anchor) is not checked.
    repo = _make_repo(
        tmp_path,
        {"SECURITY.md": "We narrate that 33 invariants existed historically.\n"},
    )
    assert scan_count_cites(repo) == []


# ------------------------------------------------------------------ #
# Banner allowlist entry — derived `${_INV_N}` has no literal int → not flagged.
# ------------------------------------------------------------------ #


def test_banner_derived_no_literal_not_flagged(tmp_path):
    repo = _make_repo(
        tmp_path,
        {"framework-check.sh":
            _FC_HEADERS + "\n"
            'echo "framework-check: all ${_INV_N} invariants passed"\n'},
    )
    assert scan_count_cites(repo) == []


def test_banner_stale_literal_flagged(tmp_path):
    repo = _make_repo(
        tmp_path,
        {"framework-check.sh":
            _FC_HEADERS + "\n"
            'echo "framework-check: all 37 invariants passed"\n'},
    )
    cites = scan_count_cites(repo)
    assert len(cites) == 1
    assert cites[0].cited_n == 37
    assert cites[0].expected == 5


# ------------------------------------------------------------------ #
# Missing allowlist entry fails OPEN.
# ------------------------------------------------------------------ #


def test_missing_site_fails_open(tmp_path):
    # No SECURITY.md at all — the entry is under-checked, not flagged.
    repo = _make_repo(tmp_path, {})
    assert scan_count_cites(repo) == []


def test_custom_allowlist_only_checks_named_sites(tmp_path):
    repo = _make_repo(
        tmp_path,
        {
            "SECURITY.md": "framework invariant checker (`framework-check.sh`, 26 invariants)\n",
            "OTHER.md": "this file says 26 invariants too\n",
        },
    )
    # An allowlist that names only OTHER.md ignores SECURITY.md entirely.
    custom = [("OTHER.md", re.compile(r"\b\d+\s+invariants?\b"))]
    cites = scan_count_cites(repo, allowlist=custom)
    assert [c.path for c in cites] == ["OTHER.md"]


# ------------------------------------------------------------------ #
# Zero false positives on the CURRENT tree (number + count).
# ------------------------------------------------------------------ #


def test_live_tree_number_cites_zero_false_positives():
    # The number-cite scan over the live tree must not flag any in-range cite.
    # (Pre-sweep there may be genuine out-of-range rot; but every flagged cite
    # MUST be a real out-of-range/retired integer, never an in-range one.)
    import invariant_map
    m = invariant_map.parse_invariant_map(REPO_ROOT / "framework-check.sh")
    valid = invariant_map.valid_numbers(m)
    cites = scan_number_cites(REPO_ROOT)
    for c in cites:
        assert c.cited_n not in valid, (
            f"in-range cite #{c.cited_n} wrongly flagged at {c.path}:{c.line}: {c.context}"
        )


def test_test_modules_are_excluded_from_number_scan(tmp_path):
    # A test_*.py module that plants a synthetic out-of-range cite is NOT
    # flagged — test fixtures are not live prose.
    repo = _make_repo(
        tmp_path,
        {
            "skills/_shared/test_planted.py": 'x = "invariant #99 planted fixture"\n',
            "skills/_shared/real_module.py": '# real prose cites invariant #99\n',
        },
    )
    cites = scan_number_cites(repo)
    paths = {c.path for c in cites}
    assert "skills/_shared/test_planted.py" not in paths
    # The real (non-test) module IS scanned and flagged.
    assert "skills/_shared/real_module.py" in paths


def test_fixtures_segment_excluded_from_number_scan(tmp_path):
    repo = _make_repo(
        tmp_path,
        {"skills/_shared/fixtures/corpus.md": "invariant #99 example\n"},
    )
    assert scan_number_cites(repo) == []


def test_live_tree_count_cites_zero_false_positives():
    # On the current tree the count check may surface the known stale
    # SECURITY.md line (sweep target) — but it must NEVER flag a site whose
    # cited count already equals active_count.
    import invariant_map
    m = invariant_map.parse_invariant_map(REPO_ROOT / "framework-check.sh")
    expected = invariant_map.active_count(m)
    for c in scan_count_cites(REPO_ROOT):
        assert c.cited_n != expected
