#!/usr/bin/env python3
"""task_eligibility.py — the per-task tier table for one plan.md phase.

design: local-implement-and-review

`classify_phase` puts every task of one phase on a rung — `local` (the cheap
tp-task-worker model), `sonnet` or `opus` — with the reasons, using only the
shared `task_scope` predicates so eligibility, `task_verify` and the Tier 3.5
re-run agree on what a task's declared **Targets** run and which Files it may touch.

Rules, in order (the first that applies sets the tier; every applicable reason
is recorded for the flip-evidence logs). No dispatchable task starts on Opus
(operator 2026-10-09: the local model is strong enough, and Opus starts burned
tokens); Opus is reached only by escalating after a failed attempt:

1. status in `DISPATCH_EXCLUDED` (`task_scope.EXCLUDED` + Done) → `excluded: true`,
   tier `opus`, never dispatched;
2. no node-targetable runner (`no-runner`) or a not-runnable **Targets** field (missing
   or malformed, i.e. non-canonical, or `none`) is a no-oracle row: it is `local` like any
   other, and its recorded reason starts it at `local-xhigh` (`local-medium` when clerical).
   `task_verify` fails every cheap rung `no oracle` for such a row unless an Opus diff
   review accepts the attempt (`no_oracle_review`; `accepted-by-review`, never a test
   pass), so Opus reads a diff instead of doing the task (operator 2026-10-09). The
   **Red** prose is not read;
3. else `local`. A target whose file and directory are both absent
   (`target-missing`: the task creates them), any unparsed File span (`unparsed-file`:
   the Targets still run, only scope is logged) and more parsed Files than `max_files`
   (`too-many-files`) are recorded as reasons but stay `local`. A local row with a
   reason starts at `local-xhigh` (`local-medium` when clerical or clean).

The CLI's mutually exclusive `--route JSON` / `--route-from PATH` add a display-only
`effective` key (via `tier_ladder.route_label`/`route_floor`/`display`) to every row;
without either flag no row gains the key, so today's output is unchanged.

`collides_with` (other dispatchable tasks sharing a written path: a File or a declared
**Targets** file, both of which an attempt may write; paths are normalised, and a File
entry ending in ``/`` covers everything beneath it) never changes the tier:
local rows run strictly serially, so it only splits a parallel sonnet batch.
`new_test` and `has_refactor` are recorded, never gate. Pure: the filesystem is
reached only through the `exists` callable.
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import os
import posixpath
import re
import sys
from collections.abc import Callable
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import local_implement_config  # noqa: E402 — in-repo, stdlib-only sibling
import ladder_rungs  # noqa: E402 — in-repo, stdlib-only sibling
import task_scope  # noqa: E402 — in-repo, stdlib-only sibling
import tier_ladder  # noqa: E402 — in-repo, stdlib-only sibling

# Never dispatched: `task_scope.EXCLUDED` plus Done (a resume must not re-run finished
# tasks). Eligibility-only: the Tier 3.5 re-run keeps `task_scope.rerun_excluded`,
# which re-runs Done tasks on purpose.
DISPATCH_EXCLUDED = task_scope.EXCLUDED | {"Done"}
_PLACEHOLDERS = frozenset({"tbd", "todo", "n/a", "-", "same as above"})
_TRAILING_PUNCT = " \t\n.:;!"
_KIND_RE = re.compile(r"^\*\*Kind\*\*:\s*(\w+)", re.MULTILINE)


def _kind(task: dict) -> str | None:
    """The task's declared ``**Kind**`` (e.g. ``clerical``), or ``None`` if absent."""
    m = _KIND_RE.search(task.get("raw") or "")
    return m.group(1) if m else None


def _has_refactor(fields: dict) -> bool:
    """A **Refactor** field with real content (not empty, a placeholder or "none")."""
    refactor = (fields.get("Refactor") or "").strip().lower().rstrip(_TRAILING_PUNCT)
    return bool(refactor) and refactor not in _PLACEHOLDERS | {"none"}


def _test_reasons(test: dict, exists) -> list[str]:
    """Why the declared **Targets** give no oracle yet: not runnable (missing, malformed
    or ``none``), or a target whose file and directory are both absent."""
    if test["kind"] == "not-runnable":
        return [f"test-not-runnable:{test['reason']}"]
    for path in test["files"]:
        parent = os.path.dirname(path)
        declared_root = not parent and path in test["new_files"]
        if not (exists(path) or declared_root or (parent and exists(parent))):
            return ["target-missing"]
    return []


def _row(task: dict, *, max_files: int, runner_ok: bool, exists) -> dict:
    fields = task.get("fields") or {}
    files, unparsed = task_scope.parse_files(fields.get("File", ""))
    test = task_scope.parse_targets(fields.get("Targets"))
    status = task_scope.task_status(task)
    row = {"task_id": task["id"], "tier": "opus", "reasons": [], "files": files,
           "unparsed_files": unparsed, "test": test, "test_paths": list(test["files"]),
           "collides_with": [], "kind": _kind(task),
           "new_test": bool(test["new_files"]) or any(not exists(p) for p in test["files"]),
           "has_refactor": _has_refactor(fields), "excluded": status in DISPATCH_EXCLUDED}
    if row["excluded"]:
        row["reasons"] = [f"excluded:{status}"]
        row["start_rung"] = ladder_rungs.task_start(row)[0]
        return row
    checks = [] if runner_ok else ["no-runner"]
    checks += _test_reasons(test, exists)
    if unparsed:
        checks.append("unparsed-file")
    too_many = ["too-many-files"] if len(files) > max_files else []
    row["reasons"] = checks + too_many
    row["tier"] = "local"  # a no-oracle row too: an Opus diff review accepts it (module doc)
    row["start_rung"] = ladder_rungs.task_start(row)[0]
    return row


