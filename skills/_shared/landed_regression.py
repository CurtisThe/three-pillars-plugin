"""landed_regression.py — landed-target regression for ``task_verify check`` (Task 2.10).

design: run-throughput (operator amendment 2, attempt integrity §A1)

After a row's own Targets pass, the Targets of every already-landed task whose Files the
attempt changed are re-run on the attempt. A node that is newly red (green at base) is
``regression <node>``; one red at base too is logged ``pre-existing red <node>``, never a
FAIL. Nothing here imports ``task_verify`` (``run`` and ``fail`` are injected). Stdlib only.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import junit_verdict
import task_attempts
import task_eligibility
import task_scope


def landed_rows(plan_text: str, phase: int, task_id: str, *, max_files: int,
                at_base) -> list[dict]:
    """Eligibility rows of phases 1..``phase`` before ``task_id`` in plan order, not
    excluded (a Done ✓ row is admitted too — it landed and must stay re-checkable; a
    ``Blocked`` / operator-run row stays skipped), with runnable Targets that all exist
    at the base (``at_base(path)``)."""
    out = []
    for ph in range(1, int(phase) + 1):
        rows = task_eligibility.classify_phase(plan_text, ph, max_files=max_files,
                                               runner_ok=True, exists=at_base)
        for row in rows:
            if ph == int(phase) and row["task_id"] == task_id:
                return out
            paths = task_scope.row_test_paths(row)
            landed = not row["excluded"] or row["reasons"] == ["excluded:Done"]
            if (landed and paths and row["test"].get("kind") in (
                    "pytest-node", "pytest-file") and all(at_base(p) for p in paths)):
                out.append(row)
    return out


def targets_of(row: dict) -> list[str]:
    """Every declared node target, then every declared target file (as step 6 runs them)."""
    nodes = [s for s in (row.get("test") or {}).get("specs") or [] if "::" in s]
    return list(dict.fromkeys([*nodes, *task_scope.row_test_paths(row)]))


def _touches(files: list[str], changed: list[str]) -> bool:
    return any(c == f or (f.endswith("/") and c.startswith(f)) for f in files for c in changed)


def overlapping(rows: list[dict], changed: list[str], own: list[str]) -> list[str]:
    """Targets of the rows whose Files intersect ``changed``, minus ``own``, de-duplicated
    in plan order."""
    got = [t for row in rows if _touches(row.get("files") or [], changed)
           for t in targets_of(row)]
    return [t for t in dict.fromkeys(got) if t not in set(own)]


def step(adir: str, targets: list[str], runner: str, timeout: int, res: dict, *,
         run, base_green, fail=RuntimeError) -> None:
    """Run each landed target; the first failed node green at base raises
    ``fail("regression <node>")``; a node red at base too is logged."""
    res["landed_targets"] = list(targets)
    for target in targets:
        failed: list[str] = []

        def go(extra, one):
            argv = task_scope.runner_argv(runner, [*one, *extra])
            res.setdefault("commands", []).append(argv)
            return run(argv, adir, timeout)
        (rc, tail), (kind, _why) = junit_verdict.run_judged(go, target, adir,
                                                            failed_out=failed)
        if rc is None:
            raise fail(f"regression {target} (timeout)")
        if kind == "red" and not failed:
            failed = [target]
        for node in failed:
            if base_green(node):
                res["test_output_tail"] = tail
                res["failing_tests"] = [*res.get("failing_tests", []), node]
                res["failing_targets"] = [target]
                raise fail(f"regression {node}")
            res.setdefault("logged", []).append(f"pre-existing red {node}")


def run_landed(attempt: dict, row: dict, landed: list[dict], runner: str, timeout: int,
               res: dict, *, run, fail) -> None:
    """The ``_verdict`` hook: overlapping landed Targets, re-run on the attempt."""
    targets = overlapping(landed, res["changed_files"], targets_of(row))
    if targets:
        step(str(attempt["attempt_dir"]), targets, runner, timeout, res, run=run,
             base_green=_base_green(attempt, runner, timeout, run), fail=fail)


def _base_green(attempt: dict, runner: str, timeout: int, run):
    """``base_green(node)``: the node passes in a scratch worktree at ``base_sha``; only
    called on a red. A timeout or any error there counts as not green."""
    import task_verify_red_base as rb  # lazy: keeps the import graph light

    def green(node: str) -> bool:
        owner, scratch, branch = rb._scratch(attempt)
        try:
            os.makedirs(os.path.dirname(scratch), exist_ok=True)
            task_attempts._git(owner, "worktree", "add", "-q", "-b", branch, scratch,
                               str(attempt["base_sha"]))
            (rc, _tail), (kind, _why) = junit_verdict.run_judged(
                lambda extra, one: run(task_scope.runner_argv(runner, [*one, *extra]),
                                       scratch, timeout), node, scratch)
            return rc is not None and kind == "pass"
        except (OSError, subprocess.CalledProcessError):
            return False
        finally:
            task_attempts._git(owner, "worktree", "remove", "--force", "--force", scratch,
                               check=False)
            task_attempts._git(owner, "worktree", "prune", check=False)
            task_attempts._git(owner, "branch", "-D", branch, check=False)
    return green


def for_attempt(attempt: dict, plan: str, phase: int, root) -> list[dict]:
    """The ``landed`` rows for an attempt, with the same ``max_files`` as ``task_row``."""
    base, adir = str(attempt["base_sha"]), str(attempt["attempt_dir"])

    def at_base(path: str) -> bool:
        return task_attempts._git(adir, "cat-file", "-e", f"{base}:{path}",
                                  check=False).returncode == 0
    return landed_rows(Path(root, plan).read_text(encoding="utf-8"), phase,
                       str(attempt.get("task_id")),
                       max_files=task_eligibility.configured_max_files(root), at_base=at_base)
