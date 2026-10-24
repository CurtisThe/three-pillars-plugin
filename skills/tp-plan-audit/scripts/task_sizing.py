#!/usr/bin/env python3
"""task_sizing.py — plan-audit sizing checks per task (design: local-sized-tasks 2.1).

`check_task_sizing(tasks, root)` returns ("WARN", "Task <id>: <name>",
"sizing: ...") tuples: cap headroom, production size, read budget, plus the
task_shape and task_closure findings. Fail-open per task.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parents[2] / "_shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)
_SCRIPTS = str(Path(__file__).resolve().parent)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import file_size_guard  # noqa: E402
import plan_couplings  # noqa: E402
import plan_files  # noqa: E402
import sizing_limits  # noqa: E402
import task_closure  # noqa: E402
import task_shape  # noqa: E402
import task_targets  # noqa: E402

_GROWTH = re.compile(r"^\*\*Growth\*\*:\s*([+-]?\d+)", re.M)
_SPLIT = re.compile(r"^\*\*Split\*\*:", re.M)
_TICKS = re.compile(r"`([^`\s]+\.\w+)`")
_FIX = ("name a `**Split**` module, add a preceding refactor task, "
        "or write `**Split**: none — <reason>`")


def _helpers(root: Path) -> list:
    out = list(sizing_limits.TEST_HELPERS) if \
        file_size_guard.is_framework_tree(root) else []
    try:
        cfg = json.loads((root / ".three-pillars" / "config.json")
                         .read_text(encoding="utf-8"))
        extra = cfg.get("plan_audit", {}).get("test_helpers", [])
        if isinstance(extra, list):
            out += [h.strip() for h in extra
                    if isinstance(h, str) and h.strip()]
    except (OSError, ValueError, AttributeError):
        pass
    return out


def _read(root: Path, rel: str):
    p = root / rel
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None


def _task_findings(task: dict, root: Path, helpers: list) -> list[str]:
    fields, raw = task.get("fields", {}), task.get("raw", "")
    m = _GROWTH.search(raw)
    growth = int(m.group(1)) if m else plan_couplings.DEFAULT_GROWTH
    items = plan_files.parse_file_field(fields.get("File"))["items"]
    out: list[str] = []
    if growth > 0 and not _SPLIT.search(raw):
        for it in items:
            cls = file_size_guard.classify(it["path"])
            text = None if it["marker"] == "new" else _read(root, it["path"])
            if cls is None or text is None or file_size_guard.is_exempt(it["path"]):
                continue
            limit = file_size_guard.LINE_CAPS[cls][0] * (
                1 - sizing_limits.SOFT_HEADROOM)
            n = len(text.splitlines())
            if n + growth > limit:
                out.append(f"`{it['path']}` has {n} lines + growth {growth} "
                           f"past the soft cap headroom; {_FIX}")
    if m and growth > sizing_limits.MAX_GROWTH:
        out.append(f"declared growth +{growth} > {sizing_limits.MAX_GROWTH}; "
                   "split into two tasks")
    tgt = fields.get("Targets")
    paths = [i["path"] for i in items] + list(
        task_targets.parse_targets(tgt)["files"]) + _TICKS.findall(str(tgt or ""))
    size = sum(len(t.encode()) for p in set(paths)
               if (t := _read(root, p)) is not None)
    if size / sizing_limits.BYTES_PER_TOKEN > sizing_limits.MAX_READ_TOKENS:
        out.append(f"read budget {size} bytes exceeds "
                   f"{sizing_limits.MAX_READ_TOKENS} tokens; split the task")
    out += task_shape.shape_findings(fields, helpers)
    out += task_closure.closure_findings(task, root)
    return out


def check_task_sizing(tasks, root) -> list[tuple]:
    root = Path(root)
    helpers = _helpers(root)
    results: list[tuple] = []
    for task in tasks:
        label = f"Task {task.get('id')}: {task.get('name')}"
        try:
            msgs = _task_findings(task, root, helpers)
        except Exception as exc:  # fail-open per task
            msgs = [f"check skipped ({type(exc).__name__})"]
        results += [("WARN", label, f"sizing: {m}") for m in msgs]
    return results
