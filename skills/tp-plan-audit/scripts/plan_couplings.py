#!/usr/bin/env python3
"""plan_couplings.py — plan-audit prechecks: file couplings + split targets.

design: run-throughput Part C (detailed-design-part-c.md, §plan_couplings)

`plan_couplings.py <design-dir> [--root .]` reads `<design-dir>/plan.md`,
splits it into task blocks (`task_scope.plan_tasks`) and runs two checks over
each task's **File** field (`plan_files.parse_file_field`):

(a) couplings — `plan_audit.couplings` in `<root>/.three-pillars/config.json`
    is a list of `{"when_new": <glob>, "requires_listed": <path>}`. When any
    `(new)` File item matches `when_new` (fnmatch), the task must also list
    `requires_listed`; otherwise a finding.

(b) split targets — a task likely to exceed the size budget. For each non-
    `(new)` File item that has a cap (`file_size_guard.classify`), flag when
    `lines(File) + growth >= the class's HARD line cap`, where `growth` is the
    task's optional `**Growth**: +N` (default +50). These do NOT fire: a task
    with a `**Split**` line (`<new path>` or `none — <reason>`); a grandfathered
    file declaring `**Growth**` <= 0; exempt (`file_size_guard.is_exempt`) and
    uncapped paths.

Findings print as ONE JSON object on stdout
(`{"findings": [{"task", "check", "category", "confidence", "severity",
"description", "suggested_fix"}]}`, empty list when clean); exit 0 clean,
1 with findings, 2 on a usage error (missing design dir / plan.md, bad config).
Stdlib only.
"""
from __future__ import annotations

import argparse
import fnmatch
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
import plan_files  # noqa: E402
import task_scope  # noqa: E402

DEFAULT_GROWTH = 50
_FILE_RE = re.compile(r"^\*\*File\*\*:\s*(.*)$", re.M)
_GROWTH_RE = re.compile(r"^\*\*Growth\*\*:\s*([+-]?\d+)", re.M)
_SPLIT_RE = re.compile(r"^\*\*Split\*\*:", re.M)


class UsageError(Exception):
    """A usage error (exit 2): missing design dir / plan.md, bad config."""


def _finding(task_id, check, description, suggested_fix) -> dict:
    return {"task": task_id, "check": check, "category": "INCONSISTENT",
            "confidence": "medium", "severity": "medium",
            "description": description, "suggested_fix": suggested_fix}


def _load_config(root: Path) -> dict:
    """`.three-pillars/config.json` at root (absent = {}); a present file that
    is unreadable, not valid JSON, or not an object is a usage error."""
    p = root / ".three-pillars" / "config.json"
    if not p.is_file():
        return {}
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UsageError(f"bad config {p}: {exc}")
    if not isinstance(cfg, dict):
        raise UsageError(f"bad config {p}: not a JSON object")
    return cfg


def _couplings(config: dict) -> list:
    block = config.get("plan_audit")
    c = block.get("couplings") if isinstance(block, dict) else None
    return c if isinstance(c, list) else []


def _coupling_findings(task_id, items, couplings):
    listed = {i["path"] for i in items}
    out = []
    for c in couplings:
        if not isinstance(c, dict):
            continue
        when_new, requires = c.get("when_new"), c.get("requires_listed")
        if not isinstance(when_new, str) or not isinstance(requires, str):
            continue
        if requires in listed:
            continue
        new_hits = (i["path"] for i in items if i["marker"] == "new"
                    and fnmatch.fnmatch(i["path"], when_new))
        hit = next(new_hits, None)
        if hit is None:
            continue
        out.append(_finding(
            task_id, "coupling",
            f"creates `{hit}` (matches coupling `{when_new}`) without listing "
            f"`{requires}` in the same task's File field",
            f"add `{requires}` to this task's File field (or list the new "
            f"path's split target if the coupling does not apply)"))
    return out


def _line_count(fpath: Path) -> int:
    return len(fpath.read_bytes().decode("utf-8", errors="replace").splitlines())


def _split_findings(task_id, items, raw, root, grandfather):
    has_split = _SPLIT_RE.search(raw) is not None
    m = _GROWTH_RE.search(raw)
    growth = int(m.group(1)) if m else None
    growth_used = growth if growth is not None else DEFAULT_GROWTH
    out = []
    for item in items:
        path = item["path"]
        if item["marker"] == "new":          # a new file starts at zero lines
            continue
        if file_size_guard.is_exempt(path):  # frozen exempt path classes
            continue
        cls = file_size_guard.classify(path)
        if cls is None:                      # uncapped extension
            continue
        fpath = root / path
        if not fpath.is_file():              # nothing on disk to grow
            continue
        lines = _line_count(fpath)
        hard = file_size_guard.LINE_CAPS[cls][1]
        if lines + growth_used < hard:
            continue
        if has_split:                        # `**Split**: <path>`/`none — …`
            continue
        if path in grandfather and growth is not None and growth <= 0:
            continue                         # grandfathered + non-growing
        out.append(_finding(
            task_id, "split",
            f"edits `{path}` ({lines} lines) + growth "
            f"{'+' if growth_used >= 0 else ''}{growth_used} "
            f"= {lines + growth_used} >= the {cls} hard cap of {hard} lines, "
            "with no `**Split**` line",
            "add `**Split**: <new path>` (or `**Split**: none — <reason>`) "
            "and keep the growth under the cap"))
    return out


def run_checks(design_dir, root) -> list:
    """Both checks over `<design-dir>/plan.md` → the findings list.

    Raises UsageError on a missing design dir / plan.md or a bad config."""
    design_dir = Path(design_dir)
    root = Path(root)
    plan_md = design_dir / "plan.md"
    if not design_dir.is_dir():
        raise UsageError(f"design dir not found: {design_dir}")
    if not plan_md.is_file():
        raise UsageError(f"no plan.md in design dir: {design_dir}")
    config = _load_config(root)
    couplings = _couplings(config)
    grandfather = file_size_guard.load_grandfather(root)
    tasks = task_scope.plan_tasks(plan_md.read_text(encoding="utf-8",
                                                   errors="replace"))
    findings = []
    for task in tasks:
        task_id = task["id"]
        raw = task.get("raw") or ""
        m = _FILE_RE.search(raw)
        items = plan_files.parse_file_field(
            m.group(1).strip() if m else None)["items"]
        findings += _coupling_findings(task_id, items, couplings)
        findings += _split_findings(task_id, items, raw, root, grandfather)
    return findings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="plan-audit prechecks: file couplings + split targets")
    parser.add_argument("design_dir", help="design dir containing plan.md")
    parser.add_argument("--root", default=".",
                        help="repo root (config + grandfather list; default .)")
    args = parser.parse_args(argv)
    try:
        findings = run_checks(args.design_dir, args.root)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"findings": findings}))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
