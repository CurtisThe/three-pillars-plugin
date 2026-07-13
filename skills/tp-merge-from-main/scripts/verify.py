#!/usr/bin/env python3
"""Independent zero-drop verifier for living-doc merges.

Knows NOTHING about the resolver. It inventories *content atoms* present in ours ∪ theirs and
asserts each survives into the resolved output. Atom identity is **ID-independent**, so a
legitimate renumber (L4 -> L7) is not mistaken for a drop:

    entry atom  `### L<n>: <title>`         -> signature = normalized <title>
    row atom    `| D<n> | <name> | `        -> signature = normalized <name>
    log atom    `- **<date|`slug`>** — …`   -> signature = normalized <key + title>

The log atom is the C3 backstop for the append-only-log class (dated `## History` bullets and
name-keyed `### Recent completions` bullets): those entries are kept VERBATIM by the resolver (no
renumber), so — unlike `entry` — the signature is NOT ID-independent; the whole bullet identifies
the atom, and a dropped log bullet on either input side is caught here.

Prose / preamble lines are intentionally NOT atoms — legitimate prose edits would look like drops.
The verifier guards structured-content drops (entries, rows, log bullets), which is where "silently
lose an entry" actually bites.

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
# Log atom — a bold-lead-bullet log entry, dated OR name-keyed. Mirrors classify.LOG_ENTRY's shape,
# re-derived here so the verifier stays independent of the resolver. Group 1 (everything after the
# `- ` marker, i.e. `**<key>** — <title>`) is the signature; the kebab-slug arm excludes file-path
# description bullets, matching what the resolver actually keeps.
LOG = re.compile(r"^-\s+(\*\*(?:`[a-z0-9][a-z0-9-]*`|\d{4}-\d{2}-\d{2})\*\*\s+—.*)$")


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
            continue
        m = LOG.match(line)
        if m and _norm(m.group(1)):
            out[("log", _norm(m.group(1)))] = "log"
    return out


def verify(ours: str, theirs: str, resolved: str):
    """Return (ok, dropped) where dropped is a list of (kind, signature) atoms lost from ours∪theirs."""
    pre = {**atoms(ours), **atoms(theirs)}
    post = atoms(resolved)
    dropped = [k for k in pre if k not in post]
    return (len(dropped) == 0, dropped)


def verify_paths(ours_p, theirs_p, resolved_p):
    return verify(Path(ours_p).read_text(encoding="utf-8"), Path(theirs_p).read_text(encoding="utf-8"), Path(resolved_p).read_text(encoding="utf-8"))


def _main(argv: list[str]) -> int:
    ok, dropped = verify_paths(*argv[:3])
    print("ZERO-DROP" if ok else f"DROPS DETECTED ({len(dropped)}):")
    for kind, sig in dropped:
        print(f"   dropped {kind}: {sig[:70]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
