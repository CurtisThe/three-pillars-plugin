"""Budget extension: one fixed-step grant per signal, clamped at 2x configured.

Pure, no I/O. `grant` reads the measured round-cap / k-consecutive values from
`state`; `overlay` raises only granted limits and never lowers a configured one.
"""
import copy

# Own copy of round_budget.K_KEY (a test pins them equal).
K_KEY = "consecutive_codereview_structural_rounds"
CLAMP = 2

SIGNAL_KEY = {
    "round-cap": "round_cap",
    "k-consecutive": "k_consecutive",
    "wall-clock": "wall_clock_sec",
    "growth-lines": "growth_multiplier",
    "test-code-ratio": "test_code_ratio",
}

# signal -> (kind, step). "measured": measured + step; "add": configured + step;
# "mul": configured * step.
STEP = {
    "round-cap": ("measured", 2),
    "k-consecutive": ("measured", 2),
    "wall-clock": ("add", 7200),
    "growth-lines": ("mul", 1.5),
    "test-code-ratio": ("mul", 1.5),
}

_MEASURED = {"round-cap": lambda s: s.get("iteration", 0) or 0,
             "k-consecutive": lambda s: s.get(K_KEY, 0) or 0}


def grant(state: dict, signal: str, lim: dict, key, now):
    """Return `(new_state, {"signal","from","to"})`, or `(state, None)` if already granted."""
    if signal not in SIGNAL_KEY:
        raise ValueError(f"signal not grantable: {signal!r}")
    if signal in (state.get("budget_extensions") or {}):
        return state, None
    if signal == "round-cap" and not state.get("reproduced_blockers", 0) > 0:
        raise ValueError("round-cap extension needs a reproduced, Opus-confirmed blocker")
    configured = lim[SIGNAL_KEY[signal]]
    kind, step = STEP[signal]
    if kind == "measured":
        frm = _MEASURED[signal](state)
        new = frm + step
    elif kind == "add":
        frm, new = configured, configured + step
    else:
        frm, new = configured, configured * step
    new = min(new, CLAMP * configured)
    out = copy.deepcopy(state)
    if out.get("budget_extensions") is None:
        out["budget_extensions"] = {}
    out["budget_extensions"][signal] = {"limit": new, "key": key, "at": now}
    return out, {"signal": signal, "from": frm, "to": new}


def overlay(lim: dict, state: dict | None) -> dict:
    """`lim` with each granted key set to `max(configured, recorded)`."""
    out = dict(lim)
    for signal, rec in ((state or {}).get("budget_extensions") or {}).items():
        k = SIGNAL_KEY.get(signal)
        if k is not None and k in out:
            out[k] = max(out[k], rec["limit"])
    return out
