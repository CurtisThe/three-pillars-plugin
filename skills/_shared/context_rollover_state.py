#!/usr/bin/env python3
"""context_rollover_state.py - the once-per-crossing ledger of context rollovers.

design: strata-spend-leaks (Task 3.2). A rollover (save -> `/clear` -> restore) must
fire at most once per session id, so the driver needs durable memory of which sessions
already had one: a session id that is in the ledger is refused, whether its rollover
finished or aborted. After a restore the session id is new, so the next crossing is
claimable again.

Two entry points, one JSON object on disk (in the run:
`<worktree>/.three-pillars/run/context-rollover.json`, a gitignored dir):
- `claim(path, session, now)` - True only when this is the first claim for
  `session`, writing `{session: {"state": "claimed", "at": now}}` atomically
  (temp file + `os.replace`);
- `finish(path, session, outcome)` - records the claim as `done` or `aborted`, so the
  entry outlives the rollover instead of being deleted.

The ledger is the only thing standing between a retry and a **second** `/clear` on a
session that already rolled over, so an unreadable, half-written or otherwise corrupt
ledger refuses every claim (False) rather than treating it as empty. Stdlib only.
"""
from __future__ import annotations

import json
import os
import tempfile
import time

__all__ = ["CLAIMED", "OUTCOMES", "claim", "finish", "entry"]

CLAIMED = "claimed"
OUTCOMES = ("done", "aborted")


def _read(path) -> "dict | None":
    """The ledger object at `path`, or None when it cannot be trusted.

    A missing file is a genuinely empty ledger (`{}`). Anything else that fails -
    an unreadable file, a directory, a half-written or garbage file, a JSON value
    that is not an object - is None: refusing is the only safe answer, because a
    fresh claim on a ledger we cannot read could send a second `/clear`.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        return {}
    except OSError:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _write(path, data: "dict") -> bool:
    """Write the ledger atomically: a temp file in the same directory, then
    `os.replace`, so a reader (or a crash) never sees a half-written ledger.

    False when the write fails - the caller then refuses, never claims.
    """
    tmp = None
    try:
        parent = os.path.dirname(str(path)) or "."
        os.makedirs(parent, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".context-rollover-", dir=parent)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
        tmp = None
        return True
    except OSError:
        return False
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def claim(path, session: str, now: "float | None" = None) -> bool:
    """Claim the one rollover for `session`. True only for the first claim.

    False when `session` is already in the ledger (claimed, done or aborted - a
    finished or aborted rollover is never re-fired), and False when the ledger
    cannot be read or the claim could not be written.
    """
    if not session:
        return False
    data = _read(path)
    if data is None or session in data:
        return False
    data[session] = {"state": CLAIMED, "at": time.time() if now is None else now}
    return _write(path, data)


def entry(path, session: str) -> "dict | None":
    """`session`'s ledger entry (`{"state": ..., "at": ...}`), or None when the ledger
    cannot be read or holds no entry for it. Read-only: never claims."""
    data = _read(path)
    found = data.get(session) if data is not None else None
    return found if isinstance(found, dict) else None


def finish(path, session: str, outcome: str) -> bool:
    """Record how a claimed rollover ended: `done` or `aborted`.

    False when `outcome` is not one of those, when the ledger cannot be read, or
    when `session` has no claim to close. The entry stays in the ledger either way -
    an aborted rollover is a human call, not an automatic second attempt.
    """
    if outcome not in OUTCOMES:
        return False
    data = _read(path)
    if data is None or session not in data:
        return False
    entry = data[session]
    if not isinstance(entry, dict):
        return False
    entry["state"] = outcome
    return _write(path, data)
