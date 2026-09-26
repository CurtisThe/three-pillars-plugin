"""audit_targets.py — the plan audit's mechanical check of every task's **Targets** field.

design: local-implement-and-review (operator rulings on #165, ruling 1 "C3")

The grammar lives in `skills/_shared/task_targets.py` (the one parser `task_scope`, the
eligibility table, `task_verify` and the Tier 3.5 re-run all use), so the audit and the
runtime can never disagree on what a field means:

* a **malformed** field (any grammar error) → ``ERROR`` (exit 1);
* a **missing** field → a ``NOTE``: the task stays valid but is non-canonical (not
  runnable: opus-only, unverified in the re-run). Notes never fail the audit and never
  suppress its pass artifact;
* a target that neither exists nor is marked ``(new)`` by any task of the plan →
  ``WARN`` (paths are relative to the cwd, the repo root, like the File-existence check).
  A ``(new)`` target that exists is fine: a re-audit after the task landed sees it.

Stdlib only.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent.parent.parent / "_shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from task_targets import parse_targets, validate  # noqa: E402 — stdlib-only sibling


def check_targets(tasks, root: Path | str = ".") -> tuple[list[tuple], list[tuple]]:
    """``tasks`` (from ``extract_tasks``) → ``(issues, notes)``, each ``(type, ctx, msg)``."""
    issues: list[tuple] = []
    notes: list[tuple] = []
    parsed: list[tuple[str, dict]] = []
    for t in tasks:
        ctx = f"Task {t['id']}: {t['name']}"
        field = t["fields"].get("Targets")
        if field is None:
            notes.append(("NOTE", ctx, "no **Targets** field: non-canonical (not runnable, "
                          "routed to opus, unverified in the Tier 3.5 re-run)"))
            continue
        errors = validate(field)
        if errors:
            issues.append(("ERROR", ctx, "malformed **Targets**: " + "; ".join(errors)))
            continue
        parsed.append((ctx, parse_targets(field)))
    created = {p for _, res in parsed for p in res["new_files"]}
    base = Path(root)
    for ctx, res in parsed:
        for path in res["files"]:
            if path not in created and not (base / path).exists():
                issues.append(("WARN", ctx, f"target `{path}` does not exist and no task "
                               "marks it (new)"))
    return issues, notes
