#!/usr/bin/env python3
"""cheap_fix_cli.py — the CLI over cheap_fix.py, run by the tp-pr-fix step 5 stub.

design: cheap-tier-offload (Task 6.3). One JSON line, exit 0 on every verdict; the
caller acts on the output, never on the exit code.

    cheap_fix_cli.py scratch --repo R --head SHA --finding F.json
        -> {eligible, scratch, reason}: the reproducer is run on head inside a fresh
           scratch worktree; an ineligible finding's scratch is removed at once.
    cheap_fix_cli.py adopt --scratch S --fix-worktree W --finding F.json
        -> {ok, oracle, reason, action, files}: the tests are pytest over the fix's
           own tests (`cheap_fix.tests_argv`), never `ci.gate_command`. A bad finding
           file escalates (and the scratch is still removed). A drafter change to the
           fix worktree escalates `drafter-wrote-live-tree` (those paths undone).

An unexpected error is still one JSON line: `scratch` gives eligible false, `adopt`
escalates. A missing or re-run scratch never raises (`cheap_fix.discard` is idempotent).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import cheap_fix  # noqa: E402 — the sibling library


def _load(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return data


def _scratch(args) -> dict:
    try:
        finding = _load(args.finding)
        path = cheap_fix.scratch(args.repo, args.head)
    except (OSError, ValueError, RuntimeError) as exc:
        return {"eligible": False, "scratch": None, "reason": f"cli-error: {exc}"}
    runnable = cheap_fix.valid_reproducer(finding.get("reproducer"))
    outcome = cheap_fix.outcome_on_head(finding, path) if runnable else "no reproducer"
    if cheap_fix.eligible(finding, outcome):
        return {"eligible": True, "scratch": str(path), "reason": ""}
    cheap_fix.discard_quietly(path)
    return {"eligible": False, "scratch": None, "reason": f"not eligible: {outcome}"}


def _adopt(args) -> dict:
    try:
        finding = _load(args.finding)
    except (OSError, ValueError) as exc:
        cheap_fix.discard_quietly(args.scratch)
        return cheap_fix.escalation(f"cli-error: {exc}")
    return cheap_fix.adopt(args.scratch, args.fix_worktree, finding)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="cheap_fix_cli.py", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scratch", help="the scratch worktree for an eligible finding")
    ad = sub.add_parser("adopt", help="judge the scratch fix; apply it on accept")
    for p, flags in ((sc, ("--repo", "--head", "--finding")),
                     (ad, ("--scratch", "--fix-worktree", "--finding"))):
        for flag in flags:
            p.add_argument(flag, required=True)
    args = parser.parse_args(argv)
    try:
        out = (_scratch if args.cmd == "scratch" else _adopt)(args)
    except Exception as exc:  # noqa: BLE001 — the contract is one JSON line on every path
        why = f"cli-error: {type(exc).__name__}: {exc}"
        out = ({"eligible": False, "scratch": None, "reason": why} if args.cmd == "scratch"
               else cheap_fix.escalation(why))
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
