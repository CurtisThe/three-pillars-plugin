"""round_budget — the /tp-pr-iterate convergence budget.

design: iterate-convergence-budget (Phase 2)

`limits(config)` is the single source of every limit (`pdw.guards.*` overlaid on
`DEFAULTS`; a state's `max_*` fields are informational and never read).
`git_numstat` measures a three-dot diff per path; `split` buckets it into a
growth total (added + deleted) and test/code added lines, excluding
`three-pillars-docs/**`.

Stdlib only; `git_numstat` is the only shell-out and its runner is injectable.
"""

from __future__ import annotations

import fnmatch
import re
from datetime import datetime

import budget_clock
import budget_extension
import finding_class
from review_proof import _default_run_git

WEIGHT_ROUND_CAPS = {"just-do-it": 2, "light": 3, "spike": 3, "full": 3}
DEFAULTS = {"round_cap": 3, "growth_multiplier": 1.5, "test_code_ratio": 3.0,
            "ratio_floor_lines": 100, "growth_floor_lines": 300,
            "k_consecutive": 3, "wall_clock_sec": 14400}

_EXCLUDED_PREFIX = "three-pillars-docs/"
_TEST_BASENAMES = ("test_*.py", "*_test.py", "*.test.*", "*.spec.*")
_TEST_DIRS = frozenset({"tests", "test"})
_BRACE_RENAME = re.compile(r"\{([^{}]*) => ([^{}]*)\}")


class BudgetError(Exception):
    """A budget measurement could not be taken (fail-closed → `budget-error`)."""


def limits(config: dict | None, state: dict | None = None) -> dict:
    """`DEFAULTS` overlaid by numeric `config.pdw.guards.<key>`, then `state`'s extensions."""
    out = dict(DEFAULTS)
    weight = state.get("review_weight") if isinstance(state, dict) else None
    if weight in WEIGHT_ROUND_CAPS:
        out["round_cap"] = WEIGHT_ROUND_CAPS[weight]
    guards = {}
    if isinstance(config, dict):
        pdw = config.get("pdw")
        if isinstance(pdw, dict) and isinstance(pdw.get("guards"), dict):
            guards = pdw["guards"]
    for key in DEFAULTS:
        val = guards.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            out[key] = val
    return budget_extension.overlay(out, state) if state is not None else out


def _new_path(path: str) -> str:
    """The post-rename path of a numstat row (`a => b`, `dir/{a => b}/x`)."""
    if " => " not in path:
        return path
    if "{" in path:
        return _BRACE_RENAME.sub(lambda m: m.group(2), path).replace("//", "/")
    return path.split(" => ", 1)[1]


def _is_test(path: str) -> bool:
    parts = path.split("/")
    base = parts[-1]
    if any(fnmatch.fnmatchcase(base, pat) for pat in _TEST_BASENAMES):
        return True
    return any(seg in _TEST_DIRS for seg in parts[:-1])


def _lines(n) -> int:
    return n if isinstance(n, int) and not isinstance(n, bool) else 0


def split(numstat) -> dict:
    """`{"total": added+deleted, "test_added": n, "code_added": n}`.

    `three-pillars-docs/**` is excluded from every measure; binary rows count 0.
    """
    out = {"total": 0, "test_added": 0, "code_added": 0}
    for path, added, deleted in numstat or ():
        path = _new_path(str(path))
        if path == _EXCLUDED_PREFIX.rstrip("/") or path.startswith(_EXCLUDED_PREFIX):
            continue
        a, d = _lines(added), _lines(deleted)
        out["total"] += a + d
        out["test_added" if _is_test(path) else "code_added"] += a
    return out


def _count(field: str) -> int:
    return int(field) if field.isdigit() else 0


def git_numstat(a, b, *, run_git=None, cwd=".") -> list[tuple[str, int, int]]:
    """Per-path `(path, added, deleted)` for `git -C <cwd> diff --numstat -z a...b`.

    `-z` keeps paths verbatim: without it `core.quotePath` quotes a non-ASCII path
    (`"three-pillars-docs/caf\\303\\251.md"`) and the docs exclusion misses it. A
    rename row is `a\td\t` followed by the old and new paths as their own fields;
    the new path is kept. Raises `BudgetError` when git fails or cannot be run.
    """
    run = run_git or _default_run_git
    try:
        rc, stdout, stderr = run(["git", "-C", str(cwd), "diff", "--numstat", "-z",
                                  f"{a}...{b}"])
    except OSError as exc:
        raise BudgetError(f"git numstat failed: {exc}") from exc
    if rc != 0:
        raise BudgetError(f"git numstat {a}...{b} exited {rc}: {str(stderr).strip()[:200]}")
    rows = []
    fields = iter(str(stdout).split("\0"))
    for field in fields:
        cols = field.split("\t", 2)
        if len(cols) != 3:
            continue
        path = cols[2]
        if not path:  # rename: old path, then new path
            next(fields, None)
            path = next(fields, "")
        rows.append((path, _count(cols[0]), _count(cols[1])))
    return rows


