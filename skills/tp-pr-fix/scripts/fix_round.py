"""fix_round.run_round — the single-round PR-fix worker.

Receives a list of already-classified comments (the Sonnet judge call lives
in `/tp-pr-fix` SKILL.md prose per audit C1) and orchestrates ONE end-to-end
fix round:

  1. Identity-gate every commenter against `gh api repos/{o}/{r}/collaborators/{u}`,
     except trusted requested-reviewer bots (Copilot) which pass via an allowlist
     (they 404 on the collaborators endpoint but are legitimate reviewers — F3).
     - 404 (non-bot) → defer with `reason="non-collaborator"`.
     - Transient 5xx → defer with `reason="identity-gate-unreachable"` and
       carry on. **Never raise** — the loop driver retries on the next poll
       (design constraint: "identity-gate failure aborts the round, not the loop").
  2. From collaborator-gated comments, keep verdict="structural"; defer the
     rest (`minor-only`, `unclear-verdict`).
  3. Commit the working tree (files the caller's Agent() invocation already
     wrote) as ONE commit with subject prefix `[tp-pr-fix iter-N]`. Override
     `GIT_COMMITTER_EMAIL` to `orchestrator+{user-localpart}@{user-domain}`
     so the auto-fix bot is auditable in `git log --format=%ce`.
  4. Push the branch.
  5. Apply the `tp:do-not-merge-yet` label via `label_manager.ensure_pr_label`.
  6. Return a fix-envelope.v1 dict.

Helpers (`_resolve_committer_env`, `_commit_message`, `_check_collaborator`,
`_parse_pr_url`, `_count_diff_lines`) keep the linear body readable.

The Sonnet judge call is NOT here — it lives in SKILL.md prose and produces
the `classified` list this function consumes.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from label_manager import ensure_pr_label  # noqa: E402  (sibling module)

# ---- sys.path: ensure _shared/ is importable so the auto-strip hook resolves ----
# fix_round.py lives at skills/tp-pr-fix/scripts/; _shared/ is skills/_shared/.
_SHARED_DIR = Path(__file__).resolve().parent.parent.parent / "_shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))


_FIX_LABEL = "tp:do-not-merge-yet"


class HeadRefMismatch(RuntimeError):
    """Raised (standalone only) when the checked-out branch is not the PR head.

    The fix round must commit to the PR head ref, not to `tp/{design}`. When
    the loop driver / `--auto` is in control the head is checked out
    automatically; standalone we refuse rather than silently mutate the
    operator's working branch (F1, pr-fix-targeting-and-auto-review seed).
    """


# Requested-reviewer bots (e.g. GitHub Copilot code review) are NOT repo
# collaborators, so `gh api .../collaborators/{bot}` 404s — but their review
# comments are legitimate and must be actioned, not deferred as untrusted
# drive-by (F3, pr-fix-targeting-and-auto-review seed). This allowlist
# short-circuits the collaborator gate for known code-review bots. Extend
# per-repo via the comma-separated TP_PR_FIX_TRUSTED_BOTS env var.
#
# Entries are stored lowercase and matched against `reviewer.lower()`: GitHub
# returns the Copilot reviewer login in several casings ("Copilot" on inline
# comments, "copilot-pull-request-reviewer[bot]" on reviews), and a casing
# mismatch would mis-route a legitimate review back into the 404-ing
# collaborators gate and re-defer it as non-collaborator (round-3 review).
_TRUSTED_REVIEWER_BOTS = frozenset(
    {
        "copilot",
        "copilot-pull-request-reviewer[bot]",
        "copilot[bot]",
        "github-copilot[bot]",
    }
)


def _trusted_reviewer_bots() -> frozenset[str]:
    extra = os.environ.get("TP_PR_FIX_TRUSTED_BOTS", "")
    if not extra.strip():
        return _TRUSTED_REVIEWER_BOTS
    return _TRUSTED_REVIEWER_BOTS | frozenset(
        b.strip().lower() for b in extra.split(",") if b.strip()
    )


# ---------- helpers ----------


def _parse_pr_url(pr_url: str) -> tuple[str, str]:
    """https://github.com/<owner>/<repo>/pull/<n> → (owner, repo)."""
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/(?:pull|issues)/\d+", pr_url)
    if not m:
        raise ValueError(f"unrecognized GitHub PR URL: {pr_url!r}")
    return m.group(1), m.group(2)


