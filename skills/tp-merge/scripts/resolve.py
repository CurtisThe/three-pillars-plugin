#!/usr/bin/env python3
"""Mechanical conflict resolvers + semantic deferral.

For each classified hunk:
  - mechanical class -> deterministic zero-drop merge (union; renumber on ID collision)
  - semantic class   -> DEFER (leave the conflict for a human), unless force=True

`force=True` bypasses deferral and makes a naive best-effort auto-merge (take theirs) even on
semantic hunks. It exists ONLY to construct the unsafe counterfactual the verifier test needs;
the merge driver never calls it.

Design invariant (validated by the spike): mechanical resolvers NEVER drop an atom (a `### L<n>:`
entry, an inventory row, or a log line). On an ID collision the entry is *renumbered and kept*.

Production deltas over the spike prototype:
  - **monotonic renumber** — theirs' entries are re-numbered to a contiguous block after ours'
    highest ID in document order (spike left a non-monotonic L4,L7,L5,L6).
  - **cross-reference updates** — textual `L<old>` references inside theirs' renumbered blocks are
    rewritten to the new IDs so in-document links stay valid.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify import (  # noqa: E402
    Hunk, classify_file, is_confident, MECHANICAL, GATED, ID_HEADING, INV_ROW,
)

RESOLVED, DEFER = "RESOLVED", "DEFER"


@dataclass
class HunkResult:
    label: str
    status: str            # RESOLVED | DEFER
    lines: list[str]
    reason: str = ""
    renumbered: dict = field(default_factory=dict)   # {old_id: new_id} for audit


# ---- entry / row parsing ---------------------------------------------------------

def split_entries(lines: list[str]) -> list[tuple[str | None, list[str]]]:
    """Split a block into (id, block-lines) by `### L<n>:` headings. Pre-heading lines get id=None."""
    out: list[tuple[str | None, list[str]]] = []
    cur_id, cur = None, []
    for line in lines:
        m = ID_HEADING.match(line)
        if m:
            if cur:
                out.append((cur_id, cur))
            cur_id, cur = m.group(1) + m.group(2), [line]
        else:
            cur.append(line)
    if cur:
        out.append((cur_id, cur))
    return out


def _retag(block: list[str], letter: str, new_n: int) -> list[str]:
    out, done = [], False
    for line in block:
        if ID_HEADING.match(line) and not done:
            out.append(ID_HEADING.sub(rf"### {letter}{new_n}:", line, count=1))
            done = True
        else:
            out.append(line)
    return out


def _apply_xref(lines: list[str], remap: dict[str, str]) -> list[str]:
    """Rewrite *bare prose* `L<old>` cross-references to their renumbered IDs, in ONE atomic pass.

    Single-pass is load-bearing: iterating `remap.items()` with successive `re.sub` calls cascades
    on chained renumbers (`L4→L5`, `L5→L6` would turn a real `L4` into `L6`). Instead we match any
    old key with one alternation and look each match up in `remap`, so every reference maps to its
    DIRECT target exactly once.

    Conservative on purpose: a plain `\\b` boundary would corrupt IDs embedded in URL anchors or
    markdown links (`#L4-heading`, `[L4](#L4)`). Those are guarded by the *preceding* char — an
    anchor/link/path/code ID is always prefixed by `# / [ \\``. So the lookbehind excludes those
    (plus word chars); the lookahead only needs to exclude word chars, `-`, `/`, `#`, `\\`` (a
    trailing hyphen-anchor or path). This still rewrites bare prose refs like `see L5`, `(L5)`,
    and `L5.` while leaving `#L5-x` and `[L5](#L5)` intact. The remap is also surfaced in the
    report so a human can eyeball references.
    """
    if not remap:
        return lines
    alt = "|".join(re.escape(k) for k in sorted(remap, key=len, reverse=True))
    pat = re.compile(rf"(?<![\w#/\[`])(?:{alt})(?![\w#/`-])")
    return [pat.sub(lambda m: remap[m.group(0)], line) for line in lines]


# ---- mechanical resolvers --------------------------------------------------------

def resolve_id_renumber(h: Hunk) -> HunkResult:
    """Union ours' + theirs' entries; renumber theirs' entries to a contiguous monotonic block
    after ours' highest ID, in document order. Zero-drop."""
    ours_e = split_entries(h.ours)
    theirs_e = split_entries(h.theirs)
    letter = "L"
    ours_nums: list[int] = []
    for _id, _ in ours_e:
        m = re.match(r"([A-Z])(\d+)", _id or "")
        if m:
            letter = m.group(1)
            ours_nums.append(int(m.group(2)))
    base_max = max(ours_nums) if ours_nums else 0

    merged: list[str] = []
    for _id, block in ours_e:
        merged += block

    # Build remap for theirs in document order, then renumber + fix cross-refs.
    remap: dict[str, str] = {}
    nxt = base_max + 1
    plan: list[tuple[list[str], int]] = []
    for _id, block in theirs_e:
        m = re.match(r"([A-Z])(\d+)", _id or "")
        if m:
            old = f"{m.group(1)}{m.group(2)}"
            new = f"{letter}{nxt}"
            if old != new:
                remap[old] = new
            plan.append((block, nxt))
            nxt += 1
        else:
            plan.append((block, 0))   # non-entry tail; keep as-is
    for block, new_n in plan:
        # Atomic _apply_xref maps the heading's own old ID directly to its new ID (== new_n) and
        # any body cross-refs to their direct targets, all in one pass (no cascade). _retag then
        # re-stamps the heading to new_n — a no-op confirmation, since xref already produced it.
        block = _apply_xref(block, remap)
        if new_n:
            block = _retag(block, letter, new_n)
        merged += block
    return HunkResult("id-renumber-collision", RESOLVED, merged, renumbered=remap)


