"""test_readers_skip_archives.py — readers skip the cold files by default.

design: skill-context-diet, Task 2.3 (D4, Behavior 5).

Two checks:

1. `read-project-docs.md` says to read the four living docs only, and never
   `*_archive.md`, `known_issues_resolved.md` or `known_issues_low.md` by
   default.
2. A scan of `skills/**/SKILL.md` and `skills/_shared/*.md` finds every file
   that names a cold file. The scan over-approximates "an instruction to read
   one": a mention is a site until it sits in `ALLOWLIST` with a category and a
   reason. A new site that is not allowlisted fails, so a new default read
   cannot slip in unseen.

The cold set and the living-doc set come from `file_size_guard` (its own
registry), not from a hand-copied list. The allowlist is keyed by file path
only, never by a prose anchor, so a later condense of a listed skill does not
break this test.

Allowlist categories:
- `lookup`: a conditional lookup on a miss, never a default read.
- `writer`: the skill or protocol writes, moves or stages the cold file.
- `lows`: `/tp-design-learn` filing, de-duplicating or promoting a Low.
- `diet`: `/tp-docs-update --diet` condensing a doc into its cold files.
- `id-resolution`: an ID-resolution or guard reader.
- `rule`: states the reader rule or the living-doc format itself.
- `mention`: names the file (a cap exemption, an incident citation) without
  telling a reader to open it.
- `pending`: a default read that is not obviously legitimate. A behaviour
  question, filed in the design's `issues-found.md` by the seat.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import file_size_guard

ROOT = Path(__file__).resolve().parents[2]
READ_DOCS = ROOT / "skills" / "_shared" / "read-project-docs.md"

ARCHIVE_PATTERN = Path(file_size_guard.ARCHIVE_GLOB).name  # '*_archive.md'
_EXEMPT_NAMES = {Path(p).name for p in file_size_guard.EXEMPT_FILES}
COLD_NAMES = sorted(  # the exempt files the archive glob does not already cover
    n for n in _EXEMPT_NAMES if not fnmatch.fnmatchcase(n, ARCHIVE_PATTERN))
LIVE_DOCS = sorted(file_size_guard.DOC_CHAR_CAPS)
COLD_RE = re.compile(
    "|".join([r"\w*" + re.escape(ARCHIVE_PATTERN.lstrip("*")),
              *(re.escape(n) for n in COLD_NAMES)]))

CATEGORIES = {"lookup", "writer", "lows", "diet", "id-resolution", "rule",
              "mention", "pending"}

# path -> (category, reason). Keyed by path; see the module docstring.
ALLOWLIST: dict[str, tuple[str, str]] = {
    "skills/tp-plan/SKILL.md": (
        "lookup", "a dependency's Design Inventory row not found in the live "
        "roadmap is looked up in product_roadmap_archive.md (fallback on a miss)"),
    "skills/tp-design-learn/SKILL.md": (
        "lows", "step 11 moves a resolved issue to known_issues_resolved.md, "
        "moves a promoted Low out of known_issues_low.md, and stages the "
        "rollover archives"),
    "skills/tp-spike-learn/SKILL.md": (
        "writer", "step 11 moves a resolved issue to known_issues_resolved.md "
        "and stages the rollover archives"),
    "skills/tp-docs-update/SKILL.md": (
        "diet", "writer: rolls History into the doc's archive and stages it; "
        "the --diet condense writes the cold files"),
    "skills/tp-docs-init/SKILL.md": (
        "writer", "scaffolds the cold archive siblings and known_issues_low.md "
        "next to the living docs"),
    "skills/tp-setup/SKILL.md": (
        "writer", "scaffolds vision.md with its pointer to vision_archive.md; "
        "the draft keeps the pointer, nothing reads the archive"),
    "skills/tp-design-complete/SKILL.md": (
        "pending", "the completion check reads product_roadmap_archive.md next "
        "to product_roadmap.md by default to find the Design Inventory row, "
        "and the archival check stages it; the read may belong behind a miss "
        "on the live roadmap"),
    "skills/_shared/read-project-docs.md": (
        "rule", "the reader rule itself: names the cold files to say they are "
        "not read by default"),
    "skills/_shared/living-doc-format.md": (
        "rule", "the living-doc format: history goes to the cold files, readers "
        "skip them, a promoted Low moves back"),
    "skills/_shared/file-size-caps.md": (
        "mention", "lists the cold files as exempt from the caps"),
    "skills/_shared/issue-id-placeholders.md": (
        "id-resolution", "a placeholder counts as a heading in the issue files "
        "(ID resolution reads known_issues_resolved.md)"),
    "skills/_shared/reconcile-protocol.md": (
        "mention", "names known_issues_resolved.md as an append-only archive "
        "whose content is never reworded"),
    "skills/_shared/certification-protocol.md": (
        "writer", "certify closes the pending sweep entry by moving it to "
        "known_issues_resolved.md and stages that file"),
    "skills/_shared/topology.md": (
        "mention", "an incident citation (issue M17 in known_issues_resolved.md), "
        "not an instruction to read it"),
    "skills/_shared/first-run.md": (
        "mention", "an incident citation (issue M17 in known_issues_resolved.md), "
        "not an instruction to read it"),
}


def scan(root: Path) -> dict[str, list[str]]:
    """`{relpath: [cold file names mentioned]}` for every in-scope skill file
    under `root` that names a cold file."""
    paths = {*root.glob("skills/**/SKILL.md"), *root.glob("skills/_shared/*.md")}
    sites: dict[str, list[str]] = {}
    for path in sorted(paths):
        found = sorted(set(COLD_RE.findall(path.read_text(encoding="utf-8"))))
        if found:
            sites[path.relative_to(root).as_posix()] = found
    return sites


# --- 1. the reader rule --------------------------------------------------------


def test_read_project_docs_names_the_four_live_docs():
    text = READ_DOCS.read_text(encoding="utf-8")
    assert len(LIVE_DOCS) == 4, LIVE_DOCS
    for doc in LIVE_DOCS:
        assert doc in text, f"read-project-docs.md must name the live doc {doc}"


def test_read_project_docs_says_never_read_cold_files_by_default():
    """One line names all three cold classes with the rule: never, by default."""
    wanted = [ARCHIVE_PATTERN, *COLD_NAMES]
    lines = READ_DOCS.read_text(encoding="utf-8").splitlines()
    rule = [l for l in lines if all(w in l for w in wanted)]
    assert rule, (
        f"read-project-docs.md: no single line names {wanted} (the cold files)")
    assert any("never" in l.lower() and "by default" in l.lower() for l in rule), (
        "read-project-docs.md: the line naming the cold files must say to "
        "never read them by default")


# --- 2. the scan ---------------------------------------------------------------


def test_every_cold_file_site_is_allowlisted_with_a_reason():
    sites = scan(ROOT)
    assert sites, "the scan found no site: the scanner is broken"
    missing = {p: toks for p, toks in sites.items() if p not in ALLOWLIST}
    assert not missing, (
        "skill files that name a cold file are not in ALLOWLIST (add each with "
        f"a category and a reason, or remove the default read): {missing}")


def test_allowlist_entries_have_a_category_a_reason_and_a_file():
    for path, (category, reason) in ALLOWLIST.items():
        assert category in CATEGORIES, f"{path}: unknown category {category!r}"
        assert reason.strip(), f"{path}: the allowlist reason is empty"
        assert (ROOT / path).is_file(), f"{path}: allowlisted file does not exist"


def test_scan_finds_a_planted_site_and_skips_clean_files(tmp_path):
    planted = tmp_path / "skills" / "tp-x" / "SKILL.md"
    nested = tmp_path / "skills" / "tp-y" / "refs" / "SKILL.md"
    shared = tmp_path / "skills" / "_shared" / "y.md"
    clean = tmp_path / "skills" / "_shared" / "clean.md"
    other = tmp_path / "skills" / "_shared" / "notes.txt"
    for path, body in (
        (planted, "Read `three-pillars-docs/known_issues_low.md` first.\n"),
        (nested, "Also check foo_archive.md and known_issues_resolved.md.\n"),
        (shared, "See `*_archive.md`.\n"),
        (clean, "Read the four living docs only.\n"),
        (other, "known_issues_low.md\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    assert scan(tmp_path) == {
        "skills/tp-x/SKILL.md": ["known_issues_low.md"],
        "skills/tp-y/refs/SKILL.md": ["foo_archive.md", "known_issues_resolved.md"],
        "skills/_shared/y.md": ["_archive.md"],
    }
