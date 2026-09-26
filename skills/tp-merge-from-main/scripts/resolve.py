#!/usr/bin/env python3
"""Mechanical conflict resolvers + semantic deferral.

For each classified hunk:
  - mechanical class -> deterministic zero-drop merge (a union), unless it is GATED
  - gated class      -> DEFER, verbatim (`classify.GATED`: `id-renumber-collision` since round 20)
  - semantic class   -> DEFER (leave the conflict for a human), unless force=True

`force=True` bypasses deferral and makes a naive best-effort auto-merge (take theirs) even on
semantic hunks. It exists ONLY to construct the unsafe counterfactual the verifier test needs;
the merge driver never calls it.

**THE RULE** (round 12, enforced by `resolve_totality`): *a mechanical resolver never discards a
line it does not understand — it preserves every input line, or it defers.* Stated over LINES, not
atoms, deliberately: the verifier can only see a lost line if that line parses as an atom, so an
atom-level invariant leaves plain prose free to vanish under a RESOLVED verdict (known-issue H8).
Every mechanical result is therefore checked against its own input before it ships, and a hunk
whose sides are not well-formed (an embedded conflict marker) is never claimed mechanically at all.

**What this module cannot check** (round 13): all of the above reads the conflict TEXT, and the
text is exactly what can lie — git's marker grammar is ordinary markdown, so a region can be cut in
the wrong place by content imitating a marker and every rule here still passes. The independent
answer lives in the merge INDEX, not in the text, so it lives outside this module: see
`stage_oracle.py`, which `merge_driver` runs before it accepts any mechanical result. Callers of
`resolve_file` that have no index (this file's own CLI, unit tests on synthetic blobs) get the
three text-side rules and nothing more.

The per-class merges themselves live in `resolvers.py` (split out in round 17); every public name
there is re-exported here. `resolvers.resolve_id_renumber` (renumber theirs' colliding entry, rewrite
its bare prose references) is DORMANT: its class is gated, so `resolve_hunk` never calls it outside
`force=True` and the file-level `_renumber_refusal` below never sees a renumber — see `classify.GATED` for why and for
what un-gating would take. Both are kept, with their tests, rather than deleted.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify import Hunk, ID_HEADING, classify_file, is_confident, MECHANICAL, GATED  # noqa: E402
from resolve_totality import (  # noqa: E402
    CannotPlace, embedded_marker, overproduced, unplaceable,
)
from resolvers import (  # noqa: E402,F401 — re-exported: `from resolve import ...` keeps working
    DEFER, HunkResult, MECH_RESOLVERS, RESOLVED, resolve_append_log,
    resolve_decision_entry_insertion, resolve_id_renumber, resolve_inventory,
    resolve_log_entry_insertion, split_entries,
)

# Every reason `resolve_hunk` can DEFER for, as a machine-readable code, in the order it decides
# them (m-L2). The `reason` string is prose for a human and may be reworded; the CODE is the thing
# callers and the pinned deferral histogram key on. Keying a bucket by substring-matching prose is
# how a genuine `would-invent` deferral would have quietly re-filed itself as UNCATEGORISED the
# first time someone improved the wording — the bucket exists precisely to make that impossible.
DEFER_CODES = ("gated", "not-confident", "malformed-hunk", "cannot-place",
               "would-drop", "would-invent", "semantic")


def _deferred(h: Hunk, reason: str, code: str) -> HunkResult:
    """Hand the region back to the human EXACTLY as it was read — same marker lines, same base
    section, same order.

    Deferral is the "we did not understand this" answer, so it must not edit anything. The previous
    form re-synthesised generic `<<<<<<< ours` / `=======` / `>>>>>>> theirs` labels and dropped the
    `||||||| base` section outright, which lost two things on every deferral: git's own side labels
    (`<<<<<<< HEAD` / the branch name — the only clue to which side is which) and every base line.
    Re-emitting verbatim is what makes DEFER a byte-exact round trip (`test_resolve_preservation`),
    and a round trip is the only form of "dropped nothing" that needs no atom inventory to check.
    """
    conflict = [h.open_marker, *h.ours]
    if h.base_marker is not None:
        conflict += [h.base_marker, *h.base]
    conflict += [h.sep_marker, *h.theirs, h.close_marker]
    assert code in DEFER_CODES, code
    return HunkResult(h.label, DEFER, conflict, reason=reason, code=code)


def resolve_hunk(h: Hunk, force: bool = False) -> HunkResult:
    if force:
        # Bypass every gate — used ONLY to construct the unsafe counterfactual for the verifier
        # test. `CannotPlace` is swallowed here on purpose: force's whole job is to produce the
        # lossy merge the safe path refuses, so it falls back to the naive take-theirs.
        if h.label in MECHANICAL:
            try:
                return MECH_RESOLVERS[h.label](h)
            except CannotPlace:
                pass
        return HunkResult(h.label, RESOLVED, h.theirs, reason="force: took theirs (UNSAFE)")
    if h.label in MECHANICAL:
        # Auto-resolve only when mechanical AND not gated AND the classifier is confident AND the
        # hunk is well-formed AND the result preserves every input line. The last two implement
        # `resolve_totality`'s rule — see that module for why it lives here rather than in the
        # verifier, and for the per-class licence the post-condition allows.
        if h.label in GATED:
            return _deferred(h, f"gated class ({h.label}) — withheld from auto-resolution "
                                f"(classify.GATED); a human resolves it", "gated")
        if not is_confident(h):
            return _deferred(h, f"classifier not confident ({h.label}, mixed structure)",
                             "not-confident")
        stray = embedded_marker(h)
        if stray is not None:
            return _deferred(h, f"structurally invalid hunk — embedded conflict marker {stray!r}",
                             "malformed-hunk")
        try:
            r = MECH_RESOLVERS[h.label](h)
        except CannotPlace as exc:
            return _deferred(h, f"resolver cannot place a line ({h.label}) — {exc}", "cannot-place")
        lost = unplaceable(h, r.label, r.lines, r.renumbered)
        if lost:
            # The backstop for every resolver, including ones not yet written: a result that does
            # not account for its own input is never shipped, whatever the resolver believed.
            return _deferred(h, f"resolver would DROP {len(lost)} line(s) ({r.label}): {lost[:2]}",
                             "would-drop")
        extra = overproduced(h, r.label, r.lines)
        if extra:
            # ...and the other direction, which no licence key can express: a line in the output
            # that the input never contained. `unplaceable` is evaluated under the class's licence,
            # so an error in that LICENCE is invisible to it; this one reads raw text and is
            # therefore the only layer here that does not share a specification with the licence
            # table. S-K1's padded duplicate is what it is for.
            return _deferred(h, f"resolver would INVENT {len(extra)} line(s) ({r.label}): "
                                f"{extra[:2]}", "would-invent")
        return r
    return _deferred(h, "semantic class — needs human", "semantic")


def resolve_file(conflict_text: str, force: bool = False,
                 labels: tuple[str, str, str] | None = None):
    """Return (file_status, reassembled_lines, [HunkResult]).
    file_status == RESOLVED iff every hunk resolved; else DEFER.

    `labels` is the `(ours, base, theirs)` marker-label triple `git merge-file` was run with; when
    given the parse is LABELLED (`conflict_parse`), which is what the byte path always passes.

    Clean (non-conflicted) segments are emitted VERBATIM — `classify.parse_conflict` hands them
    over as `list[str]` and they are extended straight onto the output. The previous
    `"\\n".join(...)` / `seg.splitlines()` round trip lost exactly one blank line per clean segment
    (`"a\\n".splitlines() == ["a"]`), and git's diff3 minimization leaves a blank immediately
    before `<<<<<<<` on essentially every real markdown living-doc conflict — so the drop fired on
    the common case and verified clean, because no atom kind is blank-line-shaped and
    `verify_atoms._digest` excludes blank lines by design. With `"\\n".join(...)` reassembly
    downstream, `parse_conflict` -> `resolve_file` is now an EXACT round trip on the clean regions.

    One rule is decided per FILE rather than per hunk (round 18, R1): see `_renumber_refusal`. A
    hunk `resolve_hunk` resolved can therefore come back deferred from here, never the reverse.
    That rule only ever acts on a RESOLVED renumber, which the gate on `id-renumber-collision`
    (round 20) makes unreachable in production; it runs, and is tested, with the gate lifted.
    """
    pf = classify_file(conflict_text, labels=labels)
    hunks = [seg for seg in pf.segments if isinstance(seg, Hunk)]
    results = [resolve_hunk(h, force=force) for h in hunks]
    if not force:
        refusal = _renumber_refusal(results, _assemble(pf.segments, results))
        if refusal is not None:
            results = [_deferred(h, refusal, "cannot-place")
                       if r.status == RESOLVED and r.renumbered else r
                       for h, r in zip(hunks, results)]
    all_resolved = all(r.status == RESOLVED for r in results)
    return (RESOLVED if all_resolved else DEFER), _assemble(pf.segments, results), results


def _assemble(segments: list, results: list) -> list[str]:
    """Clean segments verbatim, each hunk replaced by its result's lines, in file order."""
    out, it = [], iter(results)
    for seg in segments:
        out += next(it).lines if isinstance(seg, Hunk) else seg
    return out


