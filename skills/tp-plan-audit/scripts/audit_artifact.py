#!/usr/bin/env python3
"""
Plan-audit pass-artifact contract — the on-disk staleness record.

A clean `audit_plan.py` run writes `.plan-audit-pass.json` into the design dir;
downstream tooling (`tp-phase-implement`) verifies it WITHOUT importing the
auditor. The artifact carries the audited `plan.md` digest so any later edit to
`plan.md` is detectable as stale — except a task's `**Status**:` line, which
`/tp-phase-implement` writes after the audit (M46; see `plan_digest`).

Artifact shape (`<design-dir>/.plan-audit-pass.json`):
  {
    "verdict": "pass",
    "plan_digest": "<sha256 hex of plan.md bytes, Status and blank lines dropped>",
    "plan_audit_mode": "light" | "standard" | "spike" | "council",
    "warn_count": <int, number of WARN findings in the passing run>,
    "warnings": [ ...at most 20 WARN messages... ],
    "audited_at": "<ISO-8601 UTC timestamp>"
  }

`warn_count`/`warnings` are optional on read: an artifact written before they
existed (no such keys) reads as `warn_count: 0`. A WARN-only run (exit 0) still
records a CURRENT artifact (the gate is `plan_digest` only) carrying the WARN
count, so `--check` can report it.

`artifact_status(design_dir)` returns one of:
  ("ok", reason)      — artifact present and digest matches current plan.md;
                        reason is "<N> WARN(s)"
  ("absent", reason)  — no artifact (or unreadable / no plan.md)
  ("stale", reason)   — artifact present but plan.md changed since it was written

CLI: `python3 audit_artifact.py --check <design-dir>`
  exit 0 on ("ok", _) printing the WARN count and the first 5 warnings; else
  exit 1 printing a /tp-plan-audit remedy with the concrete reason (absent
  vs stale).
CLI: `python3 audit_artifact.py --write <design-dir> --mode <mode>`
  records a pass through `write_pass_artifact` — `/tp-run-full-design` Slot 6
  runs it after a council pass (mode `council`). Exit 0 written; 1 no plan.md.

Stdlib only (hashlib/json/pathlib/datetime); the digest hashes RAW BYTES so it
is locale-independent and stable across the staleness contract.
"""

import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

ARTIFACT_NAME = ".plan-audit-pass.json"


STATUS_PREFIX = b"**Status**:"


def _drop_status_lines(data):
    """plan.md bytes without its task ``**Status**:`` lines or blank lines (M46).

    A phase marks its tasks done by adding or rewriting a ``**Status**:`` line
    at column 0 (``/tp-phase-implement`` step 8, ``local-dispatch.md`` §2), after
    the audit, often with a blank line before or after it. The audited snapshot
    cannot tell which blank lines a phase added, so every blank (whitespace-only)
    line is dropped too: blank lines are layout, not plan content. Every other
    byte is kept, so any other edit — including an indented or mid-line
    ``**Status**:``, or whitespace inside a line — still changes the digest.
    """
    return b"\n".join(
        line for line in data.split(b"\n")
        if line.strip() and not line.startswith(STATUS_PREFIX)
    )


def raw_plan_digest(plan_path):
    """sha256 hex of plan.md's unmodified bytes — the pre-M46 digest."""
    return hashlib.sha256(Path(plan_path).read_bytes()).hexdigest()


def plan_digest(plan_path):
    """sha256 hex digest of plan.md's RAW BYTES, Status and blank lines dropped.

    Hashes ``read_bytes()`` (never ``read_text()``) so the digest is
    locale/encoding-independent. ``_drop_status_lines`` removes only the task
    ``**Status**:`` lines a phase writes and blank lines; any other change to plan.md
    yields a different digest, which is what the staleness contract needs.
    """
    return hashlib.sha256(_drop_status_lines(Path(plan_path).read_bytes())).hexdigest()


