"""human_approval — the REQUIRED human-approval merge-gate predicate (read path).

stdlib-only (C1 invariant: no `import anthropic`, no `subprocess.run(["claude", ...])`).
Subprocess calls go to `gh` only, never to Claude/anthropic. Mirrors
`review_readiness.py`'s shape: live `*_fn` runners with an injected-dict test seam.

See `three-pillars-docs/completed-tp-designs/human-approval-merge-gate/detailed-design.md` for
the full interface specification and Finding dispositions (F1–F4, Decisions D1–D13).

Core guarantee (login-independent): a non-automation human APPROVED native PR review
current on the head is the SOLE approval mechanism (Path B, human_approval_review.py).
The SHA-tagged label path (Path A) has been RETIRED by retire-approval-tags.

The shared identity floor (automation_identities / _is_bot_login / _actor_is_human /
_approver_not_automation) is preserved: it is imported by human_approval_review and
single_account_detect.
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


# ============================================================
# Task 1.4: automation_identities (hybrid set, D3)
# ============================================================

# GitHub-native automation logins NOT covered by review_readiness's Copilot set.
# (The Copilot logins are reused from review_readiness._REST_COPILOT_LOGINS.)
_GITHUB_NATIVE_AUTOMATION: frozenset = frozenset(
    {
        "github-actions[bot]",
        "github-actions",
        "dependabot[bot]",
    }
)


def automation_identities(*, self_login, config) -> frozenset:
    """Lowercased automation logins the approver must NOT be (D3 hybrid set).

    Base floor = hardcoded known framework/CI bots:
      - review_readiness._REST_COPILOT_LOGINS (copilot[bot], github-copilot[bot],
        copilot-pull-request-reviewer[bot], copilot)
      - the GitHub-native logins (github-actions[bot], github-actions, dependabot[bot])
    PLUS the framework's own gh-authenticated *self* login when truthy (lowercased).
    PLUS any extra logins from config review.automation_identities (list[str]), so an
    org can name its own service accounts (and, for multi-account separation-of-duties,
    its committing CI identity) WITHOUT a code change.

    F2 — self_login is resolved by the CALLER (human_approved_on_head) and an
    UNRESOLVABLE self_login is handled fail-CLOSED there (the caller returns False
    BEFORE building this set), NOT here. This function only ever receives a known
    self_login (or None when the caller is building the set for a detail string).

    Type-safe / total: non-dict config or review, non-list automation_identities are
    ignored gracefully.
    """
    import review_readiness  # noqa: E402 — in _shared/ beside this file

    members = set(review_readiness._REST_COPILOT_LOGINS) | set(_GITHUB_NATIVE_AUTOMATION)

    if isinstance(self_login, str) and self_login:
        members.add(self_login.lower())

    if isinstance(config, dict):
        review = config.get("review")
        if isinstance(review, dict):
            extra = review.get("automation_identities")
            if isinstance(extra, list):
                for login in extra:
                    if isinstance(login, str) and login:
                        members.add(login.lower())

    return frozenset(members)


# ============================================================
# Task 1.5: _actor_is_human (bot/App/automation floor, F2)
# ============================================================


def _is_bot_login(login) -> bool:
    """Catch-all backstop: a `[bot]`-suffixed login is an App/bot actor.

    Covers any unenumerated `[bot]` actor not in the hardcoded automation set.
    Total over non-str input.
    """
    return isinstance(login, str) and login.endswith("[bot]")


def _actor_is_human(event, automation: frozenset) -> bool:
    """Bot/App/automation-login FLOOR for an event's actor.

    Requires ALL:
      - actor.type != "Bot"           (App-installation tokens surface as Bot)
      - login (lowercased) ∉ automation (configured/self/known-bot logins)
      - not _is_bot_login(login)       ([bot]-suffix catch-all backstop)

    NOTE (F2): a "User"-type actor on a user-PAT install is NOT proof of a human;
    this is the FLOOR. Total / fail-closed: missing/malformed actor → False, never raises.
    """
    if not isinstance(event, dict):
        return False
    actor = event.get("actor")
    if not isinstance(actor, dict):
        return False
    if actor.get("type") == "Bot":
        return False
    login = actor.get("login")
    if not isinstance(login, str) or not login:
        return False
    login = login.lower()
    if login in automation:
        return False
    if _is_bot_login(login):
        return False
    return True


# ============================================================
# Task 1.6: _approver_not_automation (distinctness, F3)
# ============================================================


def _approver_not_automation(event, automation: frozenset) -> bool:
    """F3 distinctness: the approver is not a PROVABLE automation identity.

    Distinct ⟺ approver.login (lowercased) ∉ automation. The approver MAY equal the
    head committer/author login (the solo-operator case) — committer-equality is
    ADVISORY and does NOT fail this conjunct. This fn deliberately takes NO committer
    parameter: there is NO approver≠committer hard rule (which would make the gate
    un-satisfiable for the single-account operator). A team enforces
    separation-of-duties by naming the committing identity in
    review.automation_identities, which DOES land it in `automation` and hard-rejects.

    Total / fail-closed: missing/malformed actor → False, never raises.
    """
    if not isinstance(event, dict):
        return False
    actor = event.get("actor")
    if not isinstance(actor, dict):
        return False
    login = actor.get("login")
    if not isinstance(login, str) or not login:
        return False
    return login.lower() not in automation


# ============================================================
# Task 1.8: live runners (per-key F4) + human_approved_on_head
# ============================================================

# The runner keys, resolved PER-KEY against live defaults (F4). evaluate_gate
# passes the raw `r = runners or {}` (never None), so a whole-dict `if runners is
# None` fallback would be skipped by the non-None {} and KeyError on first subscript.
# Each key is resolved `(runners or {}).get(k) or _live[k]` instead.
_HUMAN_APPROVAL_KEYS = (
    "head_fn",
    "self_login_fn",
    "reviews_fn",
)


def _gh_json(args: list) -> object:
    """Run `gh <args>` and parse JSON stdout. Raises on gh failure (fail-CLOSED:
    the caller's per-fetch handling turns a raise into a fail-closed False)."""
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _build_live_runners(pr_url: str) -> dict:
    """Build the live `*_fn`s (calls live `gh`). Each fails CLOSED — it raises
    on a gh/JSON failure so human_approved_on_head's per-fetch try/except yields a
    fail-closed False (NEVER fail-open). Reuses thread_resolver._parse_pr_url (it is
    intra-_shared/ and on-path, unlike label_manager._parse_pr_url which lives in
    tp-pr-fix/scripts/ off the _shared/ shim)."""
    import thread_resolver  # noqa: E402 — in _shared/ beside this file

    owner, repo, number = thread_resolver._parse_pr_url(pr_url)

    def head_fn(url: str) -> dict:
        return _gh_json(["pr", "view", url, "--json", "headRefOid,commits"])

    def self_login_fn() -> str:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"gh api user failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def reviews_fn(url: str) -> list:
        # REST pulls/<n>/reviews — the proven shape (review_readiness.reviews_fn): each
        # entry carries user.login/user.type/state/commit_id/submitted_at. _gh_json raises
        # on a gh/JSON failure so human_approved_on_head's _safe_fetch yields a fail-closed
        # [] (review path → not satisfied), never fail-open.
        return _gh_json(
            ["api", f"repos/{owner}/{repo}/pulls/{number}/reviews", "--paginate"]
        )

    return {
        "head_fn": head_fn,
        "self_login_fn": self_login_fn,
        "reviews_fn": reviews_fn,
    }


def _safe_fetch(fn, *args, default):
    """Call fn(*args); on any raise OR a result whose type doesn't match `default`'s
    type return `default` (fail-closed). Used for the list/dict fetches."""
    try:
        result = fn(*args)
    except Exception:
        return default
    if not isinstance(result, type(default)):
        return default
    return result


def approved_on_head_result(pr_url: str, *, runners=None, config=None) -> "tuple[bool, str]":
    """Result-shaped entry point: `(True ⟺ a HUMAN approval is CURRENT-OR-CARRIED on THIS
    head, detail)`. `human_approved_on_head` is a thin wrapper (`== result[0]`).

    SOLE CURRENCY PATH: a non-automation human APPROVED native PR review current on the
    head (Path B — `human_approval_review.review_path_satisfied`) → `(True, "current")`.
    The SHA-tagged label path (Path A) has been RETIRED; `tp:human-approved` label
    presence has NO EFFECT.

    F4 per-key live-default wiring: each runner key is resolved `(runners or {}).get(k)
    or _live[k]` — never a whole-dict None fallback (evaluate_gate passes a non-None {}).

    F2 fail-CLOSED self: the FIRST thing done after wiring is resolve
    `self_login = self_login_fn()`; if it raises or is falsy, return `(False, "")`
    immediately (→ INDETERMINATE at the gate). We do NOT shrink the automation set and
    proceed (that would fail-OPEN on a user-PAT install).

    CARRY (task 6.3): on a currency MISS AND `base_sync_cert.carry_enabled(config)`, the
    seam resolution + delegated chain-walk call live in
    `human_approval_review.resolve_carry` (extracted to keep this file under the 350-line
    soft-warn). Config OFF (the default) makes that branch unreachable — behavior AND
    spawn profile are byte-identical to the pre-carry implementation (no git subprocess
    and no chain walk, ever; `base_sync_cert` is imported only for the cheap
    `carry_enabled` config check).

    Total — NEVER raises. Any failed conjunct, any fetch failure, any ambiguity →
    `(False, "")` (fail-closed).
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

        head_fn = _resolve("head_fn")
        self_login_fn = _resolve("self_login_fn")
        reviews_fn = _resolve("reviews_fn")

        # F2: self login is REQUIRED-resolvable. Unresolvable → fail-CLOSED.
        try:
            self_login = self_login_fn()
        except Exception:
            return False, ""
        if not self_login or not isinstance(self_login, str):
            return False, ""

        automation = automation_identities(self_login=self_login, config=config)

        head = _safe_fetch(head_fn, pr_url, default={})
        reviews = _safe_fetch(reviews_fn, pr_url, default=[])

        # Path B: native APPROVED review (the sole currency path after retire-approval-tags).
        # Lazy import (mirrors the review_readiness/thread_resolver lazy-import style and
        # avoids the human_approval_review -> human_approval import cycle). Reuses the same
        # `automation` set built above, so identity rejection is identical.
        import human_approval_review  # noqa: E402 — in _shared/ beside this file

        if human_approval_review.review_path_satisfied(reviews, head, automation=automation):
            return True, "current"

        # Currency miss: carry is the ONLY remaining path, and only when enabled. The
        # resolution block (repo_root / base_ref / run_git seams + the delegated call)
        # is extracted to human_approval_review.resolve_carry to keep this file under
        # the 350-line soft-warn (plan.md task 6.1's named escape hatch).
        return human_approval_review.resolve_carry(
            pr_url, reviews, head, automation=automation, config=config, runners=provided,
        )
    except Exception:
        return False, ""


def human_approved_on_head(pr_url: str, *, runners=None, config=None) -> bool:
    """True ⟺ a HUMAN (not bot/automation) has a CURRENT-OR-CARRIED APPROVED review on
    THIS head. Thin wrapper: `== approved_on_head_result(...)[0]`. See that function's
    docstring for the full currency + carry contract. Total — never raises."""
    return approved_on_head_result(pr_url, runners=runners, config=config)[0]


# ============================================================
# Task 2.1: _require_human_approval config interpreter (D4)
# ============================================================


def _require_human_approval(config) -> bool:
    """Whether the human-approval predicate is REQUIRED on this repo's PRs (D4).

    Reads `review.require_human_approval` from .three-pillars/config.json (threaded
    in as `config`). Default True (strict): a missing subsection, a missing key, a
    non-dict `review`, or a None/absent config ALL fold to True so a missing/corrupt
    config NEVER relaxes the gate. ONLY an explicit `review.require_human_approval:
    false` opts the repo out (the human-approval predicate is then OMITTED from the
    fold, restoring the pre-existing predicate set verbatim — backward-compat).

    Mirrors `loop_driver._expects_copilot_review` semantics. Type-safe: any non-dict
    `review` falls back to the strict default rather than raising on `.get`.
    """
    review = (config or {}).get("review") if isinstance(config, dict) else None
    if not isinstance(review, dict):
        return True
    return bool(review.get("require_human_approval", True))
