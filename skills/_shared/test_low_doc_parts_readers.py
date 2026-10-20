"""test_low_doc_parts_readers.py — every Low-doc reader sees every Low part.

design: basesync-count-line-and-low-headroom (Task 2.1)

`known_issues_low.md` sits at its 50,000-char diet cap with no headroom, so Lows
split across `known_issues_low.md`, `known_issues_low_2.md` … `_9.md`. A Low filed
in part 2 must be seen by every ID reader, the size guard, the base-sync allowlist,
the citation scan and the pending-heading lookup — exactly as one in part 1 is. A
repo with no Low doc, or only part 1, behaves as before.

Shipped, so every case is a `tmp_path` tree or a pure dict: never this repo's real
tree and never `framework-check.sh` (the inv-30 skip lines are pinned in the
dev-only `test_diet_caps_real_tree.py`).

Run with: python3 -m pytest skills/_shared/test_low_doc_parts_readers.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import auto_safe_resolution  # noqa: E402
import certify_issues  # noqa: E402
import certify_ledger  # noqa: E402
import citation_scan  # noqa: E402
import file_size_guard  # noqa: E402
import finalizer_outcome  # noqa: E402
import low_doc_parts as ldp  # noqa: E402
import number_issues as ni  # noqa: E402

DOCS = "three-pillars-docs"
KI = f"{DOCS}/known_issues.md"
P1 = ldp.part_rel(1)
P2 = ldp.part_rel(2)
FC_HEADERS = "\n".join(f"# {i}. Rule {i}" for i in range(1, 6)) + "\n"  # 5 active

PENDING = (certify_issues.PENDING_MARK + "\n\n"
           "### M?: certification guard not-binding — `g/s2.py::t` "
           "[certification sweep-01#s2]\n\n**Fix**: repair it.\n")


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


# ---- number_issues ---------------------------------------------------------------------------

def test_part2_headings_count_toward_the_next_free_l():
    head = {KI: "## Low\n### L-new-a: t\n", P2: "### L300: x\n"}
    assert ni.plan_numbering(head) == {KI: "## Low\n### L301: t\n"}


def test_a_base_only_part2_still_numbers_the_head_placeholder_past_it():
    head = {KI: "### L-new-a: z\n"}
    plan = ni.plan_numbering(head, base={P2: "### L300: cold low in base\n"})
    assert plan == {KI: "### L301: z\n"}


def test_a_part2_placeholder_numbers_past_a_part1_max():
    head = {KI: "### L201: live low\n", P1: "### L300: part 1 max\n\n### L-new-b: x\n"}
    assert ni.plan_numbering(head) == {P1: "### L300: part 1 max\n\n### L301: x\n"}


def test_base_read_paths_include_every_low_part():
    paths = ni.base_read_paths([KI])
    assert P1 in paths and P2 in paths
    assert paths.count(P2) == 1


def test_a_repo_with_only_part1_numbers_as_before():
    head = {KI: "### L183: a\n\n### L-new-b: c\n", P1: "### L300: only part\n"}
    assert ni.plan_numbering(head) == {KI: "### L183: a\n\n### L301: c\n"}


# ---- certify_issues.apply --------------------------------------------------------------------

def test_apply_skips_a_key_filed_only_in_part2(tmp_path):
    root = _tree(tmp_path, {
        KI: "# Known Issues\n\n## Medium\n",
        P2: "# Low, part 2\n\n### L12: demoted — `g` [certification sweep-01#s2]\n"})
    assert certify_issues.apply(PENDING, root / DOCS / "known_issues.md") == []


def test_apply_suffixes_a_placeholder_taken_only_in_part2(tmp_path):
    root = _tree(tmp_path, {
        KI: "# Known Issues\n\n## Medium\n",
        P2: "### M-new-cert-sweep-01-s2: an older filing [certification other#x]\n"})
    ids = certify_issues.apply(PENDING, root / DOCS / "known_issues.md")
    assert ids == ["M-new-cert-sweep-01-s2-2"]


def test_apply_unchanged_when_there_is_no_low_doc(tmp_path):
    root = _tree(tmp_path, {KI: "# Known Issues\n\n## Medium\n"})
    assert certify_issues.apply(PENDING, root / DOCS / "known_issues.md") == [
        "M-new-cert-sweep-01-s2"]


def test_live_issue_docs_list_every_low_part():
    assert P1 in certify_issues.LIVE_ISSUE_DOCS
    assert P2 in certify_issues.LIVE_ISSUE_DOCS
    assert set(ldp.PART_RELS) <= set(certify_issues.LIVE_ISSUE_DOCS)
    assert set(certify_issues.LIVE_ISSUE_DOCS) <= set(certify_issues.ISSUE_ID_DOCS)


# ---- certify_ledger.open_pending_heading -----------------------------------------------------

def test_open_pending_heading_found_only_in_part2(tmp_path):
    root = _tree(tmp_path, {
        KI: "# Known Issues\n\n## Medium\n",
        P2: "### L12: sweep ledger pending for my-slug\n"})
    assert certify_ledger.open_pending_heading(root, "my-slug") == \
        "L12: sweep ledger pending for my-slug"


# ---- auto_safe_resolution --------------------------------------------------------------------

def test_auto_safe_admits_every_low_part_and_stays_total():
    for rel in (P1, P2, ldp.part_rel(9)):
        assert auto_safe_resolution.is_auto_safe_path(rel) is True, rel
    for rel in ("three-pillars-docs/known_issues_low_10.md",
                "three-pillars-docs/known_issues_low_2.txt",
                "three-pillars-docs/known_issues_low_1.md"):
        assert auto_safe_resolution.is_auto_safe_path(rel) is False, rel
    for bad in (None, 123, Path(P2)):
        assert auto_safe_resolution.is_auto_safe_path(bad) is False, bad


def test_auto_safe_paths_set_stays_exact():
    # The exact-membership set is NOT widened — the parts join through the predicate,
    # so `base_sync_cert._cond3_allowlist` and the driver's list keep their pin.
    assert P2 not in auto_safe_resolution.AUTO_SAFE_PATHS


# ---- file_size_guard -------------------------------------------------------------------------

def test_size_guard_exempts_every_low_part():
    for rel in ldp.PART_RELS:
        assert file_size_guard.is_exempt(rel), rel
    for rel in ("three-pillars-docs/known_issues_low_10.md",
                "three-pillars-docs/known_issues_low_2.txt",
                "three-pillars-docs/known_issues_low_1.md"):
        assert not file_size_guard.is_exempt(rel), rel


def test_exempt_files_still_names_only_part1():
    # `test_readers_skip_archives.py` derives its cold names from this set, so a later
    # part is exempt through the predicate — never by a new entry added here.
    assert P1 in file_size_guard.EXEMPT_FILES
    assert P2 not in file_size_guard.EXEMPT_FILES


def test_evaluate_is_silent_for_an_oversized_part2():
    assert file_size_guard.evaluate(P2, 1000, 60_000, grandfathered=False) is None


# ---- finalizer_outcome -----------------------------------------------------------------------

def test_a_part2_citation_counts_as_grounded():
    assert finalizer_outcome.cites_grounding("ruling grounded in known_issues_low_2.md L301")


def test_part2_stays_out_of_the_default_grounding_read_list():
    assert P2 not in finalizer_outcome.GROUNDING_DOCS


# ---- the citation scan (LIVE_GLOBS comes from the shared tuple) -------------------------------

def test_a_part2_cite_is_scanned_live(tmp_path):
    title = "### L12: guard skips invariant #99 on a fresh clone\n"
    repo = _tree(tmp_path, {"framework-check.sh": FC_HEADERS,
                            KI: "# Known Issues\n\n" + title,
                            P2: "# Low, part 2\n\n" + title})
    by_path = {c.path: c.cited_n for c in citation_scan.scan_number_cites(repo)}
    assert by_path.get(KI) == 99
    assert by_path.get(P2) == 99