def write_pass_artifact(design_dir, mode, warnings=None):
    """Write `<design-dir>/.plan-audit-pass.json` recording a passing audit.

    Records the current plan.md digest, the audit mode, and a UTC timestamp.
    ``warnings`` (the passing run's WARN messages) adds ``warn_count`` (the
    full count) and ``warnings`` (at most 20, for a readable artifact); a clean
    run passes ``None`` (both record 0 / empty). Returns the written record dict.
    """
    warnings = list(warnings or [])
    design_dir = Path(design_dir)
    record = {
        "verdict": "pass",
        "plan_digest": plan_digest(design_dir / "plan.md"),
        "plan_audit_mode": mode,
        "warn_count": len(warnings),
        "warnings": warnings[:20],
        "audited_at": datetime.now(timezone.utc).isoformat(),
    }
    (design_dir / ARTIFACT_NAME).write_text(json.dumps(record, indent=2) + "\n")
    return record


def read_pass_artifact(design_dir):
    """Return the parsed artifact dict, or None if absent/unreadable/malformed.

    Non-dict JSON (a bare list/number/string) is treated as malformed → None,
    so callers never crash on ``.get`` (fail-closed: a non-dict artifact reads
    as absent rather than raising).
    """
    path = Path(design_dir) / ARTIFACT_NAME
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def artifact_status(design_dir):
    """Return ("ok"|"absent"|"stale", reason) for the design dir.

    Compares the stored ``plan_digest`` to the current plan.md digest:
      - no artifact / no plan.md / unreadable      → ("absent", …)
      - artifact verdict is not "pass"             → ("absent", …)
      - stored digest != current plan.md digest    → ("stale", …)
      - stored digest == current plan.md digest    → ("ok", …)

    The ``verdict`` field is load-bearing, not decorative: "ok" requires BOTH a
    "pass" verdict AND a digest match, so a (hand-forged or future non-pass)
    record never satisfies the gate on digest alone.
    """
    design_dir = Path(design_dir)
    record = read_pass_artifact(design_dir)
    if record is None:
        return ("absent", "no .plan-audit-pass.json artifact")
    if record.get("verdict") != "pass":
        return ("absent", "artifact verdict is not 'pass'")
    stored = record.get("plan_digest")
    try:
        # A pre-M46 artifact stores the raw digest of the audited plan.md. It
        # stays current while plan.md is byte-identical; after an edit it is
        # current only if the new normalized digest happens to equal it.
        current = (plan_digest(design_dir / "plan.md"),
                   raw_plan_digest(design_dir / "plan.md"))
    except OSError:
        return ("absent", "plan.md not found")
    if stored not in current:
        return (
            "stale",
            "plan.md changed since the audit (digest mismatch)",
        )
    # Old artifacts (pre-warn_count) read as a 0-WARN pass; the gate binds on
    # plan_digest only, so the WARN count is informational, not load-bearing.
    warn_count = record.get("warn_count", 0)
    return ("ok", f"{warn_count} WARN(s)")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 2 and argv[0] == "--check":
        status, reason = artifact_status(argv[1])
        if status == "ok":
            print(f"plan-audit: current pass ({reason})")
            for w in (read_pass_artifact(argv[1]) or {}).get("warnings", [])[:5]:
                print(f"  {w}")
            return 0
        design_name = Path(argv[1]).name
        print(
            f"Refuse: no current passing plan-audit — run "
            f"/tp-plan-audit {design_name} ({status}: {reason})"
        )
        return 1
    if len(argv) == 4 and argv[0] == "--write" and argv[2] == "--mode" and argv[3]:
        if not (Path(argv[1]) / "plan.md").is_file():
            print(f"plan-audit: no plan.md in {argv[1]}; nothing written", file=sys.stderr)
            return 1
        record = write_pass_artifact(argv[1], argv[3])
        print(f"plan-audit: pass recorded ({argv[3]}, {record['plan_digest'][:12]})")
        return 0
    print(f"Usage: {sys.argv[0]} --check <design-dir> | "
          f"--write <design-dir> --mode <mode>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