def _resolve_committer_env() -> dict:
    """Read `git config user.email`; return env overrides for the bot identity."""
    result = subprocess.run(
        ["git", "config", "user.email"], capture_output=True, text=True, check=False
    )
    user_email = result.stdout.strip()
    if "@" not in user_email:
        # Fall back to a fixed sentinel so the orchestrator identity is still
        # distinguishable from the user identity in audit logs.
        local, domain = "orchestrator", "tp-pr-fix.local"
    else:
        local, domain = user_email.split("@", 1)
    return {
        "GIT_COMMITTER_EMAIL": f"orchestrator+{local}@{domain}",
        "GIT_COMMITTER_NAME": "tp-pr-fix orchestrator",
    }


def _commit_message(iter_n: int, summary: str) -> str:
    return f"[tp-pr-fix iter-{iter_n}] {summary}"


def _check_collaborator(pr_url: str, user: str) -> str:
    """Returns 'collaborator' | 'non-collaborator' | 'unreachable'.

    `gh api repos/{o}/{r}/collaborators/{u}` exits 0 (204 No Content) when the
    user is a collaborator. On 404, gh exits non-zero with '404' in stderr.
    On 5xx, gh exits non-zero with '5xx' / '503' / 'server error' in stderr.
    Anything else we cannot classify is treated as 'unreachable' (safer than
    silently dropping the comment as non-collaborator).
    """
    owner, repo = _parse_pr_url(pr_url)
    result = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/collaborators/{user}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return "collaborator"
    stderr = (result.stderr or "").lower()
    if "404" in stderr or "not found" in stderr:
        return "non-collaborator"
    if any(s in stderr for s in ("500", "502", "503", "504", "server error", "5xx")):
        return "unreachable"
    return "unreachable"


def _count_diff_lines() -> int:
    """Sum additions + deletions for the most recent commit (HEAD~1..HEAD).

    Matches the unit used by `original_diff_lines` (insertions+deletions from
    `gh pr diff --stat`) so the loop driver's diff-growth guard compares like
    with like. Binary files appear as `-\\t-\\t<path>` in numstat and are
    skipped.
    """
    result = subprocess.run(
        ["git", "diff", "--numstat", "HEAD~1..HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return 0
    total = 0
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            total += int(parts[0]) + int(parts[1])
    return total


def _summary_from_classified(structural: list[dict]) -> str:
    n = len(structural)
    if n == 1:
        phrase = structural[0].get("issue_phrase", "fix")
        return phrase[:120]
    return f"{n} fixes from PR review"


def _has_working_tree_changes() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=False
    )
    return bool(result.stdout.strip())


def _current_branch() -> str:
    """The checked-out branch name, or 'HEAD' when detached."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def _resolve_head_ref(pr_url: str) -> str:
    """Resolve the PR head branch via `gh pr view --json headRefName` (F1).

    Raises ValueError when gh fails or returns an empty ref, so a standalone
    caller surfaces a clear error rather than committing to the wrong branch.
    """
    result = subprocess.run(
        ["gh", "pr", "view", pr_url, "--json", "headRefName", "-q", ".headRefName"],
        capture_output=True,
        text=True,
        check=False,
    )
    head = result.stdout.strip()
    if result.returncode != 0 or not head:
        raise ValueError(
            f"could not resolve PR head ref for {pr_url!r}: {result.stderr.strip()!r}"
        )
    return head


def _ensure_on_head_ref(head_ref: str, loop_mode: bool) -> None:
    """Guarantee the commit lands on the PR head ref (F1).

    - Already on `head_ref` → no-op.
    - Mismatch under loop/`--auto` (`loop_mode=True`) → `git checkout <head_ref>`
      (the loop owns the worktree; auto-checkout is intended).
    - Mismatch standalone → raise HeadRefMismatch with an actionable message;
      never silently mutate the operator's branch.
    """
    current = _current_branch()
    if current == head_ref:
        return
    if loop_mode:
        subprocess.run(["git", "checkout", head_ref], check=True)
        return
    raise HeadRefMismatch(
        f"tp-pr-fix: refusing to commit. Current branch {current!r} is not the "
        f"PR head {head_ref!r}. Check out the PR head (git checkout {head_ref}) "
        f"and re-run, or invoke via /tp-pr-iterate which checks it out automatically."
    )


# ---------- public API ----------


def _auto_strip_after_push(pr_url: str) -> bool:
    """Strip a now-stale `tp:human-approved` after the round-push advanced the head.

    FAIL-OPEN by contract: resolves the post-push head OID (`git rev-parse HEAD`) and
    calls `human_approval.strip_stale_approval(pr_url, new_head_oid)`. ANY error — git
    failure, import failure, gh DELETE failure — is swallowed and False is returned, so
    the strip can NEVER block a fix round. Correctness is guaranteed independently by
    the gate-time SHA-equality currency re-check, not by this convenience strip. Mirrors
    `skills/tp-merge-from-main/scripts/auto_strip_hook.run`.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False,
        )
        new_head_oid = result.stdout.strip()
        if result.returncode != 0 or not new_head_oid:
            return False
        from human_approval import strip_stale_approval  # noqa: E402 (lazy, _shared/)

        return strip_stale_approval(pr_url, new_head_oid)
    except Exception:
        return False


