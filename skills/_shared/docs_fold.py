"""docs_fold.py — fold one living-doc fragment onto in-memory docs (pure).

design: living-doc-fragments, Task 1.3 (grammar: design §Entities). ``fold(docs, fragment, *, pr,
root=None) -> FoldResult(docs, directed)``: ``docs`` maps a repo-relative path to its text and is never
mutated; the result holds a new mapping. ``## Roadmap`` / ``## Architecture`` ``### <heading>`` blocks:
``- <line>`` removes that exact line inside the heading's section (else ``FoldError``), ``+`` lines
right after a ``-`` replace it in place, and a lone ``+`` run appends at the end of the section (a ``|`` row, after
the last row of the section's last table; ``FoldError`` when it holds none), or
prepends before its first ``- `` entry under ``Recent completions`` and any ``… History`` heading
(newest-first). ``{pr}`` expands to ``PR #N`` (``completion PR`` when ``pr`` is None). The known-issues
arm is ``docs_fold_issues``; ``## Vision`` is never folded. Every touched doc's ``*Last updated:``
line takes the fragment's ``date``, never the clock. ``directed`` is the set of ``verify_atoms`` atoms
of every removed line. The only I/O is ``low_doc_parts.target_part`` reading ``root``. Stdlib only.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
for _path in (_SHARED, _SHARED.parent / "tp-merge-from-main" / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import docs_fold_issues  # noqa: E402
from changes_fragment import TARGET_DOCS, format_problem  # noqa: E402
from docs_fold_text import (FoldError, append_point, expand_pr, find_heading, heading_of,  # noqa: E402
                            is_prepend_heading, join, prepend_point, section_end, split, stamp)

__all__ = ["FoldError", "FoldResult", "fold"]


@dataclass
class FoldResult:
    docs: dict[str, str]
    directed: set = field(default_factory=set)


def _atoms(line: str) -> set:
    import verify_atoms  # lazy: the scanner lives in tp-merge-from-main/scripts

    return set(verify_atoms.atoms(line))


def _table_point(lines: list[str], start: int, end: int) -> int | None:
    """Index just after the last row of the LAST table in the section ``[start, end)``, else None."""
    point = None
    for i in range(start + 1, end):
        if lines[i].startswith("|"):
            point = i + 1
    return point


def _fold_block(lines: list[str], block, section: str, rel: str, pr, directed: set) -> None:
    start = find_heading(lines, block.heading)
    if start is None:
        raise FoldError(section, f"no heading '{block.heading}' in {rel}")
    text = heading_of(lines[start])[1]
    cursor: int | None = None  # where the next + lands while a - / + run is open
    for op in block.ops:
        end = section_end(lines, start)
        if op.kind == "-":
            hit = next((i for i in range(start + 1, end) if lines[i] == op.text), None)
            if hit is None:
                raise FoldError(section, f"no line '{op.text}' under '{block.heading}' in {rel}")
            del lines[hit]
            directed |= _atoms(op.text)
            cursor = hit
            continue
        if cursor is None and op.text.startswith("|"):
            cursor = _table_point(lines, start, end)
            if cursor is None:
                raise FoldError(section, f"no table under '{block.heading}' in {rel} for the row")
        if cursor is None:
            cursor = (prepend_point if is_prepend_heading(text) else append_point)(lines, start, end)
        lines.insert(cursor, expand_pr(op.text, pr))
        cursor += 1


def _fold_ops(docs: dict, section: str, blocks, pr, directed: set) -> set[str]:
    rel = TARGET_DOCS[section]
    if rel not in docs:
        raise FoldError(section, f"target doc is missing: {rel}")
    lines = split(docs[rel])
    for block in blocks:
        _fold_block(lines, block, section, rel, pr, directed)
    docs[rel] = join(lines)
    return {rel}


def fold(docs: dict[str, str], fragment, *, pr: int | None, root=None) -> FoldResult:
    """Fold ``fragment`` onto a copy of ``docs``; raise ``FoldError`` when any part does not apply."""
    if fragment.problems:
        raise FoldError(fragment.problems[0].section, format_problem(fragment.problems[0]))
    out = dict(docs)
    directed: set = set()
    touched: set[str] = set()
    for section in TARGET_DOCS:
        if fragment.sections.get(section):
            touched |= _fold_ops(out, section, fragment.sections[section], pr, directed)
    adds = fragment.sections.get(docs_fold_issues.ADD)
    if adds:
        touched |= docs_fold_issues.fold_add(out, adds, pr=pr, root=root)
    resolves = fragment.sections.get(docs_fold_issues.RESOLVE)
    if resolves:
        touched |= docs_fold_issues.fold_resolve(out, resolves, pr=pr, date=fragment.date)
    for rel in touched:
        out[rel] = stamp(out[rel], fragment.date)
    return FoldResult(out, directed)
