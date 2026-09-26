"""task_scope_corpus.py — `task_scope` over a corpus of plans (read-only report).

design: local-implement-and-review

`corpus_report(pattern)` splits every matching plan.md with the shared task splitter
and runs both field parsers on every task: the **Targets** grammar and the **File**
parser. It counts canonical tasks (a valid Targets field, `none` included) against
non-canonical ones (missing or malformed: not runnable), and `unparsed_files`, the
evidence for later turning the Tier 3.5 case-g escape gate on. Plans written before the
Targets field are non-canonical by construction; no prose is interpreted. Split out of
`task_scope.py` by responsibility; `task_scope.corpus_report` delegates here.

Stdlib only.
"""
from __future__ import annotations

import glob as _glob
from collections import Counter
from pathlib import Path

import task_scope


def corpus_report(pattern: str) -> dict:
    """Parse every plan matching ``pattern`` → counts plus one row per task.

    Returns ``{plans, tasks, canonical, non_canonical, kinds, reasons, unparsed_files,
    rows}``. ``kinds`` and ``reasons`` count the Targets outcome; ``unparsed_files``
    counts tasks whose File field had a span (or prose) the File parser could not resolve.
    """
    rows: list[dict] = []
    plans = sorted(_glob.glob(pattern))
    for plan in plans:
        text = Path(plan).read_text(encoding="utf-8")
        design = Path(plan).parent.name
        for task in task_scope.plan_tasks(text):
            fields = task.get("fields") or {}
            targets = task_scope.parse_targets(fields.get("Targets"))
            paths, unparsed = task_scope.parse_files(fields.get("File", ""))
            rows.append({"design": design, "task_id": task["id"], **targets,
                         "paths": paths, "unparsed": unparsed})
    canonical = sum(1 for r in rows if r["canonical"])
    return {
        "plans": len(plans),
        "tasks": len(rows),
        "canonical": canonical,
        "non_canonical": len(rows) - canonical,
        "kinds": dict(Counter(r["kind"] for r in rows)),
        "reasons": dict(Counter(r["reason"] for r in rows if r["reason"])),
        "unparsed_files": sum(1 for r in rows if r["unparsed"]),
        "rows": rows,
    }