def _renumber_refusal(results: list, out_lines: list[str]) -> str | None:
    """Why the file's ID renumbers must all DEFER, or None — the FILE-level half of
    `resolvers.resolve_id_renumber`, which sees one region and the other regions' INPUT only.

    * **More than one region renumbers.** Each draws its new number from the same input, so two
      same-letter regions pick the same "free" ID (R1: `L67 -> L69` and `L68 -> L69`, two
      `### L69:` headings staged as auto-resolved). Refusing is the narrow fix: the mechanical
      collision this class exists for is ONE concurrent insertion point, and a file with two is
      handed to the human whole rather than renumbered by a cleverer allocator. The rule does not
      look at letters: two regions renumbering different letters cannot coincide, and are refused
      anyway, because a simple rule is one that can be checked.
    * **Backstop: a renumbered ID is not exactly one heading of the assembled output.** Unreachable
      while the rule above and the resolver's own checks hold; it reads the OUTPUT, which neither
      of them does, so a future change to either cannot ship a duplicated ID.
    """
    renumbering = [r for r in results if r.status == RESOLVED and r.renumbered]
    if len(renumbering) > 1:
        return (f"{len(renumbering)} regions of this file renumber IDs, and each chose its new "
                f"number without seeing the others' choices")
    heads = [m.group(1) + m.group(2) for m in map(ID_HEADING.match, out_lines) if m]
    for r in renumbering:
        for new in sorted(r.renumbered.values()):
            if heads.count(new) != 1:
                return (f"the renumbered ID {new} is a heading {heads.count(new)} time(s) in the "
                        f"merged file, not exactly once")
    return None


def _main(argv: list[str]) -> int:
    force = "--force" in argv
    for path in [a for a in argv if not a.startswith("--")]:
        status, _lines, results = resolve_file(Path(path).read_text(encoding="utf-8"), force=force)
        print(f"\n{path}  -> FILE {status}{'  (force)' if force else ''}")
        for n, r in enumerate(results, 1):
            extra = f"  renumber={r.renumbered}" if r.renumbered else ""
            print(f"  hunk {n}: {r.status:8} {r.label}  {r.reason}{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
