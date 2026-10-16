#!/usr/bin/env python3
"""review_time.py — implementation wall vs review wall for one design/PR.

design: review-convergence (Task 9.3, detailed-design-pr-loop §D8)

`summary(design_dir, proof_root, pr)` sums the implementation wall from
`<design_dir>/dispatch-telemetry.ndjson` (numeric `wall_s` per row with a non-null
`phase`) and the review wall from `<proof_root>/rounds/<pr>/<ordinal>/` (a round's
manifest `started_at` to the newest mtime in its `tail/`), returning
`{"implementation_s", "review_s", "ratio"}`. The CLI prints one line.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
from pathlib import Path

NDJSON_NAME = "dispatch-telemetry.ndjson"
MANIFEST_NAME = "angles.json"
ROUNDS_DIR = "rounds"
ORDINAL_RE = re.compile(r"^r\d+(\.1)?$")


def _parse_ts(raw):
    """Manifest `started_at` as an aware datetime; None when absent or unparseable."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def _implementation_s(design_dir) -> float:
    """Sum numeric `wall_s` over rows with a non-null `phase`; a missing file, bad
    lines and null/non-numeric `wall_s` rows (design/audit slots, `tp-worker`) add 0.
    """
    path = Path(design_dir) / NDJSON_NAME
    if not path.is_file():
        return 0.0
    total = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except (ValueError, TypeError):  # blank or unparseable line
            continue
        if not isinstance(row, dict) or row.get("phase") is None:
            continue
        wall = row.get("wall_s")
        if isinstance(wall, (int, float)) and not isinstance(wall, bool):
            total += float(wall)
    return total


def _round_wall(rdir: Path):
    """Round wall: manifest `started_at` → newest mtime of its `tail/` files; None when
    the manifest or `started_at` is unreadable, or `tail/` is empty. A `tail` dir's own
    mtime is never used — a later read bumps it."""
    tail = rdir / "tail"
    files = [e for e in tail.iterdir() if e.is_file()] if tail.is_dir() else []
    if not files:
        return None
    try:
        manifest = json.loads((rdir / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    started = _parse_ts(manifest.get("started_at")) if isinstance(manifest, dict) else None
    if started is None:
        return None
    return max(0.0, max(e.stat().st_mtime for e in files) - started.timestamp())


def _review_s(pr, proof_root) -> float:
    """Sum the per-round walls; a round that cannot be measured is skipped."""
    if proof_root is None:
        return 0.0
    rounds = Path(proof_root) / ROUNDS_DIR / str(pr)
    if not rounds.is_dir():
        return 0.0
    return sum(_round_wall(rdir) or 0.0 for rdir in sorted(rounds.iterdir())
               if rdir.is_dir() and ORDINAL_RE.match(rdir.name))


def summary(design_dir, proof_root, pr) -> dict:
    """Seconds to 1 dp, ratio to 2 dp; `ratio` is None with no implementation wall."""
    impl = round(_implementation_s(design_dir), 1)
    review = round(_review_s(pr, proof_root), 1)
    return {"implementation_s": impl, "review_s": review,
            "ratio": round(review / impl, 2) if impl > 0 else None}


def fmt_duration(seconds) -> str:
    """`"<H>h <MM>m"` — 3725 → "1h 02m"."""
    total = int(max(0.0, float(seconds)))
    return f"{total // 3600}h {total % 3600 // 60:02d}m"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--design-dir", required=True)
    ap.add_argument("--proof-root")
    ap.add_argument("--pr")
    ap.add_argument("--phase", choices=("impl", "review", "all"), default="all")
    args = ap.parse_args(argv)
    impl, review, ratio = summary(args.design_dir, args.proof_root, args.pr).values()
    if args.phase == "impl":
        print(f"Implementation time: {fmt_duration(impl)} ({impl} s)")
    elif args.phase == "review":
        print(f"Review time: {fmt_duration(review)} ({review} s), "
              f"{'n/a' if ratio is None else f'{ratio}x'} implementation")
    else:
        print(f"Implementation {fmt_duration(impl)}, review {fmt_duration(review)}, "
              f"ratio {'n/a' if ratio is None else ratio}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
