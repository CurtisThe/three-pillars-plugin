"""task_verify_load.py — the ``task_verify`` CLI's attempt-record and task-row loaders.

design: local-implement-and-review

Split out of ``task_verify.py`` (file-size cap). ``CliError`` is the CLI's exit 2 with
``{"error": ..., **extra}``. Stdlib only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import task_attempts
import task_eligibility


class CliError(Exception):
    """Exit 2 with ``{"error": ..., **extra}``."""

    def __init__(self, error: str, **extra):
        self.payload = {"error": error, **extra}
        super().__init__(error)


def load_attempt(root, attempt_id: str) -> dict:
    """The record for ``<slug>/<task>-<nonce>`` in ``root``'s common dir."""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", attempt_id or "") or ".." in attempt_id:
        raise CliError("unknown-attempt", attempt_id=attempt_id)
    path = Path(task_attempts.common_dir(root), task_attempts.RECORDS, attempt_id + ".json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CliError("unknown-attempt", attempt_id=attempt_id, detail=str(exc)) from exc


def task_row(attempt: dict, plan: str, phase: int, root) -> dict:
    """The eligibility row for the attempt's task, resolved against the attempt tree."""
    adir = Path(attempt["attempt_dir"])
    text = Path(root, plan).read_text(encoding="utf-8")
    try:  # the same tier rule the dispatcher's table used (impl-audit-1 #7)
        max_files = task_eligibility.configured_max_files(root)
    except ValueError as exc:
        raise CliError("config-invalid", detail=str(exc)) from exc
    rows = task_eligibility.classify_phase(text, phase, max_files=max_files, runner_ok=True,
                                           exists=lambda p: (adir / p).exists())
    for row in rows:
        if row["task_id"] == attempt.get("task_id"):
            return row
    raise CliError("unknown-task", task_id=attempt.get("task_id"), plan=plan, phase=phase)
