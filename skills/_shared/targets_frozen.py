"""targets_frozen.py — the Targets-freeze invariant from red to green (stages §Part C1).

design: fragile-test-prevention (phase 4)

One task makes a red commit, then a green commit: the first commit in the range is
the red, and no later commit touches a Targets file. A task whose whole diff is its
Targets (a test-only task) is one commit, and it passes with `red_sha` set; a task
with no Targets file keeps one commit and passes with `red_sha=None`.

`check_pair` is the `--local` verdict, run by `task_verify` step 3. `range_audit` applies
the same verdict per task to a phase's commits, paired by the closed subject prefix
`Red: {design} {task}` / `Implement: {design} {task}`: the mechanical check for the
non-`--local` paths, run by `/tp-phase-review`. It reports and never rewrites history.
CLI: `range --plan P --phase N --base REF [--head REF] [--root DIR] [--json]`, exit 0
clean, 1 findings, 2 a bad ref or plan. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import task_scope  # noqa: E402 — the shared git env scrub and row grammar
import task_targets  # noqa: E402 — the **Targets** field grammar


def _rev(adir, *args: str) -> str:
    """A git query in the attempt, with the repo-local env scrubbed (M23)."""
    return subprocess.run(["git", *args], cwd=str(adir),
                          capture_output=True, text=True, check=True,
                          env=task_scope._git_env()).stdout.strip()


def _changed(adir, sha: str) -> list[str]:
    """The paths a commit changed (`--name-only --no-renames`), one line each."""
    return [line for line in
            _rev(adir, "show", "--name-only", "--no-renames", "--format=", sha)
            .splitlines() if line]


def _verdict(shas: list[str], changed, targets: set[str]) -> tuple[str | None, str]:
    """The pair verdict over one task's commits in order: ``(red_sha|None, reason)``.

    ``changed(sha)`` lists the paths a commit touched; it is called only when the
    commit count is small enough to need it. ``""`` = pass.
    """
    if not shas:
        return None, ""
    if len(shas) >= 3:
        return None, f"{len(shas)} commits"

    red_files = changed(shas[0])
    red_targets = sorted(p for p in red_files if p in targets)
    red_other = sorted(p for p in red_files if p not in targets)

    if len(shas) == 1:
        if red_targets and red_other:
            return None, f"targets changed without a red commit: {red_targets[0]}"
        return (shas[0] if red_targets else None), ""

    if red_other:
        return None, f"red commit touches non-Targets file: {red_other[0]}"
    green_targets = sorted(p for p in changed(shas[1]) if p in targets)
    if green_targets:
        return None, f"targets edited after red: {green_targets[0]}"
    return shas[0], ""


def check_pair(adir, base: str, row: dict) -> tuple[str | None, str]:
    """The pair verdict for one attempt: ``(red_sha|None, reason)``, ``""`` = pass.

    Invariant: the first commit in ``base..HEAD`` is the red; no later commit
    touches a Targets file. The Targets set is ``task_scope.row_test_paths(row)``;
    a failing reason names the first sorted offender.
    """
    shas = _rev(adir, "rev-list", "--reverse", f"{base}..HEAD").split()
    return _verdict(shas, lambda sha: _changed(adir, sha),
                    set(task_scope.row_test_paths(row)))


def range_audit(root, base: str, head: str, plan, phase: int,
                design: str | None = None) -> list[dict]:
    """The findings of one phase's commits in ``base..head``: ``[{task_id, reason, shas}]``.

    A task's commits are those whose subject starts ``Red: {design} {task_id}`` or
    ``Implement: {design} {task_id}`` (the id ends at whitespace, so 1.1 never matches
    1.10), in history order. ``design`` defaults to the plan file's directory name. A task
    with no such commit, or whose verdict passes, is not reported. A bad ref raises
    ``subprocess.CalledProcessError``; an unreadable plan raises ``OSError``.
    """
    plan_path = Path(plan)
    design = design or plan_path.resolve().parent.name
    log = _rev(root, "log", "--reverse", "--format=%H%x00%s", f"{base}..{head}")
    commits = [line.split("\0", 1) for line in log.splitlines() if line]
    tasks = task_scope.phase_tasks(plan_path.read_text(encoding="utf-8"), phase)

    findings = []
    for t in tasks:
        prefix = re.compile(rf"(?:Red|Implement): {re.escape(design)} "
                            rf"{re.escape(t['id'])}(?=\s|$)")
        shas = [sha for sha, subject in commits if prefix.match(subject)]
        targets = set(task_targets.parse_targets(t["fields"].get("Targets"))["files"])
        _red, reason = _verdict(shas, lambda sha: _changed(root, sha), targets)
        if reason:
            findings.append({"task_id": t["id"], "reason": reason, "shas": shas})
    return findings


def main(argv: list[str] | None = None) -> int:
    """``range`` subcommand: exit 0 clean, 1 with findings, 2 on a bad ref or plan."""
    ap = argparse.ArgumentParser(prog="targets_frozen")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rng = sub.add_parser("range", help="audit a phase's Red/Implement commit pairs")
    rng.add_argument("--plan", required=True)
    rng.add_argument("--phase", type=int, required=True)
    rng.add_argument("--base", required=True)
    rng.add_argument("--head", default="HEAD")
    rng.add_argument("--root", default=".")
    rng.add_argument("--design", help="default: the plan file's directory name")
    rng.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        findings = range_audit(args.root, args.base, args.head, args.plan,
                               args.phase, args.design)
    except (subprocess.CalledProcessError, OSError) as exc:
        detail = (getattr(exc, "stderr", "") or str(exc)).strip().splitlines()
        print(f"targets_frozen: {detail[0] if detail else exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"findings": findings}, indent=2))
    else:
        for f in findings:
            print(f"task {f['task_id']}: {f['reason']}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
