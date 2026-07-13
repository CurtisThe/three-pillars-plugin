"""pipeline_modes.py — mode-axis predicate module for tp-run-full-design.

Provides constants, validation, resolution, and slot-range logic for the
--mode {full|design|plan|build} flag on the autonomous orchestrator.

All functions are pure (no I/O, no subprocess) so they can be tested cheaply
and called from the Slot-0 precondition gate without spending subagent_tokens.

Companion doc: skills/tp-run-full-design/pipeline-modes.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple, Optional, Tuple

# ---------------------------------------------------------------------------
# Module-local slot list (11 slots in pipeline order).
#
# This list extends the briefing DAG's 10-slot subset (skills/_shared/
# html_briefing/tier_sequence.SLOTS, which is pro-tier) by adding pr-iterate
# as Slot 11.  tp-run-full-design is FREE, so we MUST NOT import
# tier_sequence.SLOTS — a free→pro import breaks the core build.  This local
# constant is the single source of truth for slot_range() below.
# ---------------------------------------------------------------------------
_SLOT_NAMES: Tuple[str, ...] = (
    "pickup",           # Slot 1
    "design",           # Slot 2
    "detail",           # Slot 3
    "design-audit",     # Slot 4
    "plan",             # Slot 5
    "plan-audit",       # Slot 6
    "phase-implement",  # Slot 7
    "impl-audit",       # Slot 8
    "design-learn",     # Slot 9
    "PR",               # Slot 10
    "pr-iterate",       # Slot 11  (extends the briefing DAG's 10-slot subset)
)

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

VALID_MODES: Tuple[str, ...] = ("full", "design", "plan", "build")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class InvalidModeError(ValueError):
    """Raised when an invalid mode value is encountered."""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_mode(value: object) -> bool:
    """Return True iff value is one of the four valid mode strings.

    Pure bool predicate — never raises, never does I/O.
    """
    return value in VALID_MODES


def require_mode(value: object) -> str:
    """Return value (str) if valid; raise InvalidModeError otherwise.

    Used at the arg-parse gate (B10) and wherever a caller must fail-closed
    on an invalid mode (e.g. an invalid pickup value with no CLI override).
    """
    if not validate_mode(value):
        raise InvalidModeError(
            f"invalid mode {value!r}; must be one of {VALID_MODES}"
        )
    return str(value)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


class ModeResolution(NamedTuple):
    """Result of resolve_mode_verbose."""

    mode: str
    overrode_pickup: bool
    pickup_value: Optional[str]


def resolve_mode(
    cli_mode: Optional[str] = None,
    pickup_mode: Optional[str] = None,
) -> str:
    """Resolve the effective pipeline mode per the precedence rule:
    CLI > pickup > default "full".

    Edge cases (B7 / B10):
    - If cli_mode is valid: return it immediately, ignoring pickup_mode
      (even if pickup_mode is invalid — valid CLI short-circuits).
    - If cli_mode is absent/None and pickup_mode is invalid: raise
      InvalidModeError (fail-closed on a bad pickup value).
    - If both are absent: return "full" (backward-compatible default, B1).
    """
    if cli_mode is not None:
        # If CLI is provided but invalid, reject it (B10).
        return require_mode(cli_mode)
    if pickup_mode is not None:
        # Fail-closed on an invalid pickup value when no CLI override.
        return require_mode(pickup_mode)
    return "full"


def resolve_mode_verbose(
    cli_mode: Optional[str] = None,
    pickup_mode: Optional[str] = None,
) -> ModeResolution:
    """Like resolve_mode but returns a ModeResolution so the caller can log
    the mode-cli-overrides-pickup decision entry (B7).

    overrode_pickup is True iff both cli_mode and pickup_mode were provided
    and cli_mode won (i.e. the pickup value was ignored).
    """
    # B7: the override is reported only when CLI and pickup DISAGREE — when both
    # are provided, the CLI value is valid, and it differs from pickup. CLI and
    # pickup agreeing is not an override (no spurious mode-cli-overrides-pickup).
    overrode = (
        cli_mode is not None
        and pickup_mode is not None
        and validate_mode(cli_mode)
        and validate_mode(pickup_mode)
        and cli_mode != pickup_mode
    )
    mode = resolve_mode(cli_mode, pickup_mode)
    return ModeResolution(
        mode=mode,
        overrode_pickup=overrode,
        pickup_value=pickup_mode,
    )


# ---------------------------------------------------------------------------
# Slot-range
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModeRange:
    """The slot window and behavioural flags for a resolved mode.

    Fields
    ------
    slots               : ordered tuple of slot names in the range
    start               : first slot name
    stop                : last slot name
    runs_worker         : True iff the range includes phase-implement (Slot 7)
    iterate             : True iff Tier 7 pr-iterate is enabled
    opens_completion_pr : True iff Tier 5.6 closeout and completion PR are run
    """

    slots: Tuple[str, ...]
    start: str
    stop: str
    runs_worker: bool
    iterate: bool
    opens_completion_pr: bool


# Per-mode slot windows (inclusive start/stop over _SLOT_NAMES).
# build includes Tier 5.6 closeout between design-learn and PR, but Tier 5.6
# is not a numbered slot — runs_closeout() governs it separately (Task 1.2).
_MODE_SLOTS: dict[str, Tuple[str, ...]] = {
    "full": _SLOT_NAMES,
    "design": ("design", "detail", "design-audit"),
    "plan": ("plan", "plan-audit"),
    "build": ("phase-implement", "impl-audit", "design-learn", "PR", "pr-iterate"),
}


def slot_range(mode: str) -> ModeRange:
    """Return the ModeRange for the given mode.

    Validates the mode via require_mode so callers cannot pass a garbage value.
    """
    require_mode(mode)
    slots = _MODE_SLOTS[mode]
    runs_worker = "phase-implement" in slots
    iterate = "pr-iterate" in slots
    opens_completion_pr = "PR" in slots
    return ModeRange(
        slots=slots,
        start=slots[0],
        stop=slots[-1],
        runs_worker=runs_worker,
        iterate=iterate,
        opens_completion_pr=opens_completion_pr,
    )


# ---------------------------------------------------------------------------
# Task 1.2 — Precondition table + closeout-scope predicates
# ---------------------------------------------------------------------------

# Required artifacts per mode, checked at the Slot-0 gate before any slot
# dispatches (B5 — fail closed and fail cheap; pure stat calls, zero tokens).
_REQUIRED_ARTIFACTS: dict[str, Tuple[str, ...]] = {
    "full": (),
    "design": (),
    "plan": ("design.md", "detailed-design.md"),
    "build": ("design.md", "detailed-design.md", "plan.md"),
}


def required_artifacts(mode: str) -> Tuple[str, ...]:
    """Return the tuple of artifact filenames required before this mode runs.

    Tuple order is the canonical check order — the precondition gate reports
    missing files in this order.
    """
    require_mode(mode)
    return _REQUIRED_ARTIFACTS[mode]


def check_preconditions(mode: str, design_dir: str) -> list[str]:
    """Check required artifacts under design_dir; return list of missing names.

    Returns an empty list when all preconditions are satisfied.  Uses
    os.path.isfile — pure stat calls, no subprocess, zero subagent_tokens.
    Preserves tuple order from required_artifacts() in the missing list.
    """
    import os as _os
    require_mode(mode)
    missing: list[str] = []
    for name in required_artifacts(mode):
        if not _os.path.isfile(_os.path.join(design_dir, name)):
            missing.append(name)
    return missing


def runs_closeout(mode: str) -> bool:
    """Return True iff the mode includes the Tier 5.6 closeout sequence.

    Closeout (fold candidate→tp/{slug}, learn-verify, tp-design-complete
    archive) runs only when the slot range includes the worker (build/full).
    design/plan modes have no candidate to fold, so they skip closeout and
    open their scoped PR directly from tp/{slug} (B9).
    """
    require_mode(mode)
    return mode in ("build", "full")


# ---------------------------------------------------------------------------
# Task 1.3 — Mode-branched PR-shape function
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PRShape:
    """The title and scope body for the terminal PR slot of a given mode.

    title      : PR title string, or None for build/full (caller keeps its
                 existing "{slug}: {task_title}" completion-PR title path).
    scope_body : Markdown text for the "In this PR / NOT in this PR" block.
    """

    title: Optional[str]
    scope_body: str


def pr_shape(mode: str, slug: str) -> PRShape:
    """Return the PRShape for the given mode and design slug.

    One function, not four templates.  Each mode's "In this PR" / "NOT in
    this PR" lists are the artifacts that mode *produces*, written as literals
    here.  These are deliberately distinct from required_artifacts(), which
    returns a mode's *precondition* inputs (e.g. plan's preconditions are
    design.md + detailed-design.md, but plan's produced artifact is plan.md) —
    so the scope body is not single-sourced from the precondition table.

    build/full return title=None (the completion PR sentinel); the caller
    retains its existing "{slug}: {task_title}" title logic.
    """
    require_mode(mode)

    if mode == "design":
        return PRShape(
            title=f"{slug}: design only",
            scope_body=(
                f"## Scope\n\n"
                f"**In this PR:** design.md, detailed-design.md\n\n"
                f"**NOT in this PR:** plan.md, implementation "
                f"(deferred — a human will own the plan and build phases)"
            ),
        )

    if mode == "plan":
        return PRShape(
            title=f"{slug}: plan only",
            scope_body=(
                f"## Scope\n\n"
                f"**In this PR:** plan.md\n\n"
                f"**NOT in this PR:** implementation "
                f"(deferred — a human will own the build phase)"
            ),
        )

    # build / full — completion PR; caller owns the title
    return PRShape(
        title=None,
        scope_body=(
            f"## Scope\n\n"
            f"**In this PR:** design.md, detailed-design.md, plan.md, "
            f"implementation (all pipeline artifacts)\n\n"
            f"This is the completion PR; the full pipeline ran to Slot 11."
        ),
    )
