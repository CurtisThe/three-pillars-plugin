"""Tests for pending_flip.flip: the pre-merge `Completion PR pending` flipper.

Oracles: example (the exact line shapes the plan header names) and metamorphic
(a re-run on the flipper's own output is a no-op), per
skills/_shared/test-fragility.md. Assertions read structured Edit/skipped
fields, not rendered prose. Hermetic: tmp-dir fixture repos, no git, no network.

design: design-complete-final-doc-state
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

import final_doc_state
import living_doc_archive
import pending_flip

DOCS = "three-pillars-docs"
RM = f"{DOCS}/product_roadmap.md"
KI = f"{DOCS}/known_issues.md"
LIVING = [*living_doc_archive.ARCHIVES, *living_doc_archive.ARCHIVES.values()]
SLUGS = ("s1", "s2")


def repo(root: Path, files: dict, slugs=SLUGS) -> Path:
    for s in slugs:
        (root / DOCS / "completed-tp-designs" / s).mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def read(root: Path, rel: str = RM) -> str:
    return (root / rel).read_text(encoding="utf-8")


def one(root, line, slug="s1", pr=None, rel=RM, slugs=SLUGS):
    """Fixture doc holding only `line` (file line 3); flip it; return the result."""
    repo(root, {rel: f"# Doc\n\n{line}\n"}, slugs)
    edits, skipped = pending_flip.flip(root, slug, pr, apply=True)
    return read(root, rel).splitlines()[2], edits, skipped


PENDING, NUMBERLESS = "Completion PR pending", "Done (completion PR)"
A = "- Fragile tests … (`s1`, 2026-10-02; Completion PR pending)."
ROW = "| s1 | x | design | Completion PR pending — [design](…) | Docs |"
FTP = (
    "3. **`s1`** (**implemented**, Completion PR pending; Parts A–F). Its Part G "
    "proof-root work was **split back out to `s2`** (operator, 2026-09-30); FTP "
    "skips Phase 11."
)
PROSE = "- Prose (`s2`, merged) and more (`s1`, 2026-10-02; Completion PR pending)."
SLUGS3 = ("cheap-tier-offload", "cheap-tier-review-prep", "task-worker-sonnet")
FOLLOW = (
    "**Follow-on:** `cheap-tier-offload` (awaiting PR) built the Sonnet task path "
    "as its opt-in task lever; its A/B runs, `cheap-tier-review-prep` and the M46 "
    "fix are owed (Active inventory)."
)
ISSUE = (
    "- ~~Tokens exclude cache~~: **resolved 2026-09-29** by `task-worker-sonnet` "
    "(awaiting PR); the bullet moved to [known_issues_resolved.md]"
    "(known_issues_resolved.md) §L139."
)


@pytest.mark.parametrize("pr, done", [(None, NUMBERLESS), (214, "Done — PR #214")])
def test_attributed_token_flips_to_done_form(tmp_path, pr, done):
    new, edits, skipped = one(tmp_path, A, pr=pr)
    assert new == A.replace(PENDING, done)
    assert skipped == []
    (e,) = edits
    assert (e.kind, e.slug, e.path, e.line) == ("status-flip", "s1", RM, 3)
    assert (e.before, e.after) == (A, new)


def test_numbered_item_lead_owns_the_token_and_other_slug_is_untouched(tmp_path):
    new, edits, _ = one(tmp_path / "a", FTP)
    assert new == FTP.replace(PENDING, NUMBERLESS) and len(edits) == 1
    new2, edits2, skipped2 = one(tmp_path / "b", FTP, slug="s2")
    assert (new2, edits2, skipped2) == (FTP, [], [])


def test_design_inventory_row_flips_by_owner_cell(tmp_path):
    new, edits, _ = one(tmp_path / "a", ROW)
    assert new == ROW.replace(PENDING, NUMBERLESS) and len(edits) == 1
    assert one(tmp_path / "b", ROW, slug="s2")[0] == ROW


def test_pr_number_upgrades_the_numberless_done_text(tmp_path):
    row = ROW.replace(PENDING, NUMBERLESS)
    new, edits, _ = one(tmp_path / "a", row, pr=214)
    assert new == row.replace(NUMBERLESS, "Done — PR #214") and len(edits) == 1
    new2, edits2, _ = one(tmp_path / "b", row, pr=None)
    assert (new2, edits2) == (row, [])


@pytest.mark.parametrize("doc", [
    "## Roadmap History\n\n- `s1` merged (Completion PR pending).\n",
    "```\n- `s1` (Completion PR pending).\n```\n",
    "- `s1` says `Completion PR pending` here.\n",
    '- `s1` says "Completion PR pending" here.\n',
    "- `s2` (Completion PR pending).\n",
])
def test_excluded_lines_are_untouched_and_not_reported(tmp_path, doc):
    repo(tmp_path, {RM: doc})
    assert pending_flip.flip(tmp_path, "s1", 7, apply=True) == ([], [])
    assert read(tmp_path) == doc


def test_a_heading_after_history_resumes_flipping(tmp_path):
    repo(tmp_path, {RM: f"## Roadmap History\n\n{A}\n\n## Active\n\n{A}\n"})
    edits, _ = pending_flip.flip(tmp_path, "s1", None, apply=True)
    assert [e.line for e in edits] == [7]


def test_parenthetical_names_one_slug_so_that_slug_owns_the_token(tmp_path):
    new, edits, _ = one(tmp_path / "a", PROSE)
    assert new == PROSE.replace(PENDING, NUMBERLESS) and len(edits) == 1
    assert one(tmp_path / "b", PROSE, slug="s2")[1:] == ([], [])


@pytest.mark.parametrize("line", [
    "- Prose naming `s1` (Completion PR pending).",
    "Prose naming **`s1`** (Completion PR pending).",
])
def test_adjacent_slug_owns_a_slugless_parenthetical(tmp_path, line):
    new, edits, _ = one(tmp_path, line)
    assert new == line.replace(PENDING, NUMBERLESS) and len(edits) == 1


@pytest.mark.parametrize("line, slug, reason", [
    ("- Prose (`s1` with `s2`; Completion PR pending).", "s1", "unattributable"),
    ("- Prose (`s1` with `s2`; Completion PR pending).", "s2", "unattributable"),
    ("Prose naming `s1` and `s2`; Completion PR pending.", "s1", "unattributable"),
    ("- Words name `s1`, then more words (Completion PR pending).", "s1",
     "unattributable"),
    ("- `s1` is Completion PR pending, then Completion PR pending again.", "s1",
     "ambiguous-multi-match"),
])
def test_unresolvable_tokens_are_skipped_loudly(tmp_path, line, slug, reason):
    new, edits, skipped = one(tmp_path, line, slug=slug)
    assert (new, edits) == (line, [])
    assert skipped == [{"file": RM, "line_no": 3, "reason": reason}]


def test_unattributable_line_not_naming_the_slug_is_not_a_skip(tmp_path):
    line = "Prose naming `s1` and `s2`; Completion PR pending."
    _, edits, skipped = one(tmp_path, line, slug="s3", slugs=("s1", "s2", "s3"))
    assert (edits, skipped) == ([], [])


@pytest.mark.parametrize("rel, line, owner", [(RM, FOLLOW, SLUGS3[0]), (KI, ISSUE, SLUGS3[2])])
def test_real_adjacency_shapes_flip_only_for_the_adjacent_slug(tmp_path, rel, line, owner):
    canon = line.replace("awaiting PR", PENDING)
    repo(tmp_path, {rel: f"# Doc\n\n{canon}\n"}, SLUGS3)
    for slug in [s for s in SLUGS3 if s != owner]:
        assert pending_flip.flip(tmp_path, slug, None, apply=True) == ([], [])
        assert read(tmp_path, rel).splitlines()[2] == canon
    edits, skipped = pending_flip.flip(tmp_path, owner, None, apply=True)
    assert skipped == [] and len(edits) == 1
    assert read(tmp_path, rel).splitlines()[2] == canon.replace(PENDING, NUMBERLESS)


# A line lead (s1) and a placement on the token's own parenthetical (s2 inside
# it, or directly before it) disagree: either reading is a documented placement,
# so the token is drift for both slugs, never silently the other slug's.
LEAD_VS_PAREN = [
    "3. **`s1`** (**implemented**, Done — PR #214; Parts A-F). "
    "Its Part G work was split back out to `s2` (Completion PR pending).",
    "- **`s1`** — Done — PR #214. Follow-on `s2` (Completion PR pending).",
    "- **`s1`** — Done — PR #214. Follow-on (`s2`, Completion PR pending).",
    "- **`s1`** — Implemented (Completion PR pending; split from `s2`).",
    "3. **`s1`** — implemented (Completion PR pending; split from `s2`).",
    "3. **`s1`** (**implemented**, Completion PR pending; Part G split out to `s2`).",
    "- **`s1`** — implemented (supersedes `s2`; Completion PR pending).",
    "| `s1` | Light | Done; (Completion PR pending, follow-on of `s2`) | Docs |",
    # Unticked leads name the slug too: the live inventory-row shape (a plain
    # first cell), a bold bullet lead and a plain numbered lead.
    "| s1 | Light | Done; (Completion PR pending, follow-on of `s2`) | Docs |",
    "- **s1** — implemented (Completion PR pending; split from `s2`).",
    "3. s1 — implemented (Completion PR pending; split from `s2`).",
]


@pytest.mark.parametrize("line", LEAD_VS_PAREN)
@pytest.mark.parametrize("slug", SLUGS)
def test_lead_and_token_parenthetical_naming_other_slugs_is_drift_for_both(
    tmp_path, line, slug
):
    new, edits, skipped = one(tmp_path, line, slug=slug)
    assert (new, edits) == (line, [])
    assert skipped == [{"file": RM, "line_no": 3, "reason": "unattributable"}]
    assert [h["owner"] for h in pending_flip.scan(tmp_path, slug)] == [None]
    out = final_doc_state.check(tmp_path, slug)
    assert out["verdict"] == "drift" and f"hand-edit {RM}:3" in out["fix"]


@pytest.mark.parametrize("rel", LIVING)
def test_every_living_doc_and_archive_is_flipped_and_missing_files_are_noops(tmp_path, rel):
    new, edits, skipped = one(tmp_path, A, rel=rel)
    assert new == A.replace(PENDING, NUMBERLESS) and skipped == []
    assert [e.path for e in edits] == [rel]


@pytest.mark.parametrize("pr", [None, 214])
def test_rerun_on_own_output_is_a_noop(tmp_path, pr):
    lines = [A, ROW, PROSE, FTP, "- Prose (`s1` with `s2`; Completion PR pending)."]
    repo(tmp_path, {RM: "# Doc\n\n" + "\n".join(lines) + "\n"})
    first, _ = pending_flip.flip(tmp_path, "s1", pr, apply=True)
    assert len(first) == 4
    after = read(tmp_path)
    again, _ = pending_flip.flip(tmp_path, "s1", pr, apply=True)
    assert again == [] and read(tmp_path) == after


def test_plan_mode_reports_the_same_edits_as_apply_and_writes_nothing(tmp_path):
    doc = f"*Last updated: 2000-01-01*\n\n{A}\n"
    repo(tmp_path, {RM: doc})
    plan, _ = pending_flip.flip(tmp_path, "s1", 7, apply=False)
    assert read(tmp_path) == doc
    applied, _ = pending_flip.flip(tmp_path, "s1", 7, apply=True)
    assert plan == applied and len(plan) == 1
    assert f"*Last updated: {datetime.date.today().isoformat()}*" in read(tmp_path)


VISION, VISION_ARCHIVE = f"{DOCS}/vision.md", f"{DOCS}/vision_archive.md"


@pytest.mark.parametrize("rel", [VISION, VISION_ARCHIVE])
def test_the_vision_pair_is_a_living_file_the_flip_reaches(tmp_path, rel):
    assert rel in living_doc_archive.ARCHIVES.keys() | living_doc_archive.ARCHIVES.values()
    new, edits, skipped = one(tmp_path, A, rel=rel)
    assert new == A.replace(PENDING, NUMBERLESS) and skipped == []
    assert [e.path for e in edits] == [rel]


@pytest.mark.parametrize("vision_files", [(), (VISION,), (VISION, VISION_ARCHIVE)])
def test_scan_and_flip_tolerate_a_tree_with_or_without_the_vision_pair(tmp_path, vision_files):
    files = {RM: f"# Doc\n\n{A}\n", **{rel: "# Vision\n\nNo tokens here.\n" for rel in vision_files}}
    repo(tmp_path, files)
    assert [h["owner"] for h in pending_flip.scan(tmp_path, "s1")] == ["s1"]
    edits, skipped = pending_flip.flip(tmp_path, "s1", None, apply=True)
    assert [e.path for e in edits] == [RM] and skipped == []
    assert read(tmp_path, RM).splitlines()[2] == A.replace(PENDING, NUMBERLESS)
    for rel in vision_files:
        assert read(tmp_path, rel) == "# Vision\n\nNo tokens here.\n"
