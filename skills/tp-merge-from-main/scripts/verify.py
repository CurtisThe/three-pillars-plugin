#!/usr/bin/env python3
"""Independent zero-drop verifier for living-doc merges — VERDICT + CLI.

Knows NOTHING about the resolver. It inventories the *content atoms* present in ours ∪ theirs
and asserts each survives into the resolved output. The atom shapes, their signatures and the
scanner itself live in `verify_atoms.py` and are re-exported here unchanged — see that module
for the atom table, the corpus measurements and the accepted normalization residual.

CRITICAL property from the spike: this verifier is NECESSARY BUT NOT SUFFICIENT. It catches a
structural drop (it even caught a real human silent drop), but it MISSES a semantic mis-merge
whose atom survives while its meaning is wrong. Semantic safety must therefore be carried by
DEFERRAL in the resolver, with this verifier as a backstop for the mechanical classes only.

It is also NOT SUFFICIENT in a second, quieter direction: a file whose *shape* this module does
not recognize yields zero atoms, and "no atoms were lost" then means "nothing was examined". That
silent pass is why `verify()` returns a three-state `VerifyResult` rather than a bool — see
`VERIFIED` / `DROPS_DETECTED` / `UNVERIFIABLE` below. `UNVERIFIABLE` fires only when the caller
reports that a mechanical resolution was actually applied to the file (`mechanical_applied=True`)
AND zero atoms were parsed; a deferred or hand-resolved prose file legitimately has no atoms and
is not blocked.

With a `base` (the merge base), `verify()` is a three-way check: the atoms `excused_atoms` names
(a base atom one side retitled in place while the other left it alone, or one both sides lack)
are skipped, because the zero-drop rule would otherwise read a one-side retitle as a drop. The
changing side's NEW atoms are never excused, so they must still survive. `base=None` is the
two-way check, unchanged.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Re-exported so `import verify; verify.atoms(...)` / `verify.ENTRY` keep working for the
# existing consumers (`base_sync_cert`, `living_doc_carry`, the coverage test).
from verify_atoms import (  # noqa: E402,F401
    ATOM_KINDS,
    DECISION_ENTRY,
    ENTRY,
    LOG,
    ROW,
    _digest,
    _esc,
    _nonblank,
    _norm,
    atoms,
)
from verify_three_way import excused_atoms  # noqa: E402

VERIFIED = "VERIFIED"
DROPS_DETECTED = "DROPS_DETECTED"
UNVERIFIABLE = "UNVERIFIABLE"

UNVERIFIABLE_MESSAGE = (
    "UNVERIFIABLE — 0 atoms parsed from ours∪theirs ({ours}/{theirs} non-blank lines); "
    "this file's shape is unknown to the verifier."
)

@dataclass(frozen=True)
class VerifyResult:
    """The three-state verdict. `ok` is True for `VERIFIED` ONLY — both `DROPS_DETECTED` and
    `UNVERIFIABLE` are failures, so every existing fail-closed `if not r.ok` branch already
    covers the new verdict.

    A dataclass with no `__bool__` is truthy for EVERY instance, so a caller writing the
    natural-looking `if not result:` would have absorbed `UNVERIFIABLE` (and `DROPS_DETECTED`)
    into the pass path. `__bool__` is therefore defined and returns `.ok`, so the bool-shaped
    call site fails closed exactly like the `.ok` one instead of silently passing.
    """

    verdict: str
    dropped: list = field(default_factory=list)
    pre_atoms: int = 0
    post_atoms: int = 0
    ours_lines: int = 0
    theirs_lines: int = 0
    excused: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.verdict == VERIFIED

    def __bool__(self) -> bool:
        return self.ok


def verify(ours: str, theirs: str, resolved: str, *, base: str | None,
           mechanical_applied: bool) -> VerifyResult:
    """Inventory ours∪theirs and assert each atom survives into `resolved`.

    `base` and `mechanical_applied` are **keyword-only with no default**: an unmigrated positional
    call raises `TypeError` at the call site rather than silently choosing a verdict policy (the
    same fail-loud device `resolve_conflict_bytes` uses). `base=None` is the two-way check; a text
    is the merge base, and `excused_atoms(base, ours, theirs)` is then skipped (listed, in `pre`
    order, in `VerifyResult.excused`). Pass the per-file fact "the resolver actually applied a
    mechanical resolution to this file" — an OR across the file's hunks.

    `UNVERIFIABLE` keys on the atoms of ours and theirs themselves, not on what is left after the
    excuse. `pre` stays an insertion-ordered dict, never a set, so `dropped` keeps document order
    (ours' atoms first, then theirs-only ones).
    """
    union = {**atoms(ours), **atoms(theirs)}
    skip = excused_atoms(base, ours, theirs) if base is not None else set()
    pre = {k: v for k, v in union.items() if k not in skip}
    post = atoms(resolved)
    dropped = [k for k in pre if k not in post]
    if mechanical_applied and not union:
        verdict = UNVERIFIABLE
    elif dropped:
        verdict = DROPS_DETECTED
    else:
        verdict = VERIFIED
    return VerifyResult(verdict=verdict, dropped=dropped, pre_atoms=len(pre),
                        post_atoms=len(post), ours_lines=_nonblank(ours),
                        theirs_lines=_nonblank(theirs), excused=[k for k in union if k in skip])


def verify_paths(ours_p, theirs_p, resolved_p, *, mechanical_applied: bool,
                 base_p=None) -> VerifyResult:
    """`verify` over files. `base_p` is the merge base's path: given, the check is three-way;
    `None` is the two-way check. An unreadable `base_p` raises like the other three paths do."""
    return verify(Path(ours_p).read_text(encoding="utf-8"),
                  Path(theirs_p).read_text(encoding="utf-8"),
                  Path(resolved_p).read_text(encoding="utf-8"),
                  base=None if base_p is None else Path(base_p).read_text(encoding="utf-8"),
                  mechanical_applied=mechanical_applied)


USAGE_ERROR_EXIT = 3


class _Parser(argparse.ArgumentParser):
    """argparse exits **2** on a usage error, which collided head-on with this CLI's documented
    `2 = UNVERIFIABLE`. A caller reading the exit status could not tell "the merge is unsafe" from
    "you typed the flag wrong". Usage errors are remapped to `3`, which is also where I/O errors
    land — see `_main`."""

    def error(self, message: str):                       # pragma: no cover - argparse plumbing
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(USAGE_ERROR_EXIT)


def _main(argv: list[str]) -> int:
    ap = _Parser(
        prog="verify.py",
        description="Zero-drop verifier. Exit 0 = VERIFIED, 1 = DROPS DETECTED, "
                    "2 = UNVERIFIABLE, 3 = usage or I/O error.")
    ap.add_argument("ours")
    ap.add_argument("theirs")
    ap.add_argument("resolved")
    ap.add_argument("--mechanical-applied", action="store_true",
                    help="the resolver actually applied a mechanical resolution to this file; "
                         "zero parsed atoms is then UNVERIFIABLE, not a pass")
    ap.add_argument("--base", metavar="PATH",
                    help="the merge base; a base atom one side retitled in place is then excused "
                         "(three-way check). Omitted: the two-way check")
    args = ap.parse_args(argv)
    try:
        r = verify_paths(args.ours, args.theirs, args.resolved,
                         mechanical_applied=args.mechanical_applied, base_p=args.base)
    except (OSError, UnicodeDecodeError) as e:
        # An unreadable/undecodable input is NOT "drops detected" (1) and NOT "unverifiable" (2) —
        # the verifier never ran. Distinct status so a caller cannot conflate the two.
        print(f"verify.py: cannot read input: {e}", file=sys.stderr)
        return USAGE_ERROR_EXIT
    if r.verdict == UNVERIFIABLE:
        print(UNVERIFIABLE_MESSAGE.format(ours=r.ours_lines, theirs=r.theirs_lines))
        return 2
    print("ZERO-DROP" if r.ok else f"DROPS DETECTED ({len(r.dropped)}):")
    for kind, sig in r.dropped:
        print(f"   dropped {kind}: {sig[:70]}")
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
