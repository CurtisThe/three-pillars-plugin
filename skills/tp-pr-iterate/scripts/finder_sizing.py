"""finder_sizing — first-attempt segment sizing from `review.strata_finder_lines_per_cap`.

design: finder-cap-coverage (Task 1.11)

The optional key has no default: absent or invalid, sizing is today's
`finder_segments.plan_segments`. `finder_coverage` re-exports both functions.
`finder_segments` is imported only inside `plan_for_round`: it imports
`finder_coverage`, which imports this module.
"""

from __future__ import annotations


def lines_per_cap(config) -> int | None:
    """`review.strata_finder_lines_per_cap` — an int ≥ 1, else None (it has no default)."""
    raw = ((config or {}).get("review") or {}).get("strata_finder_lines_per_cap")
    return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 1 else None


def plan_for_round(diff, cfg, config) -> dict:
    """The first-attempt segment plan, every segment capped by `lines_per_cap` when set.

    The engage threshold stays `max_lines`/`max_files` (Behavior 6: a diff under the
    limits is never segmented, whatever the figure); below `max_lines` the figure only
    re-cuts an engaged plan, and a smaller `max_lines` can never dis-engage it."""
    import finder_segments  # noqa: PLC0415 — lazy: the two modules import each other

    plan = finder_segments.plan_segments(diff, cfg)
    figure = lines_per_cap(config)
    if plan["engaged"] and figure is not None and figure < cfg["max_lines"]:
        plan = finder_segments.plan_segments(diff, {**cfg, "max_lines": figure})
    return plan
