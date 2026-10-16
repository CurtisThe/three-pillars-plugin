#!/usr/bin/env python3
"""model_policy.py — the `models` config reader, validator and alias map.

Policy point for which model each role runs on (design: consumer-repo-parity,
Phase 7). `model_for` returns the validated config value else the default;
`validate_models` drops an out-of-vocabulary value with one warning; `agent_alias`
maps a model to the Agent enum. The design-run fable warning + log entry lives in
the sibling `fable_notice` module, not here.
No `inherit`, no `audit` role; `fable` is an explicit `design_run` value, never a
default (operator ruling 2026-09-26). Stdlib-only; imports no other project module.

This is the ONE model source (seat ruling 13, hybrid-routing-hardening): the
`design_run` default below is the only non-test home of the launch-model
literal, and every hybrid launcher resolves through `model_for("design_run",
cfg)`. The default is `sonnet[1m]` (`opus[1m]` stays a valid override) because a bare `opus` behind the
claude-hybrid router gets a 200k window and design runs compact on turn one.
"""
from __future__ import annotations

import fnmatch
import re

AGENT_ALIASES = ("opus", "sonnet", "haiku", "fable")
# The Agent `model=` enum. Four roles; no `audit` (pinned to Opus).
ROLES = ("review", "fix", "classifier", "design_run")
ENGINE_ROLES = ("council_member", "review_finder", "context_scout", "explainer")  # local-routable

# Defaults per role: Opus except the classifier (sonnet); `fable` never.
# `design_run` carries the 1M-context suffix — a load-bearing launch argv.
DEFAULTS = {
    "review": "opus",
    "fix": "opus",
    "classifier": "sonnet",
    "design_run": "sonnet[1m]",
}

# `design_run` may be an alias or a lowercase `claude-<family>-…` id.
DESIGN_RUN_ID = re.compile(r"^claude-[a-z0-9.-]+$")

# `design_run` only: an optional trailing 1M-context suffix, exactly `[1m]`.
CONTEXT_SUFFIX = "[1m]"

# A full id whose family is itself an alias: `claude-<family>-…`.
CLAUDE_FAMILY = re.compile(r"^claude-([a-z]+)-")

# A trailing `[…]` context suffix (e.g. `[1m]`), stripped by `agent_alias` only.
BRACKET_SUFFIX = re.compile(r"\[[^\]]*\]$")

# A rung is a family or `family-effort` (effort here); families `local`,
# `sonnet`, `opus` (ladder order, cheap to Opus; every rung spawns its variant).
RUNG_EFFORTS = ("medium", "xhigh")


def _design_run_ok(value) -> bool:
    if not isinstance(value, str):
        return False
    base = value[: -len(CONTEXT_SUFFIX)] if value.endswith(CONTEXT_SUFFIX) else value
    return base != "inherit" and (
        base in AGENT_ALIASES or DESIGN_RUN_ID.match(base) is not None
    )


def _warning(role: str, value) -> str:
    return (
        f"config: dropped models.{role} ({value!r}) — legal values: "
        f"{' or '.join(AGENT_ALIASES)}"
        + (
            ", or claude-<family>-… (lowercase); either optionally suffixed "
            "[1m]" if role == "design_run" else ""
        )
    )


def validate_models(block) -> tuple[dict, list[str]]:
    """Return a validated copy of a `models` block plus one warning per drop.

    `review`/`fix`/`classifier` must be an `AGENT_ALIASES` member; `design_run`
    an alias or `claude-[a-z0-9.-]+` id, optionally followed by exactly `[1m]`,
    never `inherit`. Non-dict -> `({},[])`.
    """
    if not isinstance(block, dict):
        return {}, []
    kept: dict = {}
    warnings: list[str] = []
    for role in ROLES:
        if role not in block:
            continue
        value = block[role]
        ok = _design_run_ok(value) if role == "design_run" else (
            isinstance(value, str) and value in AGENT_ALIASES
        )
        if ok:
            kept[role] = value
        else:
            warnings.append(_warning(role, value))
    return kept, warnings


