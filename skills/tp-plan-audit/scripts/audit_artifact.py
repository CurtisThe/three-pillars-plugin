#!/usr/bin/env python3
"""
Plan-audit pass-artifact contract — the on-disk staleness record.

A clean `audit_plan.py` run writes `.plan-audit-pass.json` into the design dir;
downstream tooling (`tp-phase-implement`) verifies it WITHOUT importing the
auditor. The artifact carries the audited `plan.md` digest so any later edit to
`plan.md` is detectable as stale.

Artifact shape (`<design-dir>/.plan-audit-pass.json`):
  {
    "verdict": "pass",
    "plan_digest": "<sha256 hex of plan.md bytes>",
    "plan_audit_mode": "light",
    "audited_at": "<ISO-8601 UTC timestamp>"
  }

`artifact_status(design_dir)` returns one of:
  ("ok", reason)      — artifact present and digest matches current plan.md
  ("absent", reason)  — no artifact (or unreadable / no plan.md)
  ("stale", reason)   — artifact present but plan.md changed since it was written

CLI: `python3 audit_artifact.py --check <design-dir>`
  exit 0 on ("ok", _); else exit 1 printing a /tp-plan-audit remedy with the
  concrete reason (absent vs stale).

Stdlib only (hashlib/json/pathlib/datetime); the digest hashes RAW BYTES so it
is locale-independent and stable across the staleness contract.
"""

import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

ARTIFACT_NAME = ".plan-audit-pass.json"


def plan_digest(plan_path):
    """sha256 hex digest of plan.md's RAW BYTES.

    Hashes ``read_bytes()`` (never ``read_text()``) so the digest is
    locale/encoding-independent — any byte-level change to plan.md yields a
    different digest, which is exactly what the staleness contract needs.
    """
    return hashlib.sha256(Path(plan_path).read_bytes()).hexdigest()


def write_pass_artifact(design_dir, mode):
    """Write `<design-dir>/.plan-audit-pass.json` recording a clean audit.

    Records the current plan.md digest, the audit mode, and a UTC timestamp.
    Returns the written record dict.
    """
    design_dir = Path(design_dir)
    record = {
        "verdict": "pass",
        "plan_digest": plan_digest(design_dir / "plan.md"),
        "plan_audit_mode": mode,
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
        current = plan_digest(design_dir / "plan.md")
    except OSError:
        return ("absent", "plan.md not found")
    if stored != current:
        return (
            "stale",
            "plan.md changed since the audit (digest mismatch)",
        )
    return ("ok", "audit artifact is current for plan.md")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 2 and argv[0] == "--check":
        status, reason = artifact_status(argv[1])
        if status == "ok":
            return 0
        design_name = Path(argv[1]).name
        print(
            f"Refuse: no current passing plan-audit — run "
            f"/tp-plan-audit {design_name} ({status}: {reason})"
        )
        return 1
    print(f"Usage: {sys.argv[0]} --check <design-dir>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