# ---------- tick ----------

K_KEY = "consecutive_codereview_structural_rounds"
BUDGET_FIELDS = ("budget_pr_url", "budget_baseline_head", "budget_baseline_split",
                 "budget_last_head", "budget_last_round", "budget_last_action",
                 "budget_head_blocking", budget_clock.ACTIVE_FIELD,
                 budget_clock.ROUND_START_FIELD, "budget_extensions")
# signal → terminal phase, in check order (budget-error is check 1).
TERMINAL_PHASE = {"budget-error": "budget-exhausted", "wall-clock": "cap-exhausted",
                  "round-cap": "budget-exhausted", "growth-lines": "budget-exhausted",
                  "test-code-ratio": "budget-exhausted", "k-consecutive": "convergence-failure"}


def is_budget_terminal(state: dict) -> bool:
    """`phase` is a budget terminal carrying one of the six budget reasons."""
    reason = state.get("termination_reason")
    return reason in TERMINAL_PHASE and state.get("phase") == TERMINAL_PHASE[reason]


def _reset_for_pr(state: dict, pr_url, now) -> dict:
    """PR key: a different `pr_url` resets the counters, every budget field and a terminal."""
    prior = state.get("budget_pr_url")
    if pr_url and prior and prior != pr_url:
        state.update(iteration=0, started_at=now.isoformat(), original_diff_lines=None)
        state[K_KEY] = 0
        for f in BUDGET_FIELDS:
            state[f] = None
        if is_budget_terminal(state):
            state.update(phase="awaiting-review", termination_reason=None)
    if pr_url:
        state["budget_pr_url"] = pr_url
    return state


def _degraded_only(tally: dict) -> bool:
    return tally.get("blocking", 0) == 0 and tally.get("degraded", 0) > 0


def classify(state: dict, head_sha, ordinal, tally: dict) -> str:
    """`counted` | `completion` | `reshell` | `degraded-rerun` for this review round.

    Counted: a new head, or a new ordinal after a `fix` (a fix that made no commit
    still spends a round). Same head + same ordinal, or no ordinal: a re-shell.
    Same head, new ordinal: a completion, unless degraded-only (then nothing).
    """
    if head_sha != state.get("budget_last_head"):
        return "counted"
    if ordinal is None or ordinal == state.get("budget_last_round"):
        return "reshell"
    if state.get("budget_last_action") == "fix":
        return "counted"
    return "degraded-rerun" if _degraded_only(tally) else "completion"


def _count_round(state: dict, kind: str, head_sha, tally: dict, class_log_path) -> None:
    """Update iteration, `budget_head_blocking`, the k-counter and the class log."""
    if kind == "counted":
        state["iteration"] = state.get("iteration", 0) + 1
        state["budget_head_blocking"] = False  # [Q2] before the k evaluation
    if kind not in ("counted", "completion") or _degraded_only(tally):
        return
    state["reproduced_blockers"] = tally.get("reproduced", 0)
    blocking = tally.get("blocking", 0) > 0
    if not blocking:
        state[K_KEY] = 0
    elif not (kind == "completion" and state.get("budget_head_blocking") is True):
        state[K_KEY] = state.get(K_KEY, 0) + 1
    state["budget_head_blocking"] = blocking
    if class_log_path:
        with open(class_log_path, "a", encoding="utf-8") as fh:
            fh.write(finding_class.class_line(state.get("iteration", 0), head_sha, tally) + "\n")


def _started(state: dict, now):
    """Aware `started_at` datetime, or None when unparseable or naive (check 1)."""
    raw = state.get("started_at")
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else None


def loop_delta(baseline_split, current: dict) -> dict:
    """Per-field `current − baseline` added lines, clamped ≥ 0."""
    base = baseline_split if isinstance(baseline_split, dict) else {}
    return {f: max(0, current.get(f, 0) - (base.get(f) or 0)) for f in ("test_added", "code_added")}


def _growth(state: dict, lim: dict, measure) -> list[tuple[str, object, object]]:
    """Check 4 against the R1 baseline; nothing without a measure or a baseline."""
    if measure is None or state.get("budget_baseline_head") is None:
        return []
    if measure["total"] <= lim["growth_floor_lines"]:  # at/below the floor: not judged
        return []
    out = []
    limit = lim["growth_multiplier"] * max(state.get("original_diff_lines") or 0, 1)
    if measure["total"] > limit:
        out.append(("growth-lines", measure["total"], limit))
    d = loop_delta(state.get("budget_baseline_split"), measure)
    delta_limit = lim["test_code_ratio"] * max(d["code_added"], 1)
    pr_limit = lim["test_code_ratio"] * max(measure["code_added"], 1)
    if (d["test_added"] > delta_limit and d["test_added"] >= lim["ratio_floor_lines"]
            and measure["test_added"] > pr_limit):  # the whole PR must be over the ratio too
        out.append(("test-code-ratio", measure["test_added"], pr_limit))
    return out