def model_for(role: str, config) -> str:
    """Return the validated `config["models"][role]`, else `DEFAULTS[role]`.

    `config` may be None or miss the key (fall back to defaults); raises
    `ValueError` for a role outside `ROLES` (there is no `audit`).
    """
    if role not in ROLES:
        raise ValueError(
            f"unknown model role: {role!r} — roles: {', '.join(ROLES)} "
            "(there is no audit role; audit dispatches stay pinned to opus)"
        )
    block = config.get("models") if isinstance(config, dict) else None
    validated, _ = validate_models(block)
    return validated.get(role, DEFAULTS[role])


def rung_model(rung: str, local_cfg: dict | None) -> str:
    """The ONE rung→model map (design: run-throughput).

    ``rung`` is a family or ``family-effort`` with the family one of
    ``local``, ``sonnet``, ``opus`` (the ladder order) and the effort in
    ``RUNG_EFFORTS``. ``local`` → ``local_cfg["model"]``; ``sonnet`` →
    ``local_cfg["fallback_model"]``; ``opus`` → ``"opus"`` (its spawned
    ``tp-task-worker-opus-*`` variant; needs no ``local_cfg``). An unknown family, an effort outside ``RUNG_EFFORTS``, or
    a missing ``local_cfg``/key for a spawned family is a ``ValueError``.
    Stdlib-only; the ``local_implement`` block is passed in, never read here.
    """
    family, _, effort = str(rung).partition("-")
    if family not in ("local", "sonnet", "opus"):
        raise ValueError(f"unknown rung {rung!r} — rung families: local, sonnet, opus")
    if effort and effort not in RUNG_EFFORTS:
        raise ValueError(
            f"unknown rung {rung!r} — rung efforts: {' or '.join(RUNG_EFFORTS)}"
        )
    if family == "opus":
        return "opus"
    if local_cfg is None or not isinstance(local_cfg, dict):
        raise ValueError(
            f"rung {rung!r} needs the local_implement block "
            "(local_cfg with model / fallback_model)"
        )
    key = "model" if family == "local" else "fallback_model"
    if key not in local_cfg:
        raise ValueError(f"rung {rung!r} needs local_cfg[{key!r}]")
    return local_cfg[key]


# --- effort and the one agent table (run-throughput Part A) -----------------
# The frontmatter / `--effort` vocabulary; RUNG_EFFORTS is a subset.
EFFORTS = ("low", "medium", "high", "xhigh", "max")
ROLE_EFFORT = {"design_run": "high", "review": "high", "phase-check": "medium"}  # review: the floor; round 1 runs -deep


def effort_for(role: str) -> str:
    """The effort for a `ROLE_EFFORT` role; `ValueError` for any other."""
    if role not in ROLE_EFFORT:
        raise ValueError(f"no effort for role {role!r} — roles: {', '.join(ROLE_EFFORT)}")
    return ROLE_EFFORT[role]


PINNED = "opus"  # the gate/audit pin; not configurable (there is no audit role)
# agent name or fnmatch glob → (dispatch role, model source, effort). A source is
# PINNED, `role:<r>` (model_for), `rung:<r>` (rung_model) or `cheap` (local else sonnet).
AGENTS = {
    "tp-generator": ("generator", PINNED, "high"),
    "tp-worker": ("phase-worker", "sonnet", "high"),  # strata-spend-leaks 2.1: Opus only on a retry (SKILL.md)
    "tp-readonly-auditor": ("reader", PINNED, "high"),
    "council-*-medium": ("audit-member", "cheap", "medium"),  # Strata-only variant; first glob wins
    "council-*": ("audit-member", "cheap", "high"),
    "tp-impl-auditor": ("impl-audit", PINNED, "xhigh"),
    "tp-certifier": ("certify", PINNED, "xhigh"),
    "tp-phase-checker": ("phase-check", PINNED, "medium"),  # review-convergence 8.2
    "tp-review-confirmer": ("review", "role:review", ROLE_EFFORT["review"]),
    "tp-review-confirmer-deep": ("review", "role:review", "xhigh"),  # round 1 (angles.py)
    "tp-review-confirmer-medium": ("review_finder", "cheap", "medium"),  # Strata-only; not `review` (floor)
    "tp-runbook": ("runbook", "rung:local", "medium"),
    "tp-spawn-host": ("spawn-host", "sonnet", "low"),  # fixed-Sonnet spawn shell, never routed
    "tp-drafter": ("drafter", "rung:local", "medium"),  # cheap-tier model slots
    "tp-drafter-xhigh": ("drafter", "rung:local", "xhigh"),
    "tp-task-worker": ("task", PINNED, "xhigh"),  # the fail-safe base
    "tp-finalizer": ("finalizer", "fable", "high"),  # fable literal source, never a default
    "tp-explainer": ("explainer", "sonnet", "medium"),  # drafts; engine via explain_engine
}
FINALIZER_FALLBACK = {"model": "opus", "effort": "xhigh"}  # Behavior 4: log `finalizer-fallback`
GATE_ROLES = ("impl-audit", "certify", "review", "phase-check")  # Behavior 5
_TASK_PREFIX = "tp-task-worker-"


