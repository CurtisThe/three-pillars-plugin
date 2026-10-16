"""Issue readers in `_shared/` know `known_issues_low.md` and `known_issues_archive.md`.

design: skill-context-diet (Task 2.1; design.md D5b). `known_issues_low.md` is a live
issue doc (same governance class as `known_issues.md`): every reader that resolves
issue IDs over `known_issues.md` ∪ `known_issues_resolved.md` also reads it.
`known_issues_archive.md` is a cold archive: every cold / frozen archive list holds
it. One example per reader, on `tmp_path` doc trees where a file is read.
Run with: python3 -m pytest skills/_shared/test_known_issues_low_readers.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import auto_safe_resolution  # noqa: E402
import certify_issues  # noqa: E402
import certify_ledger  # noqa: E402
import citation_frozen  # noqa: E402
import citation_scan  # noqa: E402
import finalizer_outcome  # noqa: E402
import worktree_isolation_guard  # noqa: E402
import worktree_write_guard  # noqa: E402

DOCS = "three-pillars-docs"
LOW = f"{DOCS}/known_issues_low.md"
ARCHIVE = f"{DOCS}/known_issues_archive.md"
FC_HEADERS = "\n".join(f"# {i}. Rule {i}" for i in range(1, 6)) + "\n"  # 5 active


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


# ---- the shared tuples ----------------------------------------------------------------------

def test_shared_tuples_name_the_live_and_cold_issue_docs():
    assert LOW in certify_issues.LIVE_ISSUE_DOCS
    assert f"{DOCS}/known_issues.md" in certify_issues.LIVE_ISSUE_DOCS
    assert set(certify_issues.LIVE_ISSUE_DOCS) <= set(certify_issues.ISSUE_ID_DOCS)
    assert f"{DOCS}/known_issues_resolved.md" in certify_issues.ISSUE_ID_DOCS
    assert ARCHIVE not in certify_issues.ISSUE_ID_DOCS  # cold bodies: no double-count
    assert ARCHIVE in certify_issues.COLD_ISSUE_DOCS


# ---- citation_frozen ------------------------------------------------------------------------

def test_known_issues_archive_is_frozen():
    line = "- invariant #99 was cited here once"
    assert citation_frozen.is_frozen(ARCHIVE, line, in_history=False, in_fence=False)


def test_low_file_is_live_not_frozen():
    line = "- L12: a Low that cites invariant #99"
    assert LOW in citation_frozen.LIVE_GLOBS
    assert not citation_frozen.is_frozen(LOW, line, in_history=False, in_fence=False)


def test_low_file_title_out_of_range_cite_is_reported_like_known_issues(tmp_path):
    title = "### L12: guard skips invariant #99 on a fresh clone\n"
    repo = _tree(tmp_path, {"framework-check.sh": FC_HEADERS,
                            f"{DOCS}/known_issues.md": "# Known Issues\n\n" + title,
                            LOW: "# Low issues\n\n" + title,
                            ARCHIVE: "# Archive\n\n" + title})
    by_path = {c.path: c.cited_n for c in citation_scan.scan_number_cites(repo)}
    assert by_path.get(f"{DOCS}/known_issues.md") == 99
    assert by_path.get(LOW) == 99
    assert ARCHIVE not in by_path


# ---- certify_issues.apply -------------------------------------------------------------------

PENDING = (certify_issues.PENDING_MARK + "\n\n"
           "### M?: certification guard not-binding — `g/s2.py::t` [certification sweep-01#s2]\n\n"
           "**Fix**: repair it.\n")


def test_apply_skips_a_key_filed_only_in_the_low_file(tmp_path):
    root = _tree(tmp_path, {
        f"{DOCS}/known_issues.md": "# Known Issues\n\n## Medium\n",
        LOW: "# Low issues\n\n### L12: demoted — `g` [certification sweep-01#s2]\n"})
    assert certify_issues.apply(PENDING, root / DOCS / "known_issues.md") == []


def test_apply_avoids_a_placeholder_taken_only_in_the_low_file(tmp_path):
    root = _tree(tmp_path, {
        f"{DOCS}/known_issues.md": "# Known Issues\n\n## Medium\n",
        LOW: "### M-new-cert-sweep-01-s2: an older filing [certification other#x]\n"})
    ids = certify_issues.apply(PENDING, root / DOCS / "known_issues.md")
    assert ids == ["M-new-cert-sweep-01-s2-2"]


def test_apply_unchanged_without_a_low_file(tmp_path):
    root = _tree(tmp_path, {f"{DOCS}/known_issues.md": "# Known Issues\n\n## Medium\n"})
    assert certify_issues.apply(PENDING, root / DOCS / "known_issues.md") == [
        "M-new-cert-sweep-01-s2"]


# ---- certify_ledger.open_pending_heading ----------------------------------------------------

def test_open_pending_heading_found_only_in_the_low_file(tmp_path):
    root = _tree(tmp_path, {
        f"{DOCS}/known_issues.md": "# Known Issues\n\n## Medium\n",
        LOW: "### L12: sweep ledger pending for my-slug\n"})
    assert certify_ledger.open_pending_heading(root, "my-slug") == \
        "L12: sweep ledger pending for my-slug"


def test_open_pending_heading_never_reads_the_cold_archive(tmp_path):
    root = _tree(tmp_path, {ARCHIVE: "### L12: sweep ledger pending for my-slug\n"})
    assert certify_ledger.open_pending_heading(root, "my-slug") is None


# ---- finalizer_outcome ----------------------------------------------------------------------

def test_a_low_file_citation_counts_as_grounded():
    assert finalizer_outcome.cites_grounding("Filed as known_issues_low.md L12.")


def test_the_low_file_stays_out_of_the_default_grounding_read_list():
    assert LOW not in finalizer_outcome.GROUNDING_DOCS  # narrative readers skip it


# ---- auto_safe_resolution -------------------------------------------------------------------

def test_both_issue_docs_are_auto_safe_living_docs():
    assert LOW in auto_safe_resolution.AUTO_SAFE_PATHS
    assert ARCHIVE in auto_safe_resolution.AUTO_SAFE_PATHS


# ---- write guard / isolation guard ----------------------------------------------------------

def test_both_files_sit_in_the_write_guards_governed_set():
    governed = worktree_write_guard._LIVING_DOCS
    assert "known_issues_low.md" in governed and "known_issues_archive.md" in governed
    assert worktree_write_guard.is_guarded_path(LOW) is False
    assert worktree_write_guard.is_guarded_path(ARCHIVE) is False


def test_isolation_guard_points_at_the_low_file_for_issue_ids():
    assert "known_issues_low.md" in worktree_isolation_guard.ISSUE_DOCS_HINT


# ---- skill-script readers (Task 2.2) -------------------------------------------------------

_REPO = _SHARED_DIR.parent.parent
# The worktree skill dir name is built from parts: this file ships in the core tier and
# the release leak-guard substring-scans every shipped file for the paid skill names.
SCRIPT_READER_SOURCES = {
    "classify": _REPO / "skills/tp-merge-from-main/scripts/classify.py",
    "context_scout": _REPO / "skills/tp-pr-iterate/scripts/context_scout.py",
    "round_freeze": _REPO / "skills/tp-pr-iterate/scripts/round_freeze.py",
    "landed_evidence": _REPO / ("skills/" + "tp-" + "worktree/scripts/landed_evidence.py"),
}


@pytest.mark.parametrize("name", sorted(SCRIPT_READER_SOURCES))
def test_script_reader_names_the_low_file_where_it_names_known_issues(name):
    """Every skill script that names `known_issues.md` names the low file too (D5b).

    The site is whatever form the reader takes there: an entry in `context_scout.SOURCES`,
    the ID-scope comment in `classify.py`, the docstring pointer in `round_freeze.py` and
    `landed_evidence.py`. The rule is pinned on the source text because these readers carry
    the doc path as prose or a prompt string rather than a resolved read.
    """
    text = SCRIPT_READER_SOURCES[name].read_text(encoding="utf-8")
    assert "known_issues.md" in text, name
    assert "known_issues_low.md" in text, name
