#!/usr/bin/env python3
"""task_prompt_blocks.py — the ladder blocks a `tp-task-worker` spawn prompt carries.

design: ladder-diagnose-and-size-pins (plan Task 1.2; Behavior B3)

`render` prints, for one plan task, (a) the RETRY FEEDBACK lines of a failed previous
attempt, (b) with `ladder_dir`, the PRIOR ATTEMPT block of the newest salvage record
(plan Task 1.5) and (c) the size block: every **File** path with its line count and line cap, its
char count and char cap, and the headroom on each axis, ending with `SIZE_RULE`. The caps
come from `file_size_guard` (the predicate the pre-commit hook runs), the task block from
`task_scope.phase_tasks` and its **File** list from `task_scope.parse_files`: no second
parser and no second set of cap constants. `size_rows` is the reusable measuring helper.
Stdlib only.

    python3 task_prompt_blocks.py render --plan PLAN --phase N --task ID --root DIR \
        [--check-json C] [--ladder-dir L]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import file_size_guard  # noqa: E402
import task_scope  # noqa: E402

# A path this close to its line cap is marked `at cap` in the block.
AT_CAP_LINES = 10
# Header of the prior-attempt block, and the rule that rides the saved Red's cherry-pick line.
PRIOR_HEADER = "PRIOR ATTEMPT"
KEEP_RULE = "keep it only if it still fails for its stated reason"
# The one rule line the size block ends with; renderer and tests share this constant.
SIZE_RULE = ("over the cap → a new sibling module listed in **File**; "
             "never trim unrelated text, never edit a pin")


def _measure(root: Path, rel: str) -> tuple[int, int]:
    """(lines, chars) of ``rel`` under ``root``; a new or missing path reads as 0."""
    path = Path(root) / rel
    if not path.is_file():
        return 0, 0
    lines, chars, _text = file_size_guard.measure(path)
    return lines, chars


def size_rows(paths, root) -> list[dict]:
    """One measurement row per path: counts, caps and headroom on both axes.

    Caps are the guard's hard caps (`LINE_CAPS`, `char_caps`); a path the guard leaves
    uncapped (another suffix, or an exempt path) has ``None`` caps and headroom.
    """
    root = Path(root)
    framework = file_size_guard.is_framework_tree(root)
    rows = []
    for rel in paths:
        lines, chars = _measure(root, rel)
        cls = file_size_guard.classify(rel)
        capped = cls is not None and not file_size_guard.is_exempt(rel)
        line_cap = file_size_guard.LINE_CAPS[cls][1] if capped else None
        char_cap = file_size_guard.char_caps(rel, framework)[1] if capped else None
        line_headroom = None if line_cap is None else line_cap - lines
        rows.append({
            "path": rel,
            "lines": lines, "line_cap": line_cap, "line_headroom": line_headroom,
            "chars": chars, "char_cap": char_cap,
            "char_headroom": None if char_cap is None else char_cap - chars,
            "at_cap": line_headroom is not None and line_headroom <= AT_CAP_LINES,
        })
    return rows


def _row_line(row: dict) -> str:
    if row["line_cap"] is None:
        return f"{row['path']} lines {row['lines']} chars {row['chars']} uncapped"
    text = (f"{row['path']} lines {row['lines']}/{row['line_cap']} "
            f"headroom {row['line_headroom']} chars {row['chars']}/{row['char_cap']} "
            f"headroom {row['char_headroom']}")
    return text + " at cap" if row["at_cap"] else text


def _task_block(plan_text: str, phase: int, task_id: str) -> dict:
    for task in task_scope.phase_tasks(plan_text, phase):
        if task.get("id") == str(task_id):
            return task
    raise LookupError(f"task {task_id} not found in phase {phase}")


def retry_lines(check: dict | None) -> list[str]:
    """The RETRY FEEDBACK lines of a FAIL verdict; none for a PASS or no verdict."""
    if not check or check.get("verdict") != "FAIL":
        return []
    return ["RETRY FEEDBACK:",
            f"reason: {check.get('reason') or ''}",
            f"test_output_tail: {check.get('test_output_tail') or ''}"]


def _newest_record(ladder_dir, task_id: str) -> dict | None:
    """The newest readable ``<ladder_dir>/<task>.salvage/*.json`` (by mtime), else ``None``."""
    sal = Path(ladder_dir) / f"{task_id}.salvage"
    if not sal.is_dir():
        return None
    stamped = []
    for path in sal.glob("*.json"):
        try:
            stamped.append((path.stat().st_mtime_ns, path.name, path))
        except OSError:
            continue
    for _mtime, _name, path in sorted(stamped, reverse=True):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict):
            return rec
    return None


def _file_line(row) -> str:
    try:
        return _row_line(row)
    except (KeyError, TypeError):
        return str(row.get("path", row)) if isinstance(row, dict) else str(row)


def _digest_lines(digest) -> list[str]:
    digest = digest if isinstance(digest, dict) else {}
    test = digest.get("test") if isinstance(digest.get("test"), dict) else {}
    out = ["digest:"]
    if test.get("command"):
        out.append(f"  test: {test['command']}")
        out.extend(f"    {ln}" for ln in str(test.get("output_tail") or "").splitlines())
    files = [_file_line(row) for row in digest.get("files") or []]
    calls = [f"{c.get('name')}: {c.get('summary')}"
             for c in digest.get("calls") or [] if isinstance(c, dict)]
    for title, rows in (("files touched:", files), ("last calls:", calls)):
        if rows:
            out.append(f"  {title}")
            out.extend(f"    {row}" for row in rows)
    return out


def prior_lines(ladder_dir, task_id: str) -> list[str]:
    """The PRIOR ATTEMPT block of the newest salvage record; none when there is no record.

    Depends on the record alone, so a retry and an escalation spawn get the same block.
    The Red and patch lines appear only when the record has them.
    """
    rec = _newest_record(ladder_dir, task_id) if ladder_dir else None
    if rec is None:
        return []
    out = [f"{PRIOR_HEADER} ({rec.get('attempt_id') or 'unknown'}) failed; its work was saved:"]
    if rec.get("red_sha"):
        sha = rec["red_sha"]
        out.append(f"red: {sha} — git cherry-pick {sha}; {KEEP_RULE}")
    if rec.get("patch"):
        out.append(f"patch: {rec['patch']}")
    return out + _digest_lines(rec.get("digest"))


def render(plan_text: str, phase: int, task_id: str, root, check: dict | None = None,
           ladder_dir=None, record_check: bool = True) -> str:
    """The prompt blocks for one task: retry feedback (a FAIL ``check`` only), the PRIOR
    ATTEMPT block (a salvage record under ``ladder_dir`` only), then the size block, whose
    last line is `SIZE_RULE`."""
    task = _task_block(plan_text, phase, task_id)
    paths, _unparsed = task_scope.parse_files((task.get("fields") or {}).get("File", ""))
    if not (isinstance(check, dict) and check.get("verdict") == "FAIL") and ladder_dir and record_check:
        rec = _newest_record(ladder_dir, str(task_id)) or {}
        saved = rec.get("check")
        check = dict(saved, verdict="FAIL") if isinstance(saved, dict) else None
    out = retry_lines(check) + prior_lines(ladder_dir, str(task_id))
    out.append("SIZE CAPS (hard caps from file_size_guard):")
    out.extend(_row_line(row) for row in size_rows(paths, root))
    out.append(SIZE_RULE)
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="print the retry + size blocks for one task")
    r.add_argument("--plan", required=True)
    r.add_argument("--phase", type=int, required=True)
    r.add_argument("--task", required=True)
    r.add_argument("--root", default=".")
    r.add_argument("--check-json", default=None,
                   help="the previous attempt's task_verify check JSON")
    r.add_argument("--ladder-dir", default=None,
                   help="the ladder dir holding <task>.salvage/ records of discarded attempts")
    args = ap.parse_args(argv)
    try:
        plan_text = Path(args.plan).read_text(encoding="utf-8")
        check, record_check = None, True
        if args.check_json:
            try:
                check = json.loads(Path(args.check_json).read_text(encoding="utf-8"))
                if not isinstance(check, dict):
                    raise ValueError("not a JSON object")
            except (OSError, ValueError) as exc:
                print(f"task_prompt_blocks: --check-json dropped: {exc}", file=sys.stderr)
                check, record_check = None, False
        print(render(plan_text, args.phase, args.task, Path(args.root), check,
                     args.ladder_dir, record_check))
    except (OSError, ValueError, LookupError) as exc:
        print(f"task_prompt_blocks: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
