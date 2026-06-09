"""review_readiness — free, stdlib-only predicate for Copilot review readiness.

Parallels `skills/_shared/release_tiers.py` as the canonical **free, pytest-free,
stdlib-only** shared module. Importable by free `loop_driver` + `merge_gate` AND
pro `fleet_status` with no cross-skill import.

C1 invariant: no `import anthropic`, no `subprocess.run(["claude", ...])`.
This module is plumbing only — subprocess calls go to `gh` and `git`, never
to Claude/anthropic.

See `three-pillars-docs/completed-tp-designs/pr-readiness-surface/detailed-design.md` for
the full interface specification and Finding dispositions.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# ---- sys.path: ensure _shared/ is on path so thread_resolver is importable ----
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

# ---- loop_driver import for _CI_TERMINAL_CONCLUSIONS (Finding C deliberate coupling) ----
_LOOP_DRIVER_DIR = _SHARED_DIR.parent / "tp-pr-iterate" / "scripts"
if str(_LOOP_DRIVER_DIR) not in sys.path:
    sys.path.insert(0, str(_LOOP_DRIVER_DIR))

from loop_driver import _CI_TERMINAL_CONCLUSIONS  # noqa: E402


# ============================================================
# Constants (per-surface login sets)
# ============================================================

# REST review/comment author logins (pulls/<n>/reviews .user.login)
_REST_COPILOT_LOGINS: frozenset[str] = frozenset(
    {
        "copilot-pull-request-reviewer[bot]",
        "copilot[bot]",
        "github-copilot[bot]",
        "copilot",
    }
)

# GraphQL reviewThreads author.login carries NO [bot] suffix
# (verified at thread_resolver._THREADS_QUERY: author{login} returns the bare spelling)
_GRAPHQL_COPILOT_LOGIN = "copilot-pull-request-reviewer"

# The transient Copilot startup-crash review body (case-insensitive substring)
_ERROR_BODY_MARKER = "encountered an error and was unable to review"

# Exempt run-telemetry suffixes (Finding F — bounded to these only)
_RUN_EXEMPT_SUFFIXES: frozenset[str] = frozenset({".json", ".log", ".txt", ".ndjson"})


# ============================================================
# Task 1.1: Pure helpers — is_error_body, is_copilot_review_author
# ============================================================


def is_error_body(body) -> bool:
    """True if a review body is the transient Copilot startup-crash no-op.

    Case-insensitive substring on _ERROR_BODY_MARKER. Such a review is a terminal
    no-op — never counted as reviewed.

    body may be None (GitHub review payloads can have null body when the review
    has no summary text); None is treated as an empty string — not an error body.
    """
    if not body:
        return False
    return _ERROR_BODY_MARKER.lower() in body.lower()


def is_copilot_review_author(login: str, *, surface: str) -> bool:
    """Per-surface login filter. surface in {'rest', 'graphql'}.

    rest    → lowercased membership in _REST_COPILOT_LOGINS
    graphql → bare login equality with _GRAPHQL_COPILOT_LOGIN
              (the '[bot]' suffix is NOT present on the graphql surface)

    An unknown surface raises ValueError (no silent fall-through to a wrong filter).
    """
    if surface == "rest":
        return login.lower() in _REST_COPILOT_LOGINS
    elif surface == "graphql":
        return login == _GRAPHQL_COPILOT_LOGIN
    else:
        raise ValueError(
            f"Unknown surface {surface!r}: must be 'rest' or 'graphql'. "
            "A single hard-coded filter yields false zeros (design Constraint) — "
            "callers MUST pass the surface they read."
        )


# ============================================================
# Task 1.2: latest_copilot_review
# ============================================================


def latest_copilot_review(reviews: list[dict]) -> dict | None:
    """From REST `gh api pulls/<n>/reviews` payload, the most-recent Copilot review.

    Returns the dict (with submitted_at, commit_id, body, state) or None.
    Ordering by submitted_at; ties broken by list order (GitHub returns chronological).
    """
    copilot_reviews = [
        r for r in reviews
        if is_copilot_review_author(
            (r.get("user") or {}).get("login", ""),
            surface="rest",
        )
    ]
    if not copilot_reviews:
        return None
    # max() is stable — on ties it returns the first (lowest-index) maximum element
    return max(copilot_reviews, key=lambda r: r.get("submitted_at", ""))


# ============================================================
# Task 1.3: review_exempt_delta (Finding F bounds + Finding I fail-closed)
# ============================================================


def _is_exempt_path(path: str) -> bool:
    """True when a single changed file path matches an exempt rule.

    Exempt rules:
    - three-pillars-docs/tp-designs/*/decisions.md
    - three-pillars-docs/tp-designs/*/handoff.md
    - three-pillars-docs/tp-designs/*/lock.json
    - **/CHANGELOG* (any level)
    - .three-pillars/run/** — BOUNDED (Finding F): only _RUN_EXEMPT_SUFFIXES
    """
    p = path.strip()
    if not p:
        return False

    # Explicit design-doc patterns
    if p.startswith("three-pillars-docs/tp-designs/"):
        parts = p.split("/")
        if len(parts) >= 4:
            filename = parts[-1]
            if filename in ("decisions.md", "handoff.md", "lock.json"):
                return True

    # CHANGELOG at any level
    basename = Path(p).name
    if basename.startswith("CHANGELOG"):
        return True

    # .three-pillars/run/** — BOUNDED to _RUN_EXEMPT_SUFFIXES
    if p.startswith(".three-pillars/run/"):
        suffix = Path(p).suffix
        return suffix in _RUN_EXEMPT_SUFFIXES

    return False


def review_exempt_delta(
    base_sha: str,
    head_sha: str,
    *,
    run_subprocess=subprocess.run,
) -> bool:
    """True when every file changed in base_sha..head_sha is a review-exempt path.

    FAIL-CLOSED (Finding I): base_sha or head_sha that is None / empty /
    unresolvable (git diff returns non-zero) → return False. 'Cannot prove
    exemption' is NEVER vacuously True.

    The ONLY True-on-empty case is an EXPLICIT head == base with a clean exit
    (git diff exits 0, empty name-only output) — a genuinely empty delta.
    """
    # Finding I: fail-closed on null/empty
    if not base_sha or not head_sha:
        return False

    result = run_subprocess(
        ["git", "diff", "--name-only", f"{base_sha}..{head_sha}"],
        capture_output=True,
        text=True,
        check=False,
    )
    # Non-zero exit (unresolvable ref) → fail-closed False
    if result.returncode != 0:
        return False

    changed_paths = [p for p in result.stdout.splitlines() if p.strip()]

    # Explicit clean head == base: empty output with clean exit → True
    if not changed_paths:
        return True

    # Every changed path must match an exempt rule, else the delta is NON-exempt
    return all(_is_exempt_path(p) for p in changed_paths)


# ============================================================
# Task 1.4: ci_head_fn (Finding C — new (head_oid, settled) wrapper)
# ============================================================


def ci_head_fn(
    pr_url: str,
    *,
    run_subprocess=subprocess.run,
) -> tuple[str | None, bool]:
    """gh pr view <pr_url> --json statusCheckRollup,headRefOid (ONE fetch).

    Returns (head_oid, settled):
      head_oid = payload['headRefOid'] or None.
      settled  = rollup non-empty AND every check.conclusion in
                 _CI_TERMINAL_CONCLUSIONS (imported from loop_driver — the SAME
                 terminal-conclusion set; do NOT re-list).
    Fail-soft: gh non-zero / unparsable JSON → (None, False) (degrade less-ready).
    """
    result = run_subprocess(
        ["gh", "pr", "view", pr_url, "--json", "statusCheckRollup,headRefOid"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return (None, False)
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return (None, False)

    head_oid = payload.get("headRefOid") or None
    rollup = payload.get("statusCheckRollup") or []

    if not rollup:
        return (head_oid, False)

    settled = all(
        (check.get("conclusion") or "").upper() in _CI_TERMINAL_CONCLUSIONS
        for check in rollup
    )
    return (head_oid, settled)


# ============================================================
# Task 1.5: classify_readiness — full enum + thread filter + _LIVE_RUNNERS sentinel
# ============================================================


def _is_bot_author(login: str) -> bool:
    """True when login looks like a bot (ends with [bot] or is a known bot name)."""
    return login.endswith("[bot]") or login in ("bot",)


def _is_actionable_thread_author(login: str) -> bool:
    """True when a thread author is actionable (Copilot-graphql OR human, not other-bot).

    Actionable = is_copilot_review_author(login, surface='graphql')
                 OR the thread is HUMAN-authored (non-empty, non-bot author).
    Bot threads from OTHER bots (e.g. dependabot) are NOT actionable and are ignored.
    """
    if not login:
        return False
    if is_copilot_review_author(login, surface="graphql"):
        return True
    # Human: non-empty and not a bot (doesn't end with [bot])
    if not _is_bot_author(login):
        return True
    return False


def _count_unresolved_actionable(threads: list[dict]) -> int:
    """Count unresolved threads that have actionable authors.

    Filtering is applied BEFORE counting (Finding A).
    """
    count = 0
    for thread in threads:
        if thread.get("is_resolved", False):
            continue
        author = thread.get("author", "")
        if _is_actionable_thread_author(author):
            count += 1
    return count


def _is_on_head_or_exempt(review: dict, head_oid: str, *, run_subprocess=subprocess.run) -> bool:
    """True when the review is on the current head OR head-delta is review-exempt."""
    review_commit_id = review.get("commit_id", "")
    if head_oid and review_commit_id == head_oid:
        return True
    # Attempt to prove delta is exempt (fail-closed on error). run_subprocess is
    # injectable so unit tests can force the fail-closed path deterministically
    # without shelling out to git on fabricated SHAs.
    return review_exempt_delta(review_commit_id, head_oid, run_subprocess=run_subprocess)


def _build_live_runners(pr_url: str | None = None) -> dict:
    """Build the live runners dict (calls live gh). Called ONLY when runners is None."""
    import thread_resolver  # noqa: E402 — in _shared/ beside this file

    def reviews_fn(url: str) -> list[dict]:
        import re
        m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", url)
        if not m:
            return []
        owner, repo, number = m.group(1), m.group(2), m.group(3)
        result = subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo}/pulls/{number}/reviews"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            return []
        try:
            return json.loads(result.stdout) or []
        except (json.JSONDecodeError, ValueError):
            return []

    def threads_fn(url: str) -> list[dict]:
        return thread_resolver.list_review_threads(url)

    def _live_ci_head_fn(url: str) -> tuple[str | None, bool]:
        return ci_head_fn(url)

    def requested_fn(url: str) -> list[str]:
        import re
        m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", url)
        if not m:
            return []
        owner, repo, number = m.group(1), m.group(2), m.group(3)
        result = subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo}/pulls/{number}/requested_reviewers"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            return []
        try:
            data = json.loads(result.stdout) or {}
            users = data.get("users") or []
            teams = data.get("teams") or []
            return [u.get("login", "") for u in users] + [t.get("slug", "") for t in teams]
        except (json.JSONDecodeError, ValueError):
            return []

    return {
        "reviews_fn": reviews_fn,
        "threads_fn": threads_fn,
        "ci_head_fn": _live_ci_head_fn,
        "requested_fn": requested_fn,
    }


# Module-level sentinel: live runners are built ONLY when runners is None.
# Tests always inject a runners dict; this attribute signals the isolation boundary.
_LIVE_RUNNERS = _build_live_runners  # callable sentinel, never invoked by tests


def classify_readiness(pr_url: str, *, runners: dict | None = None) -> str:
    """The review-readiness ENUM over a live PR.

    Returns one of:
      'unreviewed'       — Copilot is NOT requested AND no Copilot review exists.
      'awaiting-copilot' — requested but no review yet, OR a review exists but actionable
                           threads remain unresolved or currency is unprovable (transient).
      'copilot-errored'  — a Copilot review exists but is_error_body.
      'review-stale'     — a non-error Copilot review on a PAST head with NON-exempt delta.
      'reviewed-stable'  — copilot_reviewed_successfully holds.

    Decision order (first match wins):
      1. latest = latest_copilot_review(reviews_fn(pr_url))
      2. latest is None:
           requested_fn has Copilot → 'awaiting-copilot'
           else                     → 'unreviewed'
      3. is_error_body(latest.body) → 'copilot-errored'
      4. on-head-or-exempt-delta AND zero unresolved actionable threads → 'reviewed-stable'
      5. NOT on-head AND head-delta NON-exempt → 'review-stale'
      6. otherwise → 'awaiting-copilot'

    runners injects the four gh fetchers for tests; None wires the live defaults.
    Fail-soft: an unfetchable signal degrades toward the less-ready state.
    """
    if runners is None:
        runners = _build_live_runners()

    reviews_fn = runners["reviews_fn"]
    threads_fn = runners["threads_fn"]
    ci_head_fn_r = runners["ci_head_fn"]
    requested_fn = runners["requested_fn"]

    # Step 1: get the latest Copilot review.
    # Fail-soft: infrastructure errors (subprocess failures, JSON decode errors)
    # degrade gracefully; but AssertionError / injected-sentinel raises propagate
    # so tests can verify the injected runners are actually called (Finding J).
    try:
        reviews = reviews_fn(pr_url)
    except (AssertionError, KeyboardInterrupt, SystemExit):
        raise  # sentinel errors and system signals propagate
    except Exception:
        reviews = []

    latest = latest_copilot_review(reviews)

    # Step 2: No review at all
    if latest is None:
        try:
            requested = requested_fn(pr_url)
        except (AssertionError, KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            requested = []
        # Check if Copilot is among requested reviewers (REST surface)
        copilot_requested = any(
            is_copilot_review_author(login, surface="rest")
            for login in requested
        )
        return "awaiting-copilot" if copilot_requested else "unreviewed"

    # Step 3: Error body
    if is_error_body(latest.get("body", "")):
        return "copilot-errored"

    # Step 4+5: Need head_oid to check currency
    try:
        head_oid, _settled = ci_head_fn_r(pr_url)
    except (AssertionError, KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        head_oid = None

    on_head_or_exempt = False
    if head_oid:
        _run_subprocess = runners.get("run_subprocess", subprocess.run)
        on_head_or_exempt = _is_on_head_or_exempt(
            latest, head_oid, run_subprocess=_run_subprocess
        )

    # Step 4: on-head or exempt AND zero unresolved actionable threads → reviewed-stable
    if on_head_or_exempt:
        try:
            threads = threads_fn(pr_url)
        except (AssertionError, KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            threads = []
        unresolved = _count_unresolved_actionable(threads)
        if unresolved == 0:
            return "reviewed-stable"
        else:
            # On-head/exempt but threads still unresolved
            return "awaiting-copilot"

    # Step 5: head known but review NOT on-head and delta NON-exempt → review-stale (Finding E).
    # We do NOT recompute review_exempt_delta here: reaching this point with a truthy
    # head_oid means Step-4's _is_on_head_or_exempt already proved (not on-head AND not
    # exempt) using the injected run_subprocess. Recomputing would duplicate the work and
    # shell out to real git un-stubbed in tests (Copilot #57 round-3 finding).
    if head_oid:
        return "review-stale"

    # Step 6: head unknown → currency unprovable → awaiting-copilot
    return "awaiting-copilot"


# ============================================================
# Task 1.6: copilot_reviewed_successfully (thin wrapper)
# ============================================================


def copilot_reviewed_successfully(pr_url: str, *, runners: dict | None = None) -> bool:
    """The positive predicate. True ⟺ classify_readiness == 'reviewed-stable'.

    True ⟺ ALL hold:
      (1) ∃ a latest Copilot review that is NOT is_error_body  (non-error)
      (2) that review is on the current head OR head-delta is review-exempt
      (3) zero unresolved ACTIONABLE threads (Copilot-by-graphql-login OR human)

    Thread-absence is necessary-but-NOT-sufficient: (3) without (1)+(2) is the
    error-review / stale-head false positive this design closes.
    Thin wrapper: classify_readiness(...) == 'reviewed-stable'.
    """
    return classify_readiness(pr_url, runners=runners) == "reviewed-stable"