def _firing(state: dict, lim: dict, tally: dict, elapsed,
            measure=None) -> list[tuple[str, object, object]]:
    """Every check 2–5 signal that fires now, in check order: `(signal, measured, limit)`."""
    out = []
    if elapsed is not None and elapsed > lim["wall_clock_sec"]:
        out.append(("wall-clock", elapsed, lim["wall_clock_sec"]))
    iteration = state.get("iteration", 0)
    if tally.get("blocking", 0) > 0 and iteration >= lim["round_cap"]:
        out.append(("round-cap", iteration, lim["round_cap"]))
    out.extend(_growth(state, lim, measure))
    k = state.get(K_KEY, 0) or 0
    if k >= lim["k_consecutive"]:
        out.append(("k-consecutive", k, lim["k_consecutive"]))
    return out


def _detail(state, lim, fired, measured=None, limit=None) -> dict:
    signal = fired[0][0] if fired else None
    if fired:
        measured, limit = fired[0][1], fired[0][2]
    return {"iteration": state.get("iteration", 0), "round_cap": lim["round_cap"],
            "signal": signal, "measured": measured, "limit": limit,
            "holding": [f[0] for f in fired]}


def _terminal(state: dict, lim: dict, fired: list) -> tuple[dict, str, dict]:
    signal = fired[0][0]
    phase = TERMINAL_PHASE[signal]
    state.update(phase=phase, termination_reason=signal)
    return state, phase, _detail(state, lim, fired)


def _measure(numstat_fn, review_base, head_sha):
    """`(split, error)`: the three-dot measure, or the BudgetError text; `(None, None)` if absent."""
    if numstat_fn is None or not review_base:
        return None, None
    try:
        return split(numstat_fn(review_base, head_sha)), None
    except BudgetError as exc:
        return None, str(exc) or "numstat failed"


def _holds(state: dict, lim: dict, reason: str, elapsed, measure, err) -> bool:
    """Check 0: does the sticky terminal's own signal still fire under current limits?"""
    if reason == "round-cap":
        return state.get("iteration", 0) >= lim["round_cap"]
    if reason == "k-consecutive":
        return (state.get(K_KEY, 0) or 0) >= lim["k_consecutive"]
    if reason == "wall-clock":
        return elapsed is None or elapsed > lim["wall_clock_sec"]
    if reason == "budget-error":
        return elapsed is None or err is not None
    if measure is None:  # growth signals hold when they cannot be re-measured (R5)
        return True
    return any(f[0] == reason for f in _growth(state, lim, measure))


def tick(state, *, head_sha, pr_url, tally, review_base, config, now, ordinal=None,
         numstat_fn=None, class_log_path=None) -> tuple[dict, str | None, dict]:
    """One budget tick for a review round → `(state, terminal_phase | None, detail)`.

    Order: PR key → check 0 (sticky terminal) → classify and count → checks 1–5.
    Never mutates `state`; the returned copy carries the updated counters and, on a
    terminal, `phase` and `termination_reason`. The wall clock reads the active
    in-round total (`budget_clock`), folded in before check 0.
    """
    st = _reset_for_pr(dict(state), pr_url, now)
    lim = limits(config, st)  # after the reset: a new PR key clears the grant first
    if st.get("started_at") is None:
        st["started_at"] = now.isoformat()  # legacy state: restart the wall clock
    started = _started(st, now)
    active, clock = budget_clock.active_elapsed(st, now)  # in-round time, not loop age
    st.update(clock)
    elapsed = active if started is not None else None  # None: unparseable started_at
    measure, err = _measure(numstat_fn, review_base, head_sha)
    if is_budget_terminal(st):
        reason = st["termination_reason"]
        if _holds(st, lim, reason, elapsed, measure, err):
            others = _firing(st, lim, tally, elapsed, measure)
            counts = {"round-cap": (st.get("iteration", 0), lim["round_cap"]),
                      "k-consecutive": (st.get(K_KEY, 0), lim["k_consecutive"])}
            held = next((f for f in others if f[0] == reason),
                        (reason, *counts.get(reason, (None, None))))
            fired = [held] + [f for f in others if f[0] != reason]
            return _terminal(st, lim, fired)
        st.update(phase="awaiting-review", termination_reason=None)
        st["transitions"] = [*st.get("transitions", []), {
            "phase": "awaiting-review", "at": now.isoformat(),
            "note": f"[budget-lifted] {reason}"}]
    kind = classify(st, head_sha, ordinal, tally)
    _count_round(st, kind, head_sha, tally, class_log_path)
    if started is None:
        return _terminal(st, lim, [("budget-error", st.get("started_at"), None)])
    if err is not None:
        return _terminal(st, lim, [("budget-error", err, None)])
    if measure is not None and kind == "counted" and st.get("budget_baseline_head") is None:
        st.update(original_diff_lines=measure["total"], budget_baseline_head=head_sha,
                  budget_baseline_split={f: measure[f] for f in ("test_added", "code_added")})
    fired = _firing(st, lim, tally, elapsed, measure)
    if fired:
        return _terminal(st, lim, fired)
    return st, None, _detail(st, lim, fired)
