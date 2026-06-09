#!/usr/bin/env python3
"""Independent zero-drop verifier for living-doc merges.

Knows NOTHING about the resolver. It inventories *content atoms* present in ours ∪ theirs and
asserts each survives into the resolved output. Atom identity is **ID-independent**, so a
legitimate renumber (L4 -> L7) is not mistaken for a drop:

    entry atom  `### L<n>: <title>`  -> signature = normalized <title>
    row atom    `| D<n> | <name> | ` -> signature = normalized <name>

Prose / preamble lines are intentionally NOT atoms — legitimate prose edits would look like drops.
The verifier guards structured-content drops (entries, rows), which is where "silently lose an
entry" actually bites.

CRITICAL property from the spike: this verifier is NECESSARY BUT NOT SUFFICIENT. It catches a
structural drop (it even caught a real human silent drop), but it MISSES a semantic mis-merge
whose atom survives while its meaning is wrong. Semantic safety must therefore be carried by
DEFERRAL in the resolver, with this verifier as a backstop for the mechanical classes only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ENTRY = re.compile(r"^### [A-Z]\d+:\s*(.*)$")
ROW = re.compile(r"^\|\s*[A-Z]\d+\s*\|\s*([^|]+?)\s*\|")


def _norm(s: str) -> str:
    s = re.sub(r"[`*_]", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def atoms(text: str) -> dict[tuple[str, str], str]:
    """Return {(kind, signature): kind} for every structured atom in `text`."""
    out: dict[tuple[str, str], str] = {}
    for line in text.splitlines():
        m = ENTRY.match(line)
        if m and _norm(m.group(1)):
            out[("entry", _norm(m.group(1)))] = "entry"
            continue
        m = ROW.match(line)
        if m and _norm(m.group(1)):
            out[("row", _norm(m.group(1)))] = "row"
    return out


def verify(ours: str, theirs: str, resolved: str):
    """Return (ok, dropped) where dropped is a list of (kind, signature) atoms lost from ours∪theirs."""
    pre = {**atoms(ours), **atoms(theirs)}
    post = atoms(resolved)
    dropped = [k for k in pre if k not in post]
    return (len(dropped) == 0, dropped)


def verify_paths(ours_p, theirs_p, resolved_p):
    return verify(Path(ours_p).read_text(), Path(theirs_p).read_text(), Path(resolved_p).read_text())


def _main(argv: list[str]) -> int:
    ok, dropped = verify_paths(*argv[:3])
    print("ZERO-DROP" if ok else f"DROPS DETECTED ({len(dropped)}):")
    for kind, sig in dropped:
        print(f"   dropped {kind}: {sig[:70]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
