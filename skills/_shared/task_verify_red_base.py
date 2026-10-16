"""task_verify_red_base.py — Red-at-base evidence for ``task_verify check`` (logged only).

design: local-implement-and-review (Behavior 5)

For ``pytest-node`` Targets, a scratch worktree (on a named throwaway ``tp-redbase/``
branch, under the dispatcher's ``.tp-scratch/``, removed in ``finally``) at the
attempt's red commit ``red_sha`` (the tests exist there, the implementation does not),
or with no red commit at ``base_sha`` with HEAD's target files overlaid, runs the node
targets through ``task_scope.runner_argv``, **one run per node**, each judged by its own
``--junitxml`` report (`junit_verdict`); the first most severe node wins (amendment A31):

* every node passed → ``green-at-base`` (suspect: a weak or trivial test; the phase review
  reads it first);
* only their file's (or class's) collection failed → ``import-only``;
* a node failed → ``meaningful``; a file-level spec → ``n/a``; a timeout → ``timeout``;
  no or a malformed report, a skip or an absent (maybe deselected) node → ``unverified``;
* an error of its own (a git call, the scratch) → ``error`` via ``logged`` (never raises).

It never changes the verdict. Split out of ``task_verify.py`` to keep it under the cap.
"""
from __future__ import annotations

import os
import uuid

import junit_verdict
import task_attempts
import task_scope

SCRATCH_PREFIX = "tp-redbase-"
BRANCH_PREFIX = "tp-redbase/"


def classify(rc, verdict: tuple[str, str]) -> str:
    """``green-at-base`` | ``import-only`` | ``meaningful`` | ``unverified`` | ``timeout``
    from the run's rc (only a timeout) and its per-node report ``verdict``."""
    kind, why = verdict
    if rc is None:
        return "timeout"
    if kind == "pass":
        return "green-at-base"
    if kind == "red" and why == "collection-error":
        return "import-only"
    return "meaningful" if kind in ("red", "missing") else "unverified"


_RANK = {"meaningful": 0, "import-only": 0, "timeout": 1, "unverified": 1,
         "green-at-base": 2}


def _judge_each(specs, runner: str, scratch: str, timeout: int, run) -> dict:
    """One run per declared node, each classified from its own report; the first most
    severe wins (a red stops the loop): no skip or abort of one node masks another."""
    found = None
    for spec in specs:
        (rc, tail), verdict = junit_verdict.run_judged(
            lambda extra, one: run(task_scope.runner_argv(runner, [*one, *extra]), scratch,
                                   timeout), spec, scratch)
        one = {"red_at_base": classify(rc, verdict), "red_at_base_tail": tail}
        if found is None or _RANK[one["red_at_base"]] < _RANK[found["red_at_base"]]:
            found = one
        if _RANK[found["red_at_base"]] == 0:
            break
    return found


def task_part(task_id) -> str:
    """The task id in a scratch name, with no ``-``: the slug/task boundary stays exact
    for ``task_scratch_sweep`` (a slug may hold ``-``, a task part never does)."""
    return task_attempts._safe(task_id).replace("-", "_")


def _scratch(attempt: dict) -> tuple[str, str, str]:
    """``(owner root, scratch dir, branch)`` for a fresh scratch worktree."""
    owner = os.path.realpath(str(attempt["owner"]["dispatcher_root"]))
    slug = task_attempts.slug_of(str(attempt.get("design_dir_rel") or ""))
    name = f"{slug}-{task_part(attempt.get('task_id'))}-{uuid.uuid4().hex[:8]}"
    path = os.path.join(owner, task_attempts.ATTEMPT_PARENT, SCRATCH_PREFIX + name)
    return owner, path, BRANCH_PREFIX + name.replace(f"{slug}-", f"{slug}/", 1)


def logged(attempt: dict, row: dict, runner: str, timeout: int, *, run,
           red_sha: str | None = None) -> dict:
    """``red_at_base`` that never raises: it runs after the PASS verdict, so any error
    (a failing ``git show`` / ``worktree add``, an OS error) is recorded as
    ``red_at_base: "error"`` with its stderr tail and the PASS stands."""
    try:
        return red_at_base(attempt, row, runner, timeout, run=run, red_sha=red_sha)
    except Exception as exc:  # noqa: BLE001 — evidence only, never gating
        detail = getattr(exc, "stderr", None) or str(exc)
        return {"red_at_base": "error", "red_at_base_tail": str(detail).strip()[-2000:]}


def red_at_base(attempt: dict, row: dict, runner: str, timeout: int, *, run,
                red_sha: str | None = None) -> dict:
    """→ ``{red_at_base, red_at_base_tail}``; ``run(argv, cwd, timeout) -> (rc, tail)``.
    ``red_sha`` set: the scratch is that commit as-is; else ``base_sha`` plus the overlay."""
    test = row.get("test") or {}
    specs = test.get("specs") or []
    if test.get("kind") != "pytest-node" or not specs:
        return {"red_at_base": "n/a", "red_at_base_tail": ""}
    texts = {} if red_sha else {
        path: task_attempts._git(attempt["attempt_dir"], "show", f"HEAD:{path}").stdout
        for path in test.get("files") or []}
    owner, scratch, branch = _scratch(attempt)
    try:
        os.makedirs(os.path.dirname(scratch), exist_ok=True)
        task_attempts._git(owner, "worktree", "add", "-q", "-b", branch, scratch,
                           red_sha or str(attempt["base_sha"]))
        for path, text in texts.items():
            target = os.path.join(scratch, path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(text)
        return _judge_each(specs, runner, scratch, timeout, run)
    finally:
        task_attempts._git(owner, "worktree", "remove", "--force", "--force", scratch,
                           check=False)
        task_attempts._git(owner, "worktree", "prune", check=False)
        task_attempts._git(owner, "branch", "-D", branch, check=False)
