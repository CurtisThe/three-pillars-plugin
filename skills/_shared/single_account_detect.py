"""single_account_detect.py — single-account collision detection helpers.

Solo-operator-identity-split design: these four helpers detect the
single-account collision topology (pure/live) and the per-PR collision
signature (pure/live). They are advisory-only and fail-open at the
detection layer — they never block a commit or a gate evaluation.

Imports from human_approval one-directionally (no circular import):
human_approval holds the gate predicates; this module holds the
detection helpers that call no gate code.

stdlib-only (C1 invariant: no `import anthropic`,
no `subprocess.run(["claude", ...])`).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# ---- sys.path: ensure _shared/ is on path so sibling modules are importable ----
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from human_approval import (  # noqa: E402
    HUMAN_APPROVED_LABEL,
    _build_live_runners,
    _is_bot_login,
    _label_present,
    _latest_label_event,
    automation_identities,
)


# ============================================================
# solo-operator-identity-split: Detection helpers
# ============================================================


def single_account_collision(*, self_login, collaborators, config) -> bool:
    """Detect a single-account collision topology (pure/total, fail-open).

    Returns True iff the `gh` self-login is the only human-approval path — i.e.
    there is NO collaborator login that a human could use to apply tp:human-approved
    that would fall OUTSIDE the automation set. This is the "collision" case: any
    approval will be rejected because the sole human path equals the automation identity.

    Collision ⟺ for EVERY collaborator entry with type=="User" and a non-[bot] login,
    that login.lower() is INSIDE the automation set (reusing automation_identities —
    no duplication). If any such login is OUTSIDE the automation set, there is a
    distinct human approval path → return False (no collision).

    Design note — row (c) ["self-login maps to operator's own git identity, no distinct
    machine account"] is INTENTIONALLY SUBSUMED by this row-(b) condition. The
    collaborator-set view is the decisive, forge-agnostic signal: if the only human
    collaborator is also the self-login, the collision fires regardless of whether
    that login is the operator's git identity. No separate git-identity input is needed
    or accepted — the collaborator set alone is sufficient and simpler.

    Fail-open guards:
      - self_login falsy or non-str → False (cannot reason about automation set)
      - collaborators not a list → False (cannot enumerate the collaborator set)
      - any collaborator with a non-dict or missing/None login entry → skipped
    Never raises; never calls gh.
    """
    # Fail-open guards
    if not isinstance(self_login, str) or not self_login:
        return False
    if not isinstance(collaborators, list):
        return False

    automation = automation_identities(self_login=self_login, config=config)

    for collab in collaborators:
        if not isinstance(collab, dict):
            continue
        login = collab.get("login")
        if not isinstance(login, str) or not login:
            continue
        # Only consider human-type collaborators (type=="User", non-[bot])
        collab_type = collab.get("type", "User")
        if collab_type != "User":
            continue
        if _is_bot_login(login):
            continue
        # This is a human-type collaborator. Is it OUTSIDE the automation set?
        if login.lower() not in automation:
            # Distinct human approval path exists → no collision.
            return False

    # No distinct human collaborator found outside the automation set.
    return True


def single_account_collision_live(*, runners=None, config=None) -> bool:
    """Live wrapper: resolve self_login and collaborators, then call single_account_collision.

    Fail-OPEN at the detection layer: any failure to resolve self_login or the
    collaborator set returns False (silent — we never block on an unresolvable
    environment, and we never spuriously warn). The inverse of the gate's fail-closed.

    Runner keys (test seam):
      - self_login_fn(): -> str  (default: gh api user --jq .login)
      - collaborators_fn(): -> list  (default: gh api repos/{owner}/{repo}/collaborators)

    The collaborators_fn live default calls:
      gh api repos/{owner}/{repo}/collaborators --jq '[.[]|{login:.login,type:.type}]'
    using the framework's own gh-auth context. If any fetch raises, returns False.
    """
    try:
        provided = runners or {}
        self_login_fn = provided.get("self_login_fn")
        collaborators_fn = provided.get("collaborators_fn")

        if self_login_fn is None:
            # Build a live self_login_fn inline (no pr_url needed here)
            import subprocess as _sp

            def self_login_fn():
                r = _sp.run(
                    ["gh", "api", "user", "--jq", ".login"],
                    capture_output=True, text=True, check=False,
                )
                if r.returncode != 0:
                    raise RuntimeError(f"gh api user failed: {r.stderr.strip()}")
                return r.stdout.strip()

        if collaborators_fn is None:
            import subprocess as _sp2

            def collaborators_fn():
                r = _sp2.run(
                    [
                        "gh", "api", "repos/{owner}/{repo}/collaborators",
                        "--jq", "[.[]|{login:.login,type:.type}]",
                    ],
                    capture_output=True, text=True, check=False,
                )
                if r.returncode != 0:
                    raise RuntimeError(f"gh api collaborators failed: {r.stderr.strip()}")
                return json.loads(r.stdout)

        self_login = self_login_fn()
        if not isinstance(self_login, str) or not self_login:
            return False

        collaborators = collaborators_fn()
        if not isinstance(collaborators, list):
            return False

        return single_account_collision(
            self_login=self_login,
            collaborators=collaborators,
            config=config or {},
        )
    except Exception:
        # Fail-OPEN: any resolution failure yields no warning, never blocks.
        return False


def approval_collision_signature(*, labels, timeline, self_login) -> bool:
    """Detect the collision signature on a PR: label present AND latest actor == self_login.

    True ⟺ BOTH:
      1. A tp:human-approved family label is present (reuses _label_present)
      2. The most-recent labeled event for it has actor.login (lowercased) == self_login.lower()

    This is the PR-level signal: the operator DID try to approve (label is present)
    but applied it as the framework's own login (collision actor). This is
    distinct from the absent-label case or the stale-on-head case.

    Pure/total, fail-closed: missing/malformed inputs → False, never raises.
    All fixtures must use the tagged form tp:human-approved:<sha7+>.
    """
    if not isinstance(self_login, str) or not self_login:
        return False
    if not _label_present(labels, HUMAN_APPROVED_LABEL):
        return False
    ev = _latest_label_event(timeline, HUMAN_APPROVED_LABEL)
    if not ev:
        return False
    actor = ev.get("actor") if isinstance(ev, dict) else None
    if not isinstance(actor, dict):
        return False
    actor_login = actor.get("login")
    if not isinstance(actor_login, str) or not actor_login:
        return False
    return actor_login.lower() == self_login.lower()


def approval_collision_signature_live(pr_url: str, *, runners=None) -> bool:
    """Live wrapper for approval_collision_signature.

    Resolves labels_fn, timeline_fn, and self_login_fn from the provided
    runners dict or from _build_live_runners(pr_url) for defaults. Returns
    False on any resolution failure (fail-open at the detection layer).
    """
    try:
        provided = runners or {}
        live = None

        def _resolve(key):
            nonlocal live
            fn = provided.get(key)
            if fn is not None:
                return fn
            if live is None:
                live = _build_live_runners(pr_url)
            return live[key]

        labels_fn = _resolve("labels_fn")
        timeline_fn = _resolve("timeline_fn")
        self_login_fn = _resolve("self_login_fn")

        self_login = self_login_fn()
        if not isinstance(self_login, str) or not self_login:
            return False

        labels = labels_fn(pr_url)
        timeline = timeline_fn(pr_url)

        return approval_collision_signature(
            labels=labels,
            timeline=timeline,
            self_login=self_login,
        )
    except Exception:
        return False
