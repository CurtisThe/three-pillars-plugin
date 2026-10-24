"""docs_compile_verify.py — the zero-drop verify of ``docs_compile`` (design §Interfaces step 4).

design: living-doc-fragments, Task 1.5. ``verify_compile(before, after, fragments_numbered,
resolved_ids, directed) -> list`` returns the atoms (``verify_atoms`` keys) that were in the docs
before, or in a folded fragment's added lines, and are gone from the docs after, minus the atoms the
fragments themselves remove or replace (``directed``). ``before`` / ``after`` map a repo-relative path
to its text; only the guarded set (the auto-safe living docs minus ``vision.md``, plus the Low parts)
is read, concatenated, so a move between files keeps its atom in the set. Both inputs are put in
their expected final form first: ``before`` gets each resolved ``### <ID>:`` heading rewritten to
``### <ID> (RESOLVED <date>):`` (``resolved_ids``: id -> date), and ``fragments_numbered`` are the
fragment texts after numbering, so ``M-new-x`` already reads ``M52``. A renumber or a resolve move is
then atom-identical. A scan of zero atoms is itself a refusal (the ``UNVERIFIABLE`` verdict).
Stdlib only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
for _path in (_SHARED, _SHARED.parent / "tp-merge-from-main" / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import auto_safe_resolution  # noqa: E402
import low_doc_parts  # noqa: E402
import verify  # noqa: E402

VISION = "three-pillars-docs/vision.md"
ADD_SECTIONS = ("Known issues — add",)
OP_SECTIONS = ("Roadmap", "Architecture")


def is_guarded(rel: str) -> bool:
    """True for a shared living doc whose atoms the compile must not drop."""
    return (rel in auto_safe_resolution.AUTO_SAFE_PATHS and rel != VISION) or low_doc_parts.is_part_rel(rel)


def _concat(docs: dict) -> str:
    return "\n".join(docs[rel] for rel in sorted(docs) if is_guarded(rel))


def _added_lines(text: str) -> str:
    """The lines one numbered fragment adds: ``+`` lines (prefix cut) and the add-section blocks."""
    out, section = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        elif section in OP_SECTIONS and line.startswith("+ "):
            out.append(line[2:])
        elif section in ADD_SECTIONS:
            out.append(line)
    return "\n".join(out)


def _as_resolved(text: str, resolved_ids: dict) -> str:
    for issue_id, date in resolved_ids.items():
        text = re.sub(rf"^### {re.escape(issue_id)}:", f"### {issue_id} (RESOLVED {date}):", text, flags=re.M)
    return text


def verify_compile(before: dict, after: dict, fragments_numbered, resolved_ids, directed) -> list:
    """The atoms dropped by the compile and not directed by a fragment (empty = verified)."""
    ours = _as_resolved(_concat(before), dict(resolved_ids))
    theirs = "\n".join(_added_lines(text) for text in fragments_numbered)
    result = verify.verify(ours, theirs, _concat(after), base=None, mechanical_applied=True)
    if result.verdict == verify.UNVERIFIABLE:
        return [("unverifiable", "0 atoms parsed from the guarded docs")]
    return [atom for atom in result.dropped if atom not in set(directed)]
