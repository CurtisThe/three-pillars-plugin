"""single_account_detect.py — single-account collision detection helpers.

Solo-operator-identity-split design: these helpers detect the single-account
collision topology (pure/live). They are advisory-only and fail-open at the
detection layer — they never block a commit or a gate evaluation.

After retire-approval-tags: the per-PR label collision signature helpers
(approval_collision_signature, approval_collision_signature_live) have been
REMOVED — they were pure Path-A label logic. The collaborator-set collision
helpers (single_account_collision, single_account_collision_live) are KEPT:
they now mean "the review-path gate has no distinct human reviewer → no gate".

Imports from human_approval one-directionally (no circular import):
human_approval holds the gate predicates; this module holds the
detection helpers that call no gate code.

stdlib-only (C1 invariant: no `import anthropic`,
no `subprocess.run(["claude", ...])`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ---- sys.path: ensure _shared/ is on path so sibling modules are importable ----
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from human_approval import (  # noqa: E402
    _is_bot_login,
    automation_identities,
)


# ============================================================
# solo-operator-identity-split: Detection helpers
# ============================================================


def single_account_collision(*, self_login, collaborators, config) -> bool:
    """Detect a single-account collision topology (pure/total, fail-open).

    Returns True iff the review-path gate has no distinct human reviewer — i.e.
    there is NO collaborator login that a human could use to submit an APPROVED review
    that would fall OUTSIDE the automation set. This is the "collision" case: the only
    human path equals the automation identity, so a human APPROVED review would be
    rejected as automation-authored, leaving the operator with NO gate.

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
    import subprocess as _sp

    try:
        provided = runners or {}
        self_login_fn = provided.get("self_login_fn")
        collaborators_fn = provided.get("collaborators_fn")

        if self_login_fn is None:
            # Build a live self_login_fn inline (no pr_url needed here)
            def self_login_fn():
                r = _sp.run(
                    ["gh", "api", "user", "--jq", ".login"],
                    capture_output=True, text=True, check=False,
                )
                if r.returncode != 0:
                    raise RuntimeError(f"gh api user failed: {r.stderr.strip()}")
                return r.stdout.strip()

        if collaborators_fn is None:
            def collaborators_fn():
                r = _sp.run(
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
