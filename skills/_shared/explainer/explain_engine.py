"""explainer/explain_engine.py — the explainer's drafter engine, check pin and exhaustion map.

Public API:
    ROLE            "explainer" (the `role_engines` key)
    CHECK_MODEL     "opus" — the check model; a constant, not configurable
    CHECKED_KINDS   the kinds that get the Opus check ("pr-brief", "human-escalation")
    resolve_drafter(kind, config, root, *, available=None) -> dict
    on_exhausted(decision) -> str
    needs_check(kind) -> bool

`resolve_drafter` returns `{engine, model, effort, note, busy}` for one explain
kind. `config` is the full repo config. The per-kind `explainer.drafter_override`
wins (opus). Otherwise an explicit `role_engines.explainer: opus` drafts every kind
on opus, with a note (the design's honest switch). Any other value — unset, or the
deprecated `local` — follows the one cheap-engine rule through `role_engine.resolve`
(one-cheap-engine): sonnet without `--local`; under `--local`, Strata when the
backend answers, else sonnet with role_engine's own note (M51, and the deprecation
line for a set key). `busy` is always `fallback`: a busy Strata slot is served on
Sonnet. `available` is the injectable backend probe; None means
`local_backend.available`, looked up at call time.

`on_exhausted` passes `strata_spawn.decide`'s answer through (`sonnet` on exhaustion
since one-cheap-engine) and still maps a legacy `opus` answer to `sonnet`. role_engine
and strata_spawn stay unchanged.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_config  # noqa: E402
import local_backend  # noqa: E402
import role_engine  # noqa: E402

ROLE = "explainer"
CHECK_MODEL = "opus"
CHECKED_KINDS = ("pr-brief", "human-escalation")
DEFAULT_MODEL = "sonnet"
BUSY = "fallback"


def _row(engine: str, model: str, note) -> dict:
    return {"engine": engine, "model": model,
            "effort": role_engine.row_effort(ROLE, engine),
            "note": note, "busy": BUSY}


def _override(kind: str, config) -> str | None:
    """The kept `explainer.drafter_override` engine for `kind`, else None.

    Entries outside `explain_config.OVERRIDE_KINDS` / `OVERRIDE_ENGINES` are
    ignored here; `explain_config.load` is where they are warned about.
    """
    block = config.get(explain_config.CONFIG_KEY) if isinstance(config, dict) else None
    overrides = block.get("drafter_override") if isinstance(block, dict) else None
    if not isinstance(overrides, dict) or kind not in explain_config.OVERRIDE_KINDS:
        return None
    engine = overrides.get(kind)
    return engine if engine in explain_config.OVERRIDE_ENGINES else None


def _explicit(config) -> str | None:
    """The validated `role_engines.explainer` value (unset or invalid -> None)."""
    block = config.get(role_engine.CONFIG_KEY) if isinstance(config, dict) else None
    return role_engine.validate(block)[0].get(ROLE)


def resolve_drafter(kind, config, root, *, available=None) -> dict:
    """`{engine, model, effort, note, busy}` — the drafter for one explain kind."""
    engine = _override(kind, config)
    if engine is not None:
        return _row(engine, engine,
                    f"explainer: drafter_override.{kind}={engine}; drafting on {engine}")
    if _explicit(config) == "opus":
        return _row("opus", "opus", f"role-engine: {ROLE}=opus; drafting on opus")
    # Unset or `local` (deprecated): the drafter follows the run, like every cheap site.
    probe = available if available is not None else local_backend.available
    resolved = role_engine.resolve(ROLE, config, root=root, available=probe)
    if resolved["engine"] == "local":
        return _row("local", resolved["model"], resolved["note"])
    return _row(DEFAULT_MODEL, DEFAULT_MODEL, resolved["note"])


def on_exhausted(decision: str) -> str:
    """`strata_spawn.decide`'s exhausted `opus` -> `sonnet`; other answers pass through."""
    return DEFAULT_MODEL if decision == "opus" else decision


def needs_check(kind) -> bool:
    """True for the kinds that get the Opus check (pr-brief, human-escalation)."""
    return kind in CHECKED_KINDS
