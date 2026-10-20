"""low_doc_parts.py — the one helper that lists the Low-doc parts.

design: basesync-count-line-and-low-headroom (1.1)

`known_issues_low.md` sits at the 50,000-char diet cap with no headroom, so
Lows are split across numbered parts: `known_issues_low.md`, then
`known_issues_low_2.md` … `known_issues_low_9.md`. Every reader (the base-sync
count-line resolver, the writers, the backstop) takes the set from here rather
than naming one path, so a consumer repo with only `known_issues.md` (no Low
doc at all) lists no parts and behaves exactly as today.

Stdlib only, import-safe in a consumer repo. CAP is a literal (not imported
from `file_size_guard`) so this module stays dependency-free; the pin that the
two agree lives in `test_low_doc_parts.py`.

CLI:
  low_doc_parts.py target --root R --chars N [--create]
  low_doc_parts.py count  --root R
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DOCS = "three-pillars-docs/"
FIRST_REL = DOCS + "known_issues_low.md"
MAX_PARTS = 9  # the framework-check.sh glob `known_issues_low_[2-9].md` must agree
CAP = 50_000   # the 50,000-char diet cap test_diet_caps_real_tree.py applies
RESERVE = 5_000

_PART_RE = re.compile(r"three-pillars-docs/known_issues_low(?:_([2-9]))?\.md")
LOW_HEADING = re.compile(r"^### L(?:[0-9]+|-new-[a-z0-9])", re.M)


class LowSplitError(ValueError):
    """A Low part cannot be split without losing or duplicating an entry."""


def part_rel(n: int) -> str:
    """The rel path of Low part `n` (1-based; part 1 is the unsuffixed doc)."""
    return FIRST_REL if n == 1 else DOCS + f"known_issues_low_{n}.md"


PART_RELS = tuple(part_rel(n) for n in range(1, MAX_PARTS + 1))


def is_part_rel(rel: str) -> bool:
    """True when `rel` names one of the Low parts (either slash style)."""
    return _PART_RE.fullmatch(rel.replace("\\", "/")) is not None


def part_number(rel: str) -> int | None:
    """The part number of `rel`, or None when it is not a Low part."""
    m = _PART_RE.fullmatch(rel.replace("\\", "/"))
    if m is None:
        return None
    return int(m.group(1)) if m.group(1) else 1


def next_part_rel(rel: str) -> str | None:
    """The rel of the part after `rel`, or None past `MAX_PARTS`."""
    n = part_number(rel)
    if n is None or n >= MAX_PARTS:
        return None
    return part_rel(n + 1)


def parts_on_disk(root: Path) -> list[str]:
    """The `PART_RELS` that exist as files under `root`, in part order."""
    return [rel for rel in PART_RELS if (root / rel).is_file()]


def count_lows(text: str) -> int:
    """How many `### L…` issue headings `text` holds."""
    return len(LOW_HEADING.findall(text))


def total_lows(root: Path) -> int:
    """The `### L` heading count across every Low part on disk."""
    return sum(count_lows(_read(root, rel)) for rel in parts_on_disk(root))


def part_header(n: int) -> str:
    """The H1 a Low part starts with (part 1 is the unsuffixed cold doc)."""
    if n == 1:
        return "# Known Issues — Low (cold)\n\n"
    return f"# Known Issues — Low (cold), part {n}\n\n"


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def target_part(root: Path, add_chars: int) -> str | None:
    """The part a new Low of `add_chars` should go into, or None when full."""
    on_disk = parts_on_disk(root)
    if not on_disk:
        return FIRST_REL
    last = on_disk[-1]
    if len(_read(root, last)) + add_chars <= CAP - RESERVE:
        return last
    return next_part_rel(last)


def _split_entries(text: str) -> tuple[str, list[str]]:
    """(preamble, entries): each entry runs from a `### ` line to the next."""
    starts = [m.start() for m in re.finditer(r"^### ", text, re.M)]
    if not starts:
        return text, []
    entries = [text[a:b] for a, b in zip(starts, starts[1:] + [len(text)])]
    return text[: starts[0]], entries


def split_part(root: Path, rel: str, cap: int = CAP) -> int:
    """Move whole trailing entries of `rel` into the next part; count moved.

    Raises `LowSplitError` (leaving every file byte-identical) when there is no
    next part, when the part holds no `### ` entry to move, when the preamble
    alone is already over `cap`, when keeping the first entry still leaves the
    part over `cap`, when the next part would go over `cap`, or when the heading
    counts before and after do not match. Nothing is ever written on a refusal:
    a part with no entry to move must not gain a header-only sibling (C1).
    """
    nxt = next_part_rel(rel)
    if nxt is None:
        raise LowSplitError(f"low_doc_parts: {rel} is the last Low part")
    text = _read(root, rel)
    preamble, entries = _split_entries(text)
    if len(text) <= cap:
        return 0
    if not entries:
        raise LowSplitError(f"low_doc_parts: {rel} holds no '### ' entry to move")
    if len(preamble) >= cap:
        raise LowSplitError(f"low_doc_parts: {rel} preamble alone is over cap")
    keep = len(entries) - 1
    while keep > 0 and len(preamble + "".join(entries[:keep])) > cap:
        keep -= 1
    if keep == 0:
        raise LowSplitError(f"low_doc_parts: {rel} first entry is over cap")
    rest, moved = preamble + "".join(entries[:keep]), "".join(entries[keep:])
    existing = _read(root, nxt) if (root / nxt).is_file() else None
    head = part_header(part_number(nxt)) if existing is None else existing
    if not head.endswith("\n"):
        head += "\n"
    if len(head + moved) > cap:
        raise LowSplitError(f"low_doc_parts: {nxt} would go over cap")
    if count_lows(rest) + count_lows(head + moved) != count_lows(text) + (
        count_lows(existing) if existing is not None else 0
    ):
        raise LowSplitError(f"low_doc_parts: heading count changed splitting {rel}")
    (root / rel).write_text(rest, encoding="utf-8")
    (root / nxt).write_text(head + moved, encoding="utf-8")
    return len(entries) - keep


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="low_doc_parts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("target")
    t.add_argument("--root", default=".")
    t.add_argument("--chars", type=int, required=True)
    t.add_argument("--create", action="store_true")
    c = sub.add_parser("count")
    c.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if args.cmd == "count":
        print(total_lows(root))
        return 0
    rel = target_part(root, args.chars)
    if rel is None:
        print("low_doc_parts: every Low part is full (raise MAX_PARTS)",
              file=sys.stderr)
        return 2
    print(rel)
    if args.create and not (root / rel).is_file():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(part_header(part_number(rel)), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
