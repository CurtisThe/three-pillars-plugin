"""Owed ledger for ready pings: a skipped (conflicting) ping stays owed.

A ``ready`` ping skipped because the PR conflicts leaves an ``owed`` record in
the same per-slug ndjson ledger ``ready_ping`` writes. A later ``ready`` ping
that is actually sent clears it. Stdlib-only and imports nothing from
``ready_ping`` (``ready_ping`` imports this module). Every public function is
fail-open: nothing here raises to its caller.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

OWED = "owed"
READY = "ready"
STOP = "stop"


def _records(ledger):
    """Every JSON-object line of the ledger; ``[]`` when missing or unreadable."""
    path = Path(ledger)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def record_owed(slug, pr, head, ledger):
    """Append an ``owed`` record for ``head`` unless its key is already present.

    Returns True when a record was written, False otherwise (duplicate, or the
    ledger cannot be written). Never raises.
    """
    try:
        key = f"owed:{head}"
        if any(rec.get("key") == key for rec in _records(ledger)):
            return False
        path = Path(ledger)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "key": key, "kind": OWED, "slug": slug, "pr": pr, "head": head,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        return True
    except Exception:
        return False


def owed_pending(slug, ledger=None):
    """True when the last ``owed``/``ready`` record for ``slug`` is ``owed``.

    The default ledger is ``ready_ping.ledger_path(slug)``, imported lazily.
    Never raises; an unreadable ledger reads as not pending.
    """
    try:
        if ledger is None:
            from ready_ping import ledger_path
            ledger = ledger_path(slug)
        last = None
        for rec in _records(ledger):
            if rec.get("kind") in (OWED, READY):
                last = rec.get("kind")
        return last == OWED
    except Exception:
        return False


def converged_before(ledger):
    """True when the last ``ready``/``owed``/``stop`` record is ``ready`` or ``owed``.

    A later ``stop`` record (the loop escalated or demoted the PR) means it is
    no longer converged, so a later base-sync must not re-announce it ready.
    Never raises; an unreadable ledger reads as not converged.
    """
    try:
        last = None
        for rec in _records(ledger):
            if rec.get("kind") in (OWED, READY, STOP):
                last = rec.get("kind")
        return last in (OWED, READY)
    except Exception:
        return False
