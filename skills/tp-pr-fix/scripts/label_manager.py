"""label_manager.py — idempotent PR-label ensure for tp-pr-fix.

`ensure_pr_label(pr_url, label)` makes sure `label` is on the PR identified
by `pr_url`. Idempotent and label-creation-safe:

1. `gh pr view <pr_url> --json labels` — if the label is already present,
   return immediately. This is the noop path that lets callers invoke
   `ensure_pr_label` once per fix round without rate-limit anxiety.
2. Else `gh pr edit <pr_url> --add-label <label>`. If `gh` reports the
   label does not exist on the repo (`stderr` containing "not found"),
   run `gh label create <label>` and retry the add-label once. If the
   retry also fails, raise `RuntimeError` with the stderr.

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


def _validate_pr_url(pr_url: str) -> None:
    if not isinstance(pr_url, str) or not pr_url.startswith("https://"):
        raise ValueError(f"pr_url must be an https URL, got: {pr_url!r}")


def _label_missing_signal(stderr: str) -> bool:
    """True when gh stderr indicates the label does not exist on the repo.

    `gh pr edit --add-label` returns variants like:
      "could not find label: foo"
      "label not found"
      "HTTP 422: Label foo not found"
    so a substring match on "not found" is the documented signal per the
    detailed-design.
    """
    return "not found" in (stderr or "").lower()


def ensure_pr_label(pr_url: str, label: str) -> None:
    """Ensure `label` is applied to the PR at `pr_url`. Idempotent."""
    _validate_pr_url(pr_url)
    if not isinstance(label, str) or not label:
        raise ValueError(f"label must be a non-empty string, got: {label!r}")

    # Step 1: probe current labels.
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

    # Step 2: attempt to add the label.
    edit = subprocess.run(
        ["gh", "pr", "edit", pr_url, "--add-label", label],
        capture_output=True,
        text=True,
        check=False,
    )
    if edit.returncode == 0:
        return

    # Step 3: missing-label recovery — create the label on the repo, retry add.
    if not _label_missing_signal(edit.stderr):
        raise RuntimeError(f"gh pr edit --add-label failed: {edit.stderr.strip()}")

    create = subprocess.run(
        ["gh", "label", "create", label],
        capture_output=True,
        text=True,
        check=False,
    )
    if create.returncode != 0:
        raise RuntimeError(f"gh label create failed: {create.stderr.strip()}")

    retry = subprocess.run(
        ["gh", "pr", "edit", pr_url, "--add-label", label],
        capture_output=True,
        text=True,
        check=False,
    )
    if retry.returncode != 0:
        raise RuntimeError(
            f"gh pr edit --add-label failed after create: {retry.stderr.strip()}"
        )
