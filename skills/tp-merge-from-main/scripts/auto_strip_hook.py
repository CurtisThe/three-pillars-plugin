"""auto_strip_hook — thin push-time hook that strips a stale human-approval label.

After a push advances a PR's head, the previously-applied `tp:human-approved` label
is stale and must be cleared so the GitHub UI honestly reflects what is authorized
on the NEW head (D2 — the auto-strip write site). This module is the wiring point the
base-sync push step calls AFTER the push lands; the actual removal logic lives in
`human_approval.strip_stale_approval`.

stdlib-only (C1 invariant: no `import anthropic`, no `subprocess.run(["claude", ...])`).
The only side effect is the REST DELETE inside `strip_stale_approval` (a `gh` call).

FAIL-OPEN by design: `run` swallows ANY exception and returns False, so a strip
failure (network blip, gh error, an unexpected internal raise) can NEVER block a push.
The gate-time currency re-check in `pred_human_approved` is the independent
fail-CLOSED backstop — a missed strip never defeats correctness; it only leaves a
stale label visible until the next gate evaluation.

> Placement (plan Task 3.2 / 4.2 / D2): this hook lives at its permanent home
> `skills/tp-merge-from-main/scripts/auto_strip_hook.py` (the base-sync half, post the
> `/tp-merge` → `/tp-merge-from-main` rename). It is wired into the base-sync push step
> (the renamed skill's step 7) — see `skills/tp-merge-from-main/SKILL.md`.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---- sys.path: ensure _shared/ is on path so human_approval is importable ----
_SCRIPTS_DIR = Path(__file__).resolve().parent
_SHARED_DIR = _SCRIPTS_DIR.parent.parent / "_shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from human_approval import strip_stale_approval  # noqa: E402


def run(pr_url: str, new_head_oid: str, *, runners=None) -> bool:
    """Strip a stale `tp:human-approved` label after the PR head advanced to
    `new_head_oid`. Returns True iff the label was removed, False otherwise.

    FAIL-OPEN: any exception is swallowed and False is returned — this hook must
    NEVER block a push. Correctness is guaranteed independently by the gate-time
    currency re-check, not by this convenience strip.
    """
    try:
        return strip_stale_approval(pr_url, new_head_oid, runners=runners)
    except Exception:
        return False