def run_round(
    design: str,
    pr_url: str,
    iteration: int,
    classified: list[dict],
    head_ref: str | None = None,
    loop_mode: bool = False,
) -> dict:
    """Execute one end-to-end fix round. See module docstring for contract.

    `head_ref` is the PR head branch the commit must land on (F1). When None
    (standalone convenience) it is resolved from the PR via
    `gh pr view --json headRefName`. `loop_mode=True` (loop driver / `--auto`)
    auto-checks-out the head on a mismatch; standalone refuses via
    HeadRefMismatch rather than mutating the operator's branch.
    """
    fixes_deferred: list[dict] = []
    gated: list[dict] = []

    # 1. Identity-gate every commenter. Trusted requested-reviewer bots (e.g.
    #    Copilot) pass without the collaborators API call — they 404 there but
    #    are legitimate reviewers (F3).
    trusted_bots = _trusted_reviewer_bots()
    for c in classified:
        if c["reviewer"].lower() in trusted_bots:
            gated.append(c)
            continue
        verdict = _check_collaborator(pr_url, c["reviewer"])
        if verdict == "collaborator":
            gated.append(c)
        elif verdict == "non-collaborator":
            fixes_deferred.append(
                {"comment_id": c["comment_id"], "reason": "non-collaborator"}
            )
        else:  # unreachable
            fixes_deferred.append(
                {"comment_id": c["comment_id"], "reason": "identity-gate-unreachable"}
            )

    # 2. Filter to structural; defer the rest.
    structural: list[dict] = []
    for c in gated:
        if c.get("verdict") == "structural":
            structural.append(c)
        elif c.get("verdict") == "minor":
            fixes_deferred.append(
                {"comment_id": c["comment_id"], "reason": "minor-only"}
            )
        else:
            fixes_deferred.append(
                {"comment_id": c["comment_id"], "reason": "unclear-verdict"}
            )

    # No actionable comments OR no changes in the working tree → return cleanly.
    # This early-exit is BEFORE the head-ref resolution/checkout below, so a
    # no-op round never touches the branch or makes a network call (F1).
    if not structural or not _has_working_tree_changes():
        return _make_envelope(iteration, [], fixes_deferred, "no-applicable-fixes", 0)

    # 2.5. Target the PR head ref, not the currently-checked-out branch (F1).
    #      Standalone: refuse on mismatch. Loop/--auto: auto-checkout the head.
    if head_ref is None:
        head_ref = _resolve_head_ref(pr_url)
    _ensure_on_head_ref(head_ref, loop_mode)

    # 3. Commit (env override) the changes the caller's Agent() prose wrote.
    summary = _summary_from_classified(structural)
    msg = _commit_message(iteration, summary)
    env = {**os.environ, **_resolve_committer_env()}
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-m", msg], env=env, check=True)
    diff_lines = _count_diff_lines()

    # 4. Push.
    subprocess.run(["git", "push"], check=True)

    # 4.5. Auto-strip a now-stale human approval (D2, fail-OPEN). The round-push just
    #      advanced the PR head, so any prior `tp:human-approved` label was approving
    #      the OLD head and is stale. Mirror /tp-merge-from-main step 7: call the strip
    #      hook with the post-push head OID. FAIL-OPEN — a strip failure must NEVER
    #      block the round (the gate-time SHA-equality re-check is the fail-closed
    #      backstop). See skills/_shared/human_approval.strip_stale_approval.
    _auto_strip_after_push(pr_url)

    # 5. Label.
    ensure_pr_label(pr_url, _FIX_LABEL)

    fixes_applied = [
        {"comment_id": c["comment_id"], "summary": c.get("issue_phrase", "")[:200]}
        for c in structural
    ]
    return _make_envelope(iteration, fixes_applied, fixes_deferred, "applied", diff_lines)


def _make_envelope(
    iteration: int,
    fixes_applied: list[dict],
    fixes_deferred: list[dict],
    verdict: str,
    diff_lines_added: int,
) -> dict:
    return {
        "schema": "tp-pr-fix/v1",
        "iteration": iteration,
        "fixes_applied": fixes_applied,
        "fixes_deferred": fixes_deferred,
        "verdict": verdict,
        "diff_lines_added": diff_lines_added,
    }