def _is_glob(name: str) -> bool:
    return any(c in name for c in "*?[")


def _entry(name: str) -> tuple:
    """The AGENTS row for `name`: exact; else the variant rule — a rung
    `<family>-<effort>` with a `rung_model` (every rung spawns its variant) is
    `("task", "rung:<rung>", <effort>)`; else a glob."""
    if name in AGENTS:
        return AGENTS[name]
    rung = name[len(_TASK_PREFIX):] if name.startswith(_TASK_PREFIX) else ""
    try:
        spawned = "-" in rung and rung_model(rung, {"model": 1, "fallback_model": 1})
    except ValueError:
        spawned = False
    if spawned:
        return ("task", f"rung:{rung}", rung.rsplit("-", 1)[1])
    for pattern, row in AGENTS.items():
        if _is_glob(pattern) and fnmatch.fnmatchcase(name, pattern):
            return row
    raise KeyError(f"agent {name!r} has no model_policy.AGENTS entry")


def agent_spec(name: str, config=None, local_cfg=None) -> dict:
    """`{role, model, effort}` (`KeyError` when unknown). PINNED is itself,
    `role:<r>` is `model_for(r, config)`, `rung:<r>` is `rung_model(r,
    local_cfg)` (a missing one: ValueError); `cheap` is local's alias, else sonnet."""
    role, source, effort = _entry(name)
    kind, _, arg = source.partition(":")
    model = (model_for(arg, config) if kind == "role"
             else rung_model(arg, local_cfg) if kind == "rung"
             else (agent_alias(local_cfg["model"]) if local_cfg else "sonnet") if kind == "cheap"
             else source)
    return {"role": role, "model": model, "effort": effort}


def role_agent(role: str) -> str | None:
    """The non-glob AGENTS entry for `role`, else None."""
    return next((n for n, row in AGENTS.items() if row[0] == role and not _is_glob(n)), None)


def floor(role: str, config=None) -> dict | None:
    """A GATE_ROLES role's `{model, effort, configurable}`, from its role
    agent (`configurable`: a `role:` model source); else None."""
    if role not in GATE_ROLES:
        return None
    name = role_agent(role)
    spec = agent_spec(name, config)
    configurable = AGENTS[name][1].startswith("role:")
    return {"model": spec["model"], "effort": spec["effort"], "configurable": configurable}


def agent_alias(model) -> str | None:
    """Map a model to its Agent-enum alias, or None.

    An alias passes through; a `claude-<family>-…` id maps to its family when
    that family is in `AGENT_ALIASES`. Input is normalised `strip().lower()`
    and a trailing `[…]` suffix is dropped first, so `'Opus'` and `'opus[1m]'`
    -> `'opus'`. Anything else (a local model) is None. This is the one family
    normaliser; the fleet and override-warning checks delegate to it.
    """
    m = BRACKET_SUFFIX.sub("", str(model).strip().lower()).strip()
    if m in AGENT_ALIASES:
        return m
    family = CLAUDE_FAMILY.match(m)
    if family is not None and family.group(1) in AGENT_ALIASES:
        return family.group(1)
    return None
