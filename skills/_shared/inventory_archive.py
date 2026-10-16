"""inventory_archive.py — move a merged design's Design Inventory row to the archive.

`move_completed(repo_root, slug, apply=False)` is run by `/tp-post-merge`
after the merge is verified — the one lifecycle point where "done" is true.
It moves the slug's Design Inventory table rows, verbatim, out of
`product_roadmap.md` into `product_roadmap_archive.md`, each under the same
`### ` sub-heading it left. Rows are selected by slug alone — every data row
attributable to the slug, in one call — never by Status text: whatever
`/tp-design-learn` wrote and `reconcile_docs` flipped, the row moves, so there
is no status predicate to drift from the writers. A slug promoted from a seed
table keeps its seed row beside its Active row; after the merge neither belongs
in the live inventory, and moving both at once is what makes the re-run a
no-op. The same call keeps `### Recent
completions` at the newest `RC_KEEP` bullets: older bullets roll, verbatim and
newest-first, to the top of the archive's older-entries subsection. The mover
never rewrites row content.

Created archive lines are verifier-declared scaffold (see the `_place_*`
functions); a missing archive file is seeded from `living_doc_archive.ARCHIVE_HEADER`.
Attribution uses `citation_rows.owner_slug_of_row` (the same predicate
`reconcile_docs` uses); `verify_moves.verify_move` (with `scaffold_lines`)
runs in memory before anything is written. A second run is a no-op.

CLI: `--slug S [--apply] [--json] [--repo-root R]` — dry-run by default.
Exit 0 for a clean move or a no-op; 1 on a verifier failure.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import living_doc_archive
import verify_moves
from citation_rows import owner_slug_of_row

LIVE_REL = "three-pillars-docs/product_roadmap.md"
INVENTORY_HEADING = "## Design Inventory"
INVENTORY_ARCHIVE_HEADING = "## Design Inventory — completed and superseded rows"
CF_ARCHIVE_HEADING = "## Current Focus — historical (moved from the live roadmap)"
RC_ARCHIVE_HEADING = "### Recent completions — older entries (the newest four stay in the live roadmap)"
RC_KEEP = 4  # live `### Recent completions` bullets kept; older ones roll
_BULLET_RE = re.compile(r"^\s*[-*]\s+")


@dataclass
class MoveResult:
    """Outcome: `moved` lines (row and/or rolled bullets), `reason` (None on
    a clean move; a no-op names the slug), `rows` — the moved lines in move order."""
    moved: int
    reason: str | None = None
    rows: list[str] | None = None


def _section_span(lines, heading):
    """(start, end) line-index span of section `heading`: start at the
    heading line, end (exclusive) at the next `## ` line or EOF."""
    for i, line in enumerate(lines):
        if line == heading:
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("## "):
                    return i, j
            return i, len(lines)
    return None


def _is_delimiter_line(line):
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|") and len(s) > 2):
        return False
    cells = [c.strip() for c in s.strip("|").split("|")]
    return any(cells) and all(c == "" or re.fullmatch(r":?-{3,}:?", c) for c in cells)


def _table_start(lines, i, section_start):
    """Index of the table header above data row `i` (the line above the
    delimiter row), or None when no header precedes it in this table."""
    for j in range(i - 1, section_start, -1):
        if lines[j].startswith("#"):
            return None
        if (_is_delimiter_line(lines[j]) and j - 1 >= section_start
                and lines[j - 1].strip().startswith("|")):
            return j - 1
    return None


def _find_rows(lines, slug, root):
    """Every (row_idx, table_start) of the slug's rows in the Design Inventory
    section, in document order: each data row attributable to `slug`
    (owner_slug_of_row), whatever its Status cell says. A slug may hold more
    than one row (a seed-table row and the Active row it was promoted to);
    all of them move together, so a re-run finds none."""
    span = _section_span(lines, INVENTORY_HEADING)
    if span is None:
        return []
    found = []
    for i in range(span[0] + 1, span[1]):
        line = lines[i]
        if not line.lstrip().startswith("|") or _is_delimiter_line(line):
            continue
        if owner_slug_of_row(line, root) != slug:
            continue
        table_start = _table_start(lines, i, span[0])
        if table_start is not None:
            found.append((i, table_start))
    return found


def _nearest_heading(lines, idx, prefix):
    for j in range(idx - 1, -1, -1):
        if lines[j].startswith(prefix):
            return lines[j]
    return None


def _rc_overflow(lines):
    """Indices of the `### Recent completions` bullets (inside `## Current
    Focus`) past the newest `RC_KEEP`, in live (newest-first) order."""
    bullets, in_cf, in_rc = [], False, False
    for i, line in enumerate(lines):
        if line.startswith("## "):
            in_cf, in_rc = line[3:].strip().startswith("Current Focus"), False
        elif line.startswith("### "):
            in_rc = in_cf and line[4:].strip().startswith("Recent completions")
        elif in_rc and re.match(r"[-*]\s", line):  # column-0 bullets only
            bullets.append(i)
    return bullets[RC_KEEP:]


def _ensure_heading(text, heading):
    """`text` holding `heading` on its own line: as-is, else appended at EOF."""
    if any(line == heading for line in text.splitlines()):
        return text
    if text.strip() == "":
        return heading + "\n"
    base = text if text.endswith("\n") else text + "\n"
    if not base.endswith("\n\n"):
        base += "\n"
    return base + heading + "\n"


def _insert_block(lines, end, block):
    """Insert `block` at index `end`, blank-separated from the non-blank
    lines on either side (idempotent when one already sits there)."""
    head = lines[:end]
    while head and head[-1].strip() == "":
        head.pop()
    tail = lines[end:]
    while tail and tail[0].strip() == "":
        tail.pop(0)
    return head + ([""] if head else []) + block + ([""] + tail if tail else [])


def _place_row(after, subheading, header_line, delim_line, row_line):
    """The archive text with `row_line` under the `### ` sub-heading: after
    the matching block's last table row when the block exists; the block
    (sub-heading, repeated header, delimiter, row) appended at the end of
    the `## ` section when it does not; the section created at EOF if missing."""
    after = _ensure_heading(after, INVENTORY_ARCHIVE_HEADING)
    lines = after.splitlines()
    sec_start, sec_end = _section_span(lines, INVENTORY_ARCHIVE_HEADING)
    block_end = lambda start: next(
        (j for j in range(start + 1, sec_end)
         if lines[j].startswith("## ") or lines[j].startswith("### ")), sec_end)
    for i in range(sec_start + 1, sec_end):
        if lines[i] == subheading:
            insert_at = block_end(i)
            while insert_at - 1 > i and lines[insert_at - 1].strip() == "":
                insert_at -= 1
            return "\n".join(lines[:insert_at] + [row_line] + lines[insert_at:]) + "\n"
    block = [subheading, "", header_line, delim_line, row_line]
    return "\n".join(_insert_block(lines, sec_end, block)) + "\n"


def _place_bullet(after, bullet_line):
    """The archive text with `bullet_line` in the Current Focus section:
    before the `### Recent completions — older entries …` subsection's
    first bullet (headings created when missing; bullets stay newest-first)."""
    after = _ensure_heading(after, CF_ARCHIVE_HEADING)
    lines = after.splitlines()
    cf_start, cf_end = _section_span(lines, CF_ARCHIVE_HEADING)
    rc = next((i for i in range(cf_start + 1, cf_end)
               if lines[i] == RC_ARCHIVE_HEADING), None)
    if rc is None:  # subsection missing: create it at the end of the CF section
        return "\n".join(_insert_block(lines, cf_end, [RC_ARCHIVE_HEADING, "", bullet_line])) + "\n"
    for j in range(rc + 1, cf_end):
        if _BULLET_RE.match(lines[j]):
            return "\n".join(lines[:j] + [bullet_line] + lines[j:]) + "\n"
        if lines[j].startswith("## ") or lines[j].startswith("### "):
            break
    insert_at = rc + 1
    if insert_at < cf_end and lines[insert_at].strip() == "":
        insert_at += 1
    return "\n".join(lines[:insert_at] + [bullet_line] + lines[insert_at:]) + "\n"


def move_completed(repo_root, slug, apply=False):
    """Move every Design Inventory row of `slug` to the roadmap archive,
    verbatim, and roll the `### Recent completions` bullets past the newest
    `RC_KEEP` there too. The verifier runs in memory first; with `apply=True`
    and no problems both files are written. A no-op returns `moved=0`, reason
    naming the slug."""
    root = Path(repo_root)
    archive_rel = living_doc_archive.archive_for(LIVE_REL)
    live_path = root / LIVE_REL
    if not live_path.is_file():
        return MoveResult(0, f"live roadmap not found: {LIVE_REL}")
    before_live = live_path.read_text(encoding="utf-8")
    lines = before_live.splitlines()

    slug_rows = _find_rows(lines, slug, root)
    overflow = _rc_overflow(lines)
    if not slug_rows and not overflow:
        return MoveResult(
            0, f"nothing to move for '{slug}': no Design Inventory row attributable "
            f"to the slug, and `### Recent completions` holds at most {RC_KEEP} bullets",
        )

    idxs = [row_idx for row_idx, _ in slug_rows] + overflow
    rows = [lines[i] for i in idxs]
    gone = set(idxs)
    after_live = "\n".join(line for i, line in enumerate(lines) if i not in gone)
    if not after_live.endswith("\n"):
        after_live += "\n"

    archive_path = root / archive_rel
    before_archive = archive_path.read_text(encoding="utf-8") if archive_path.is_file() else ""
    after_archive = before_archive or living_doc_archive.ARCHIVE_HEADER[archive_rel]
    for row_idx, table_start in slug_rows:  # document order: each lands under its own sub-heading
        subheading = _nearest_heading(lines, table_start, "### ") or "### Unsubheaded"
        after_archive = _place_row(
            after_archive, subheading,
            lines[table_start], lines[table_start + 1], lines[row_idx],
        )
    for i in reversed(overflow):  # oldest first: each lands on top, newest-first
        after_archive = _place_bullet(after_archive, lines[i])

    problems = verify_moves.verify_move(
        before_live, after_live, before_archive, after_archive,
        scaffold=verify_moves.scaffold_lines(archive_rel, after_archive),
    )
    if problems:
        return MoveResult(0, "verifier: " + "; ".join(problems), rows)

    if apply:
        live_path.write_text(after_live, encoding="utf-8")
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_text(after_archive, encoding="utf-8")
    return MoveResult(len(rows), None, rows)


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Move a merged design's Design Inventory rows to the roadmap archive.")
    parser.add_argument("--slug", required=True, metavar="S",
                        help="design slug whose rows move (run after the merge is verified)")
    parser.add_argument("--apply", action="store_true", help="write the move (default: dry-run)")
    parser.add_argument("--json", action="store_true", help="print the MoveResult as JSON")
    parser.add_argument("--repo-root", default=".", metavar="R", help="repo root (default: .)")
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    result = move_completed(args.repo_root, args.slug, apply=args.apply)
    if args.json:
        payload = {"moved": result.moved, "reason": result.reason, "rows": result.rows or []}
        print(json.dumps(payload, indent=2))
    elif result.moved:
        verb = "moved" if args.apply else "would move (dry-run)"
        print(f"inventory_archive: {verb} {result.moved} line(s) for '{args.slug}'")
        for line in result.rows or []:
            print(f"  {line}")
    else:
        print(f"inventory_archive: nothing moved for '{args.slug}' — {result.reason}")
    if result.reason and result.reason.startswith("verifier:"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
