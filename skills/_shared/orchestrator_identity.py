"""orchestrator_identity.py — same-actor predicate + display label for orchestrator locks.

Pure stdlib module; no third-party deps. Flat module (no __init__.py) matching every
other skills/_shared/*.py. The public surface is exactly two functions:

  same_actor(owner_a, owner_b) -> bool
    True iff both owner strings denote the same git user, collapsing the
    'orchestrator:' namespace prefix. Two empty/None owners return False.

  display_label(owner) -> str
    Render an owner for human readouts, preserving the orchestrator distinction.

Design ref: three-pillars-docs/completed-tp-designs/orchestrator-identity/design.md
"""

from __future__ import annotations

from typing import Optional

_ORCH_PREFIX = "orchestrator:"


def _canonical(owner: Optional[str]) -> str:
    """Internal: collapse an owner string to its comparable git-user key.

    Strip a single leading 'orchestrator:' prefix, then strip whitespace and
    lowercase the remaining email. None/empty/non-str -> "" (never matches a real
    email). Non-str owners (e.g. malformed lock.json with owner=42) are treated as
    "" so same_actor returns False — fail-closed, never a spurious adoption.
    """
    if not owner:
        return ""
    if not isinstance(owner, str):
        return ""
    s = owner
    if s.startswith(_ORCH_PREFIX):
        s = s[len(_ORCH_PREFIX):]
    return s.strip().lower()


def same_actor(owner_a: Optional[str], owner_b: Optional[str]) -> bool:
    """True iff both owner strings denote the same git user.

    Collapses the 'orchestrator:' namespace: a prefixed owner and a bare owner
    with the same email (case-insensitive) are the same actor. Two empty/None
    owners are NOT the same actor — guards against a released (owner=None) lock
    spuriously matching a None current-user.
    """
    a = _canonical(owner_a)
    b = _canonical(owner_b)
    return a == b and a != ""


def display_label(owner: Optional[str]) -> str:
    """Render an owner for human readouts, preserving the orchestrator distinction.

    Rules:
      - None                     -> "-"           (released/clean)
      - non-str, non-None        -> str(owner)    (safe fallback; no orchestrator marker)
      - "orchestrator:<email>"   -> "<email> (orchestrator)"  (original case preserved)
      - "<bare-email>"           -> "<bare-email>"  (verbatim, no marker)

    Normalization (lowercasing) is for comparison only, never for display. The email's
    original case is preserved in the marker form. Non-str owners (e.g. a malformed
    lock.json with owner=42) are rendered safely without crashing.
    """
    if owner is None:
        return "-"
    if not isinstance(owner, str):
        return str(owner)
    if owner.startswith(_ORCH_PREFIX):
        rest = owner[len(_ORCH_PREFIX):]
        return f"{rest} (orchestrator)"
    return owner
