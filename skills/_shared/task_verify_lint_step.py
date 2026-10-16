#!/usr/bin/env python3
"""task_verify_lint_step.py — step 7 of ``task_verify.check``: the fragility lint on the diff.

design: fragile-test-prevention (detailed-design-stages §Part C1, phase 5)

After the Targets pass (and ``landed_regression``), ``run`` lints the lines the attempt
adds: ``fragility_lint.check_diff(adir, base, head="HEAD")``, in process, over the
committed text, so the dirty state of the worktree never changes the verdict.

- A gating hit no waiver silences → the failure reason ``fragile: <rule> at <path>:<line>``
  (the first such hit in path, line order); ``check`` raises it as ``_Fail``, and the ladder
  feeds it back like a red test.
- A diff or a ``.py`` file the lint could not judge (exit 2) → one line per cause,
  ``fragility-lint could-not-evaluate: <why>``, appended to the caller's ``logged``. That
  is evidence, never a pass and never a fail by itself: the other steps decide.

The lint runs git in this process, so the repo-local git env is scrubbed for the call: a
caller launched from a git hook still lints the attempt, not the repo the hook is in.
Nothing here imports ``task_verify``. Stdlib only.
"""
from __future__ import annotations

import contextlib
import os
from typing import Iterator

import fragility_lint
import task_scope

COULD_NOT_EVALUATE = "fragility-lint could-not-evaluate: "


@contextlib.contextmanager
def _clean_git_env() -> Iterator[None]:
    """``os.environ`` without the repo-local git env, restored on exit."""
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(task_scope._git_env())
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def run(adir: str, base: str, logged: list[str]) -> str | None:
    """Lint ``base..HEAD`` of the attempt at ``adir``.

    → the failure reason ``fragile: <rule> at <path>:<line>`` for a blocking hit, else
    None with each thing the lint could not judge appended to ``logged`` as
    ``fragility-lint could-not-evaluate: <why>``. A blocking hit is a gating hit whose
    waiver is absent or empty; a waived hit passes."""
    with _clean_git_env():
        result = fragility_lint.check_diff(adir, base, head="HEAD")
    for hit in result.hits:
        if hit.gating and not hit.waived:
            return f"fragile: {hit.rule_id} at {hit.path}:{hit.line}"
    logged.extend(COULD_NOT_EVALUATE + why for why in result.could_not_evaluate)
    return None
