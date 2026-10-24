"""docs_fold_issues.py — the known-issues arm of the fragment fold.

design: living-doc-fragments, Task 1.3 (grammar: design §Entities). ``## Known issues — add`` blocks
go verbatim under ``## Critical / High`` (H) or ``## Medium`` (M) of ``known_issues.md``, and L blocks
to the Low part ``low_doc_parts.target_part`` names (the one disk read, from ``root``; without a root
the last Low part already in the docs). ``## Known issues — resolve`` lines move the entry verbatim to
``known_issues_resolved.md`` under its original ``## `` section, headed ``### <ID> (RESOLVED <date>):``
with the note as its last line. Every function edits the ``docs`` mapping it is given. Stdlib only.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import low_doc_parts  # noqa: E402
from docs_fold_text import (FoldError, append_point, append_to_text, entry_end, expand_pr,  # noqa: E402
                            find_heading, heading_of, insert_block, join, section_end, split)

KI = "three-pillars-docs/known_issues.md"
RESOLVED = "three-pillars-docs/known_issues_resolved.md"
RESOLVED_HEADER = "# Known Issues — RESOLVED archive\n"
ADD = "Known issues — add"
RESOLVE = "Known issues — resolve"
SEVERITY_SECTIONS = {"H": "Critical / High", "M": "Medium"}


def _block_lines(block, pr) -> list[str]:
    return [expand_pr(line, pr) for line in [f"### {block.heading}"] + list(block.body)]


def _low_target(docs: dict, add_chars: int, root) -> str:
    if root is not None:
        rel = low_doc_parts.target_part(Path(root), add_chars)
        if rel is None:
            raise FoldError(ADD, "every Low part is full (raise low_doc_parts.MAX_PARTS)")
        return rel
    present = [rel for rel in low_doc_parts.PART_RELS if rel in docs]
    return present[-1] if present else low_doc_parts.FIRST_REL


def fold_add(docs: dict, blocks, *, pr, root) -> set[str]:
    """Insert every add block; return the rels touched."""
    touched: set[str] = set()
    for block in blocks:
        lines = _block_lines(block, pr)
        severity = block.heading[:1]
        if severity == "L":
            rel = _low_target(docs, len(join(lines)) + 1, root)
            existing = docs.get(rel, low_doc_parts.part_header(low_doc_parts.part_number(rel)))
            docs[rel] = append_to_text(existing, lines)
            touched.add(rel)
            continue
        if KI not in docs:
            raise FoldError(ADD, f"target doc is missing: {KI}")
        doc = split(docs[KI])
        start = find_heading(doc, SEVERITY_SECTIONS[severity], level=2)
        if start is None:
            raise FoldError(ADD, f"no '## {SEVERITY_SECTIONS[severity]}' section in {KI}")
        insert_block(doc, append_point(doc, start, section_end(doc, start)), lines)
        docs[KI] = join(doc)
        touched.add(KI)
    return touched


def _locate(docs: dict, issue_id: str) -> tuple[str, int] | None:
    """(rel, line index) of the ``### <ID>:`` heading in ``known_issues.md`` or a Low part."""
    prefix = f"### {issue_id}:"
    for rel in (KI,) + low_doc_parts.PART_RELS:
        if rel not in docs:
            continue
        for i, line in enumerate(split(docs[rel])):
            if line.startswith(prefix):
                return rel, i
    return None


def _original_section(lines: list[str], start: int, default: str) -> str:
    for i in range(start - 1, -1, -1):
        head = heading_of(lines[i])
        if head and head[0] == 2:
            return head[1]
    return default


def _archive(docs: dict, section: str, entry: list[str]) -> None:
    text = docs.get(RESOLVED, RESOLVED_HEADER)
    lines = split(text)
    start = find_heading(lines, section, level=2)
    if start is None:
        docs[RESOLVED] = append_to_text(text, [f"## {section}", ""] + entry)
        return
    insert_block(lines, append_point(lines, start, section_end(lines, start)), entry)
    docs[RESOLVED] = join(lines)


def fold_resolve(docs: dict, blocks, *, pr, date: str) -> set[str]:
    """Move every resolved entry to the archive; return the rels touched."""
    touched: set[str] = set()
    for block in blocks:
        found = _locate(docs, block.heading)
        if found is None:
            raise FoldError(RESOLVE, f"no entry '### {block.heading}:' in {KI} or a Low part")
        rel, start = found
        lines = split(docs[rel])
        end = entry_end(lines, start)
        body = lines[start + 1:end]
        while body and not body[-1].strip():
            body.pop()
        title = lines[start][len(f"### {block.heading}:"):]
        entry = [f"### {block.heading} (RESOLVED {date}):{title}"] + body
        entry += [expand_pr(note, pr) for note in block.body]
        section = _original_section(lines, start, "Low")
        del lines[start:end]
        docs[rel] = join(lines)
        _archive(docs, section, entry)
        touched |= {rel, RESOLVED}
    return touched