def _written(path: str) -> tuple[str, bool]:
    """``(normalised path, covers its children)``: ``./`` and ``a/../`` forms read the
    same, and an entry ending in ``/`` covers everything beneath it (as in
    ``task_scope.classify_path``)."""
    p = task_scope.norm_path(path)
    return posixpath.normpath(p or "."), p.endswith("/") or p in ("", ".")


def _overlap(a: str, b: str) -> bool:
    """Two written paths collide when they name the same path or one covers the other."""
    (pa, dir_a), (pb, dir_b) = _written(a), _written(b)
    return pa == pb or (dir_a and (pa == "." or pb.startswith(pa + "/"))) \
        or (dir_b and (pb == "." or pa.startswith(pb + "/")))


def classify_phase(plan_text: str, phase: int, *, max_files: int = 3, runner_ok: bool,
                   exists: Callable[[str], bool]) -> list[dict]:
    """One row per task of ``phase``, in plan order (see the module docstring)."""
    rows = [_row(t, max_files=max_files, runner_ok=runner_ok, exists=exists)
            for t in task_scope.phase_tasks(plan_text, phase)]
    live = [r for r in rows if not r["excluded"]]
    for row in live:  # an attempt may write its Files and its declared Targets files
        mine = row["files"] + row["test_paths"]
        row["collides_with"] = [o["task_id"] for o in live if o is not row and any(
            _overlap(a, b) for a in mine for b in o["files"] + o["test_paths"])]
        if row["collides_with"]:
            row["reasons"].append("collides:" + ",".join(row["collides_with"]))
    return rows


# --- Corpus rows and the CLI -------------------------------------------------------

_REPO = Path(__file__).resolve().parents[2]


def corpus_rows(pattern: str, *, max_files: int = 3, runner_ok: bool = True,
                exists: Callable[[str], bool] | None = None) -> list[dict]:
    """`classify_phase` over every phase of every plan matching ``pattern``.

    Each row gains ``design`` and ``phase``. ``exists`` defaults to the path existing
    under this repository's root. No git is read.
    """
    if exists is None:
        exists = lambda p: (_REPO / p).exists()  # noqa: E731
    rows: list[dict] = []
    for plan in sorted(_glob.glob(pattern)):
        text = Path(plan).read_text(encoding="utf-8")
        phases = dict.fromkeys(t["phase"] for t in task_scope.plan_tasks(text)
                               if t.get("phase") is not None)
        for phase in phases:
            for row in classify_phase(text, phase, max_files=max_files, runner_ok=runner_ok,
                                      exists=exists):
                rows.append({"design": Path(plan).parent.name, "phase": phase, **row})
    return rows


def configured_max_files(root) -> int:
    """``local_implement.max_files`` from ``root``'s config (the default when the block
    is absent). A malformed config raises ``ValueError``, never a silent default."""
    cfg = local_implement_config.load(root)
    return int((cfg or local_implement_config.DEFAULTS)["max_files"])


def phase_rows(plan_text: str, phase: int, root, *, max_files: int | None = None) -> list[dict]:
    """`classify_phase` with the CLI's own arguments: ``max_files`` from
    `configured_max_files` unless given, ``runner_ok`` from `task_scope.resolve_runner`,
    ``exists`` against ``root``. A malformed config raises ``ValueError``."""
    root = Path(root)
    if max_files is None:
        max_files = configured_max_files(root)
    runner, _reason = task_scope.resolve_runner(root, None)
    return classify_phase(plan_text, phase, max_files=max_files, runner_ok=runner is not None,
                          exists=lambda p: (root / p).exists())


def _route_from_text(path: str | None) -> str | None:
    """The text at ``path`` (utf-8), or ``None`` on any read/decode failure
    (including ``path is None``) — never an error exit."""
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Per-task tier table for one plan phase.")
    parser.add_argument("plan", help="path to plan.md")
    parser.add_argument("--phase", type=int, required=True)
    parser.add_argument("--max-files", type=int, default=None,
                        help="override local_implement.max_files (default: the config's)")
    parser.add_argument("--root", default=".", help="repository root (default: .)")
    route_group = parser.add_mutually_exclusive_group()
    route_group.add_argument("--route", help="a route result, as a JSON object or string")
    route_group.add_argument("--route-from", help="a decisions.md path to read the route from")
    args = parser.parse_args(argv)
    plan = Path(args.plan)
    if not plan.is_file():
        parser.error(f"plan not found: {plan}")
    try:
        rows = phase_rows(plan.read_text(encoding="utf-8"), args.phase, args.root,
                          max_files=args.max_files)
    except ValueError as exc:
        parser.error(str(exc))

    if args.route is not None or args.route_from is not None:
        route_from_text = _route_from_text(args.route_from)
        label = tier_ladder.route_label(args.route, route_from_text, os.environ)
        for row in rows:
            floored_tier, _floored = tier_ladder.route_floor(row["tier"], label)
            row["effective"] = tier_ladder.display(row["tier"], floored_tier, label)
    print(json.dumps(rows, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
