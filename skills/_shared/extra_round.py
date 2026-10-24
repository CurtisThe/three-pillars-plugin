"""The pinned extra-round question for a needs-work audit slot.

design: escalation-threshold. The one-grant cap is ``finalizer-ledger.json``'s
at-most-once stop key over this pinned text, never a parsed ``decisions.md``
heading. The question is digit-free because ``normalize_detail`` strips digits.

Usage: python3 extra_round.py stop --slug S --slot SLOT [--out FILE]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import finalizer  # noqa: E402

SLOTS = finalizer.AUDIT_SLOTS
ALIASES = {"design-audit": "design", "plan-audit": "plan", "impl-audit": "implementation"}


def _slot(s) -> str:
    """Canonical slot for ``s`` (alias or bare), else ``ValueError``."""
    slot = ALIASES.get(s, s)
    if slot not in SLOTS:
        raise ValueError(f"unknown audit slot {s!r}; expected one of {SLOTS} or {tuple(ALIASES)}")
    return slot


def question(slot) -> str:
    slot = _slot(slot)
    return (f"The {slot} audit is still needs-work after its patch, re-check and finalizer "
            "round. Grant one more retry-with-advice cycle plus one re-check for this slot?")


def stop(slug, slot) -> dict:
    slot = _slot(slot)
    return {
        "source": "question",
        "signal": "decision",
        "target": slug,
        "detail": {
            "question": question(slot),
            "options": [
                {"name": "grant-one-round",
                 "description": "one more retry-with-advice cycle (a patch, or a re-run of the "
                                "flagged phases for implementation) and one re-check, then the "
                                "audit must PASS"},
                {"name": "stop-here",
                 "description": "escalate to the operator with the findings"},
            ],
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="extra_round")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("stop")
    p.add_argument("--slug", required=True)
    p.add_argument("--slot", required=True)
    p.add_argument("--out")
    args = ap.parse_args(argv)
    try:
        text = json.dumps(stop(args.slug, args.slot))
    except ValueError as exc:
        print(f"extra_round: {exc}", file=sys.stderr)
        return 2
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
