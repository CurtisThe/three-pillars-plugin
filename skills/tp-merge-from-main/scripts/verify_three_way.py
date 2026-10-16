#!/usr/bin/env python3
"""Three-way verifier core: per-occurrence atoms and the sections they own.

`verify_atoms.atoms` answers "which (kind, signature) atoms does a text hold" as a SET, so a
signature held twice looks like once. This module re-reads the same text per OCCURRENCE: every
atom is returned with the place it sits in (`key`) and the lines it owns (`start`, `end`), so a
later three-way check can tell "one side retitled L1" from "L1 was dropped". `excused_atoms` is
that check: it names the base atoms one side changed in place while the other left them alone.

Line kinds (`entry`, `heading-entry`, `row`, `slug-row`, `log`) are found by calling `verify_atoms.atoms` on
each line, exactly as `archive_moves._scan` does, so there is no second copy of the line scanner
to drift. Only the section bounds and the decision-entry block bounds are scanned here, with this
module's own regexes. Lines split with `splitlines()`, the same split `atoms` uses, so indexes and
the atom set agree even for a stray form feed or U+2028.
"""
from __future__ import annotations

import re
from typing import NamedTuple

from verify_atoms import _norm, atoms

_LINE_KINDS = ("entry", "heading-entry", "row", "log", "slug-row")
_HEADING = re.compile(r"^#{1,3}[ \t]")
# One key namespace for `entry` and `heading-entry`: an ID, a `M-new-x` placeholder or a `slug`.
_HEAD_KEY = re.compile(r"^### ([A-Z](?:\d+|-new-[a-z0-9]+(?:-[a-z0-9]+)*)|`[a-z0-9][a-z0-9-]*`)")
# A row's place key is its ID or, for a slug row, the raw `slug` (equal to its atom signature, so a
# slug row's other cells can change on one side with no excuse and a rename is a pure removal).
_ROW_KEY = re.compile(r"^\|\s*([A-Z]\d+|`[a-z0-9][a-z0-9-]*`)")
_LOG_KEY = re.compile(r"^-\s+\*\*(`[a-z0-9][a-z0-9-]*`|\d{4}-\d{2}-\d{2})\*\*")
_DECISION_KEY = re.compile(r"^### \[([^\]\s][^\]]*)\]\s+(.+)$")


class Occ(NamedTuple):
    """One atom occurrence: its `kind`, signature, place `key`, and 0-based lines [start, end)."""

    kind: str
    sig: str
    key: str
    start: int
    end: int


def _trim(lines: list[str], start: int, end: int) -> int:
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return end


def _line_key(kind: str, line: str, sig: str) -> str:
    if kind == "slug-row":
        return sig      # a plain or bold slug row (`keyed-row-insertion`): its slug is sig and key
    rx = {"row": _ROW_KEY, "log": _LOG_KEY}.get(kind, _HEAD_KEY)
    m = rx.match(line)
    return m.group(1) if m else ""


def _section_end(lines: list[str], i: int, kind: str) -> int:
    if kind not in ("entry", "heading-entry"):
        return i + 1
    j = i + 1
    while j < len(lines) and not _HEADING.match(lines[j]):
        j += 1
    return _trim(lines, i, j)


def occurrences(text: str) -> list[Occ]:
    """Every atom occurrence in `text`, in document order."""
    lines = text.splitlines()
    out: list[Occ] = []
    heads: list[int] = []
    for i, line in enumerate(lines):
        for kind, sig in atoms(line):
            if kind == "decision-entry":
                heads.append(i)
            elif kind in _LINE_KINDS:
                out.append(Occ(kind, sig, _line_key(kind, line, sig), i, _section_end(lines, i, kind)))
    for a, b in zip(heads, heads[1:] + [len(lines)]):
        m = _DECISION_KEY.match(lines[a])
        key = _norm(f"[{m.group(1)}] {m.group(2)}") if m else ""
        for kind, sig in atoms("\n".join(lines[a:b])):
            if kind == "decision-entry":
                out.append(Occ(kind, sig, key, a, _trim(lines, a, b)))
    return sorted(out, key=lambda o: o.start)


def _family(kind: str) -> str:
    """The key namespace a kind lives in: `entry` and `heading-entry` share one, the rest own one."""
    return "head" if kind in ("entry", "heading-entry") else kind


class _Side:
    """One document's occurrences, indexed by atom and by (key family, place key)."""

    def __init__(self, text: str) -> None:
        self.lines = text.splitlines()
        self.by_atom: dict[tuple[str, str], list[Occ]] = {}
        self.by_slot: dict[tuple[str, str], list[Occ]] = {}
        for occ in occurrences(text):
            self.by_atom.setdefault((occ.kind, occ.sig), []).append(occ)
            self.by_slot.setdefault((_family(occ.kind), occ.key), []).append(occ)

    def section(self, occ: Occ) -> list[str]:
        return self.lines[occ.start:occ.end]


def _changed_in_place(atom: tuple[str, str], base: _Side, s: _Side, o: _Side) -> bool:
    """True when side `s` replaced base `atom` in place and side `o` left its section alone."""
    if atom in s.by_atom:
        return False
    in_base, in_o = base.by_atom.get(atom, []), o.by_atom.get(atom, [])
    if len(in_base) != 1 or len(in_o) != 1:
        return False
    if base.section(in_base[0]) != o.section(in_o[0]):
        return False
    slot = (_family(atom[0]), in_base[0].key)
    if not slot[1] or len(base.by_slot.get(slot, [])) != 1 or len(o.by_slot.get(slot, [])) != 1:
        return False
    replacements = s.by_slot.get(slot, [])
    if len(replacements) != 1:
        return False
    new = (replacements[0].kind, replacements[0].sig)
    return len(s.by_atom[new]) == 1 and new not in o.by_atom


def excused_atoms(base: str, ours: str, theirs: str) -> set[tuple[str, str]]:
    """Base atoms the zero-drop check may skip: absent from both sides, or changed in place.

    Option (a), a CHANGED atom only: one side lost the atom but still carries exactly one
    replacement under the same place key, and the other side's section is byte-equal to base's.
    A pure one-side removal, a both-sides change, a duplicate signature or key, a key repeated in
    the changing side, or a replacement another entry could satisfy are all NOT excused.
    """
    b, o, t = _Side(base), _Side(ours), _Side(theirs)
    out: set[tuple[str, str]] = set()
    for atom in b.by_atom:
        if atom not in o.by_atom and atom not in t.by_atom:
            out.add(atom)
        elif _changed_in_place(atom, b, o, t) or _changed_in_place(atom, b, t, o):
            out.add(atom)
    return out