def resolve_inventory(h: Hunk) -> HunkResult:
    """Union table rows keyed by design-ID. On same-ID conflict prefer theirs (newer/master side).
    Zero-drop at BOTH the row AND the line level: ours' block is emitted in full — including
    non-row lines (table header, `| --- |` separator, blanks, prose) — with conflicting rows
    swapped to theirs' version; then theirs-only rows are appended. No line and no row is lost.
    (Earlier version reduced the hunk to an ID->row dict and silently dropped header/separator
    lines, which the atoms-only verifier could not catch — fixed.)"""
    def row_id(line: str) -> str | None:
        m = INV_ROW.match(line)
        return m.group(1) if m else None

    theirs_rows: dict[str, str] = {}
    theirs_order: list[str] = []
    for line in h.theirs:
        k = row_id(line)
        if k is not None:
            if k not in theirs_rows:
                theirs_order.append(k)
            theirs_rows[k] = line

    out_lines: list[str] = []
    ours_ids: set[str] = set()
    for line in h.ours:
        k = row_id(line)
        if k is not None:
            ours_ids.add(k)
            out_lines.append(theirs_rows.get(k, line))   # theirs wins same-ID conflict
        else:
            out_lines.append(line)                        # preserve header/separator/blank/prose
    for k in theirs_order:                                # append theirs-only rows
        if k not in ours_ids:
            out_lines.append(theirs_rows[k])
    return HunkResult("design-inventory-row-merge", RESOLVED, out_lines)


def resolve_append_log(h: Hunk) -> HunkResult:
    """base is a common prefix of both; union the two tails, dedup identical lines."""
    n = len(h.base)
    seen, tail = set(), []
    for line in h.ours[n:] + h.theirs[n:]:
        if line not in seen:
            seen.add(line)
            tail.append(line)
    return HunkResult("append-only-log", RESOLVED, h.base + tail)


MECH_RESOLVERS = {
    "id-renumber-collision": resolve_id_renumber,
    "design-inventory-row-merge": resolve_inventory,
    "append-only-log": resolve_append_log,
}


def _deferred(h: Hunk, reason: str) -> HunkResult:
    conflict = ["<<<<<<< ours", *h.ours, "=======", *h.theirs, ">>>>>>> theirs"]
    return HunkResult(h.label, DEFER, conflict, reason=reason)


def resolve_hunk(h: Hunk, force: bool = False) -> HunkResult:
    if force:
        # Bypass every gate — used ONLY to construct the unsafe counterfactual for the verifier test.
        if h.label in MECHANICAL:
            return MECH_RESOLVERS[h.label](h)
        return HunkResult(h.label, RESOLVED, h.theirs, reason="force: took theirs (UNSAFE)")
    if h.label in MECHANICAL:
        # Auto-resolve only when mechanical AND not gated AND the classifier is confident.
        if h.label in GATED:
            return _deferred(h, f"gated class ({h.label}) — human until a fixture exists")
        if not is_confident(h):
            return _deferred(h, f"classifier not confident ({h.label}, mixed structure)")
        return MECH_RESOLVERS[h.label](h)
    return _deferred(h, "semantic class — needs human")


def resolve_file(conflict_text: str, force: bool = False):
    """Return (file_status, reassembled_lines, [HunkResult]).
    file_status == RESOLVED iff every hunk resolved; else DEFER."""
    pf = classify_file(conflict_text)
    results, out_lines, all_resolved = [], [], True
    for seg in pf.segments:
        if isinstance(seg, str):
            out_lines += seg.splitlines()
        else:
            r = resolve_hunk(seg, force=force)
            results.append(r)
            out_lines += r.lines
            if r.status == DEFER:
                all_resolved = False
    return (RESOLVED if all_resolved else DEFER), out_lines, results


def _main(argv: list[str]) -> int:
    force = "--force" in argv
    for path in [a for a in argv if not a.startswith("--")]:
        status, _lines, results = resolve_file(Path(path).read_text(), force=force)
        print(f"\n{path}  -> FILE {status}{'  (force)' if force else ''}")
        for n, r in enumerate(results, 1):
            extra = f"  renumber={r.renumbered}" if r.renumbered else ""
            print(f"  hunk {n}: {r.status:8} {r.label}  {r.reason}{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
