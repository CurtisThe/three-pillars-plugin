"""Certifier-at-most-once: per-slot markers, the follow-up ledger, and the CLI.

design: review-convergence (detailed-design-phase-check.md §F2, Task 12.2)
design: certifier-lean 1.2 (Behaviors 3, 5)
design: light-run-ceremony-diet 1.2 (B1)

Each certifying slot runs its full pass at most once per design: ``should_run``
is true only while that slot's marker is absent; ``mark`` writes it, so a
re-check after the patch reuses attempt 1's certifications instead of spending
another certifier run. Slot 8 (Step 2b) keeps the original marker name and is
the default everywhere. Slot 4 (the phase-check pass) has its own marker and
never runs for a light design. Separately each claim key buys at most one
follow-up run: ``followup`` records the key and is true only the first time.

A light design reaches Slot 8 only when it is a safety gate: ``design.md``
declares ``safety-gate: true`` or the diff touches a ``safety_gate.GATE_PATHS``
path. Otherwise ``should-run --light`` skips with "not a safety gate". An
unreadable diff counts as a gate (err toward certifying). Without ``--light``
nothing changes.

CLI:
    cert_once.py should-run --design-dir D [--slot N] [--light]
                            [--base REF [--head REF] [--repo DIR]]
                                                exit 0 run / 1 skip / 2 --light
                                                at slot 8 needs --base on an
                                                undeclared design
    cert_once.py mark --design-dir D [--attempt N] [--slot N]
                                                exit 0, or 2 when D is missing
    cert_once.py followup --design-dir D --claim KEY
                                                exit 0 first / 1 used / 2 no dir
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import safety_gate  # noqa: E402

MARKER_NAME = "certify-once.json"
SLOT = 8
MARKERS = {8: MARKER_NAME, 4: "certify-once-slot4.json"}
FOLLOWUP_NAME = "certify-retries.json"


def marker_path(design_dir, slot: int = SLOT) -> Path:
    """The marker file for a certifying slot inside a design directory."""
    return Path(design_dir) / MARKERS[slot]


def skip_reason(design_dir, slot: int = SLOT, light: bool = False, changed=None):
    """``"not a safety gate"`` when a light design skips Slot 8, else None.

    ``changed`` is the diff's path list; None (unknown / unreadable) counts as
    touching a gate, so the certifier runs.
    """
    if light and slot == SLOT:
        if not (safety_gate.declares_safety_gate(design_dir)
                or safety_gate.touches_gate(changed)):
            return "not a safety gate"
    return None


def should_run(design_dir, slot: int = SLOT, light: bool = False, changed=None) -> bool:
    """True while no certification marker exists for this slot.

    A light design never runs the Slot 4 full pass, marker or not. At Slot 8
    it runs only when it is a safety gate (see ``skip_reason``).
    """
    if light and slot == 4:
        return False
    if skip_reason(design_dir, slot, light, changed) is not None:
        return False
    return not marker_path(design_dir, slot).exists()


def mark(design_dir, attempt: int = 1, slot: int = SLOT) -> Path:
    """Write the slot's once-marker recording slot, attempt and timestamp."""
    path = marker_path(design_dir, slot)
    payload = {
        "slot": int(slot),
        "attempt": int(attempt),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


def followed(design_dir) -> set:
    """The claim keys that already had their one follow-up run."""
    path = Path(design_dir) / FOLLOWUP_NAME
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def followup(design_dir, key: str) -> bool:
    """Record a claim key in the ledger; True only the first time it is seen."""
    path = Path(design_dir) / FOLLOWUP_NAME
    seen = followed(design_dir)
    if key in seen:
        return False
    seen.add(key)
    path.write_text(json.dumps(sorted(seen)) + "\n", encoding="utf-8")
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="cert_once.py")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("should-run", help="exit 0 when the certifier should run, 1 when skipped")
    run.add_argument("--design-dir", required=True, help="design directory holding the marker")
    run.add_argument("--slot", type=int, choices=sorted(MARKERS), default=SLOT,
                     help="certifying slot (default 8)")
    run.add_argument("--light", action="store_true", help="the design's weight is light")
    run.add_argument("--base", help="diff base ref (needed with --light at slot 8)")
    run.add_argument("--head", default="HEAD", help="diff head ref (default HEAD)")
    run.add_argument("--repo", default=".", help="repo to diff (default .)")
    mk = sub.add_parser("mark", help="record that the certifier ran for this design")
    mk.add_argument("--design-dir", required=True, help="design directory holding the marker")
    mk.add_argument("--attempt", type=int, default=1, help="attempt number (default 1)")
    mk.add_argument("--slot", type=int, choices=sorted(MARKERS), default=SLOT,
                    help="certifying slot (default 8)")
    fu = sub.add_parser("followup", help="claim one follow-up run for a claim key")
    fu.add_argument("--design-dir", required=True, help="design directory holding the ledger")
    fu.add_argument("--claim", required=True, help="claim key, e.g. file.claims.json#c1")
    args = parser.parse_args(argv)

    if args.command == "should-run":
        changed = None
        if (args.light and args.slot == SLOT
                and not safety_gate.declares_safety_gate(args.design_dir)):
            if not args.base:
                print("should-run: error: --light at slot 8 needs --base", file=sys.stderr)
                return 2
            changed = safety_gate.changed_paths(args.repo, args.base, args.head)
        reason = skip_reason(args.design_dir, args.slot, args.light, changed)
        if reason:
            print(f"should-run: skip ({reason})")
            return 1
        verdict = should_run(args.design_dir, args.slot, args.light, changed)
        print(f"should-run: {'run' if verdict else 'skip'}")
        return 0 if verdict else 1

    if not Path(args.design_dir).is_dir():
        print(f"{args.command}: error: design dir not found: {args.design_dir}", file=sys.stderr)
        return 2

    if args.command == "followup":
        granted = followup(args.design_dir, args.claim)
        print(f"followup: {'granted' if granted else 'already used'} for {args.claim}")
        return 0 if granted else 1

    mark(args.design_dir, args.attempt, args.slot)
    print(f"mark: marked attempt {args.attempt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
