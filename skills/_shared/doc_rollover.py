"""doc_rollover.py — the writer-side soft-cap rollover for a living doc.

A thin wrapper over `history_rollover.roll`: it rolls the oldest `## History`
entries of a living doc into its archive, one entry at a time, until the doc is
at or under its `file_size_guard.char_caps` soft cap. It never parses History
itself, and it reaches `keep=0` when every entry is needed. A doc that is still
over the soft cap (no History, or nothing left to roll) prints one line,

  CONDENSE-NEEDED <rel> chars=N soft=M → /tp-docs-update --diet

so the writer (or the operator) knows a condense pass is owed. This is the
"next framework writer rolls an over-cap doc over" half of the consumer-safe
posture (design D6/D8): an over-cap doc is warned at commit time, never blocked.

Always exits 0 (fail-open for writers); an under-cap doc is a no-op. Stdlib only.

CLI:
  doc_rollover.py --doc <rel> [--repo-root R]
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import file_size_guard
import history_rollover

_PROBE_KEEP = sys.maxsize  # a no-op roll: its RollResult reports the live entry count


@dataclass
class RollToCapResult:
    """`moved` entries rolled, the doc's `chars_before`/`chars_after`, its
    `soft` cap, and whether a condense pass is still `condense_needed`."""
    moved: int
    chars_before: int
    chars_after: int
    soft: int
    condense_needed: bool


def _chars(path: Path) -> int:
    return file_size_guard.measure(path)[1]


def roll_to_cap(repo_root, rel: str) -> RollToCapResult:
    """Roll `rel`'s oldest History entries into its archive until it is at or
    under its soft cap, printing CONDENSE-NEEDED if it is still over. Rolls only
    through `history_rollover.roll`. `KeyError` if `rel` has no archive pair."""
    path = Path(repo_root) / rel
    soft = file_size_guard.char_caps(rel, False)[0]
    if not path.is_file():
        return RollToCapResult(0, 0, 0, soft, False)
    chars = before = _chars(path)
    moved = 0
    probe = history_rollover.roll(repo_root, rel, keep=_PROBE_KEEP) if chars > soft else None
    live = probe.live_count if probe is not None else 0
    while chars > soft and live > 0:
        result = history_rollover.roll(repo_root, rel, keep=live - 1)
        if result.moved == 0:  # a refusal (e.g. the verifier): stop, never spin
            break
        moved += result.moved
        live = result.live_count
        chars = _chars(path)
    over = chars > soft
    if over:
        print(f"CONDENSE-NEEDED {rel} chars={chars} soft={soft} → /tp-docs-update --diet")
    return RollToCapResult(moved, before, chars, soft, over)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Roll a living doc's oldest History into its archive until under its soft cap.",
    )
    parser.add_argument("--doc", required=True, metavar="REL",
                        help="repo-relative living doc path")
    parser.add_argument("--repo-root", default=".", metavar="R",
                        help="repo root (default: .)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")
    try:
        result = roll_to_cap(args.repo_root, args.doc)
    except KeyError:
        print(f"doc_rollover: {args.doc} has no archive pair; nothing to roll", file=sys.stderr)
    except Exception as exc:  # fail-open: a writer's own work must never fail on this
        print(f"doc_rollover: skipped {args.doc} — {exc}", file=sys.stderr)
    else:
        if result.moved:
            print(f"doc_rollover: rolled {result.moved} entries from {args.doc} "
                  f"(chars {result.chars_before} → {result.chars_after}, soft {result.soft})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
