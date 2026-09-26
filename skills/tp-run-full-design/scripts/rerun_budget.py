"""rerun_budget.py — the Tier 3.5 re-run's phase-wide time budget.

design: local-implement-and-review (impl-audit-1 #5, impl-audit-2 #1)

The wrapper runs inside one orchestrator Bash call of ``BASH_TIMEOUT_MS`` (the tool's
maximum, the ``timeout`` SKILL.md gives the call), after an ``ls-remote`` of at most
``LS_REMOTE_TIMEOUT_S``, so the whole re-run must end well inside it. The budget starts before the
first network or git call. Task runs stop at ``budget - reserve``; the reserve is kept
for the confirm pass and the environment control of the red candidates already seen,
so a slow phase cannot use up the time that proves a real red.

Split out of ``rerun_phase_tests.py`` by responsibility (file-size cap). Stdlib only.
"""
from __future__ import annotations

import subprocess
import time

BASH_TIMEOUT_MS = 600000  # the Bash tool's maximum timeout
BASH_MARGIN_S = 30  # start-up, artifact writes and cleanup around the timed steps
LS_REMOTE_TIMEOUT_S = 60  # the wrapper's SHA cross-check, before the budget starts
PHASE_BUDGET_S = 480
CONFIRM_RESERVE_S = 120  # confirm + control of the candidates seen before the cut
FETCH_TIMEOUT_S = 60  # each best-effort ``git fetch`` before the scratch exists


class OutOfBudget(Exception):
    """The budget (or the task stage's share of it) ran out."""


class Deadline:
    """A per-run ``timeout`` clipped to what is left of the phase-wide budget."""

    def __init__(self, per_run: float, budget: float, *, end: float | None = None):
        self.per_run = per_run
        self.end = time.monotonic() + budget if end is None else end

    def left(self) -> float:
        return self.end - time.monotonic()

    def clip(self) -> float:
        left = self.left()
        if left <= 0:
            raise OutOfBudget()
        return min(self.per_run, left)

    def until(self, reserve: float) -> "Deadline":
        """The same clock, ending ``reserve`` seconds before this one (the task stage)."""
        return Deadline(self.per_run, 0, end=self.end - reserve)


def bounded(call, deadline: Deadline) -> None:
    """Run ``call(timeout)`` (a best-effort git call) with ``timeout`` capped at
    ``FETCH_TIMEOUT_S`` and the time left; a timeout is swallowed, never raised."""
    try:
        call(max(1.0, min(FETCH_TIMEOUT_S, deadline.left())))
    except subprocess.TimeoutExpired:
        pass


def reserve_for(budget: float, reserve: float | None = None) -> float:
    """The confirm/control reserve: ``CONFIRM_RESERVE_S``, at most a quarter of a small
    budget so the task stage always gets most of it."""
    if reserve is not None:
        return min(reserve, budget)
    return min(CONFIRM_RESERVE_S, budget / 4)
