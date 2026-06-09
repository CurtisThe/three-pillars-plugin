"""label_manager.py — idempotent PR-label ensure for tp-pr-fix.

`ensure_pr_label(pr_url, label)` makes sure `label` is on the PR identified
by `pr_url`. Idempotent and label-creation-safe:

1. `gh pr view <pr_url> --json labels` — if the label is already present,
   return immediately. This is the noop path that lets callers invoke
   `ensure_pr_label` once per fix round without rate-limit anxiety. `gh pr
   view` is read-only and works on every repo (unlike `gh pr edit` — step 2).
2. Else add the label via the REST endpoint
   `gh api repos/{owner}/{repo}/issues/{n}/labels -f labels[]=<label>`.
   We deliberately do NOT use `gh pr edit --add-label`: on a repo with
   **classic Projects** enabled, `gh pr edit` fails with a GraphQL
   "Projects (classic) … deprecated" error on the `projectCards` field
   *before* the label is applied (observed on CurtisThe/three-pillars). The
   REST issues/labels endpoint has no such dependency — the same reason
   `tp-pr-iterate` resolves threads via GraphQL `resolveReviewThread` and the
   `tp-run-full-design` Tier 6 requests the Copilot reviewer via REST, both
   "never `gh pr edit`". If the add reports the label does not exist on the
   repo, run `gh label create <label>` and retry the add once. If the retry
   also fails, raise `RuntimeError` with the stderr.

The function relies entirely on `gh` being authenticated and on the
caller's network reachability — failures are intentionally surfaced so
the orchestrator can decide whether to retry or abort the round.

Only the `subprocess.run` binding is module-local; tests stub it via
`patch("label_manager.subprocess.run", ...)`. URL validation is minimal
(must look like an https URL) — the per-orchestrator allow-list lives in
the sibling `url_allowlist` helper (Task 4.3) which the worker composes
with this one before invoking.
"""

from __future__ import annotations

import json
import subprocess
from urllib.parse import urlparse

# Label constants — consistent with the tp: namespace
READY_FOR_HUMAN_MERGE = "tp:ready-for-human-merge"


def _validate_pr_url(pr_url: str) -> None:
    if not isinstance(pr_url, str) or not pr_url.startswith("https://"):
        raise ValueError(f"pr_url must be an https URL, got: {pr_url!r}")


def _parse_pr_url(pr_url: str) -> tuple[str, str, str]:
    """Parse https://<host>/{owner}/{repo}/pull/{n} -> (owner, repo, number).

    The REST add-label endpoint is keyed on owner/repo/issue-number, not the PR
    URL `gh pr edit` accepts — so we extract them here.
    """
    parts = [p for p in urlparse(pr_url).path.split("/") if p]
    if len(parts) < 4 or parts[2] != "pull" or not parts[3].isdigit():
        raise ValueError(
            f"pr_url must look like .../{{owner}}/{{repo}}/pull/{{n}}, got: {pr_url!r}"
        )
    return parts[0], parts[1], parts[3]


def _label_missing_signal(stderr: str) -> bool:
    """True when gh stderr indicates the label does not exist on the repo.

    The REST add (`gh api issues/{n}/labels`) returns an HTTP 422 validation
    error when a label name is unknown to the repo; other surfaces phrase it
    "not found" / "does not exist". A bare "422" is NOT sufficient — the
    endpoint can also 422 for an unrelated validation reason, and a spurious
    `gh label create` + retry would mask that true error. So a 422 only counts
    as a missing-label signal when the message is about a "label"; the explicit
    "not found" / "does not exist" phrasings stand on their own.
    """
    s = (stderr or "").lower()
    if "not found" in s or "does not exist" in s:
        return True
    return "422" in s and "label" in s


def _add_label_rest(
    owner: str, repo: str, number: str, label: str
) -> subprocess.CompletedProcess:
    """Add `label` to the issue/PR via the REST issues/labels endpoint.

    Uses `gh api` (REST), never `gh pr edit` — see the module docstring for why
    `gh pr edit` is unusable on a classic-Projects repo.

    The body is sent as an EXPLICIT JSON object on stdin (`--input -`) rather than
    relying on gh's `-f 'labels[]=…'` array-from-string-field convention: the
    endpoint requires `{"labels": [...]}` (an array), and an explicit body is both
    unambiguous and directly assertable in tests (the array shape is verified, not
    just the argv).
    """
    body = json.dumps({"labels": [label]})
    return subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"repos/{owner}/{repo}/issues/{number}/labels",
            "--input",
            "-",
        ],
        input=body,
        capture_output=True,
        text=True,
        check=False,
    )


def ensure_pr_label(pr_url: str, label: str) -> None:
    """Ensure `label` is applied to the PR at `pr_url`. Idempotent."""
    _validate_pr_url(pr_url)
    if not isinstance(label, str) or not label:
        raise ValueError(f"label must be a non-empty string, got: {label!r}")
    owner, repo, number = _parse_pr_url(pr_url)

    # Step 1: probe current labels (read-only; works on every repo).
    view = subprocess.run(
        ["gh", "pr", "view", pr_url, "--json", "labels"],
        capture_output=True,
        text=True,
        check=False,
    )
    if view.returncode != 0:
        raise RuntimeError(f"gh pr view failed: {view.stderr.strip()}")

    try:
        payload = json.loads(view.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh pr view returned non-JSON: {exc}") from exc

    existing = [entry.get("name") for entry in payload.get("labels") or []]
    if label in existing:
        return

    # Step 2: add the label via REST (never `gh pr edit` — broken on classic-Projects repos).
    add = _add_label_rest(owner, repo, number, label)
    if add.returncode == 0:
        return

    # Step 3: missing-label recovery — create the label on the repo, retry add.
    if not _label_missing_signal(add.stderr):
        raise RuntimeError(f"gh api add-label failed: {add.stderr.strip()}")

    create = subprocess.run(
        ["gh", "label", "create", label],
        capture_output=True,
        text=True,
        check=False,
    )
    if create.returncode != 0:
        raise RuntimeError(f"gh label create failed: {create.stderr.strip()}")

    retry = _add_label_rest(owner, repo, number, label)
    if retry.returncode != 0:
        raise RuntimeError(
            f"gh api add-label failed after create: {retry.stderr.strip()}"
        )
