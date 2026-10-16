"""Rung algebra for the escalation ladder: rungs are derived, never tabled.

No model and no effort table lives here; the model comes from
``model_policy.rung_model``. A rung is ``<family>-<effort>``.
"""
import model_policy

SAFE_CLAUDE = "sonnet"

LADDER = ("local", "sonnet", "opus")
RUNGS = tuple(f"{f}-{e}" for f in LADDER for e in model_policy.RUNG_EFFORTS)
LEGACY = {"local": "local-medium", "sonnet": "sonnet-xhigh", "opus": "opus-xhigh"}


def family(rung: str) -> str:
    return rung.rsplit("-", 1)[0]


def effort(rung: str) -> str:
    return rung.rsplit("-", 1)[1]


SPAWN_RUNGS = RUNGS  # every rung spawns its variant, opus-* included (Q4)


def agent(rung: str) -> str | None:
    """Worker agent name for a rung (every rung spawns its variant); None otherwise."""
    return f"tp-task-worker-{rung}" if rung in SPAWN_RUNGS else None


def rank(rung: str) -> tuple[int, int]:
    return (LADDER.index(family(rung)), model_policy.RUNG_EFFORTS.index(effort(rung)))


def quality_next(rung: str) -> str | None:
    """Next effort in the family, else the next family's top effort."""
    fam, eff = family(rung), effort(rung)
    efforts = model_policy.RUNG_EFFORTS
    top = efforts[-1]
    if fam == "local" and eff != top:
        return f"{fam}-{efforts[efforts.index(eff) + 1]}"
    if fam != "local" and eff != top:
        return f"{fam}-{top}"
    i = LADDER.index(fam) + 1
    return f"{LADDER[i]}-{top}" if i < len(LADDER) else None


def unavailable_next(rung: str) -> str | None:
    """The next family at the same effort; opus-* has none."""
    i = LADDER.index(family(rung)) + 1
    return f"{LADDER[i]}-{effort(rung)}" if i < len(LADDER) else None


def jump(current: str, target: str) -> str | None:
    """max(quality_next(current), target) by rank."""
    nxt = quality_next(current)
    if nxt is None:
        return None
    return max(nxt, target, key=rank)


def task_start(row: dict) -> tuple[str, str]:
    """Default start rung for a task_eligibility row: (rung, reason)."""
    tier = row["tier"]
    if tier == "local":
        if row.get("kind") != "clerical" and [
                r for r in row.get("reasons") or [] if not r.startswith("collides:")]:
            return "local-xhigh", "local-eligible task, complex (has reasons)"
        return "local-medium", "local-eligible task"
    if row.get("kind") == "clerical":
        return f"{tier}-medium", f"{tier} row, clerical kind"
    return LEGACY[tier], f"{tier} row, default effort"


def as_rung(tier_or_rung: str) -> str:
    """A legacy family (``local``/``sonnet``/``opus``) mapped through ``LEGACY``; a rung
    (or anything else) unchanged."""
    return LEGACY.get(tier_or_rung, tier_or_rung)


def route_floor(tier: str, label: str) -> tuple[str, bool]:
    """Rung-aware: a ``local``-family tier or rung under any ``label`` but
    ``"routed/ok"`` becomes ``sonnet`` at the **same effort** (``local`` → ``sonnet``,
    ``local-X`` → ``sonnet-X``), with ``True``; else ``(tier, False)``.
    ``sonnet``/``opus`` are never floored."""
    fam, sep, eff = str(tier).partition("-")
    if fam == "local" and label != "routed/ok":
        return (f"{SAFE_CLAUDE}-{eff}" if sep else SAFE_CLAUDE), True
    return tier, False


def effective_model(tier: str, cfg: dict, label: str) -> str | None:
    """``model_policy.rung_model(tier, cfg)``, except a haiku-family model (case-insensitive
    ``"haiku"``) under a non-routed ``label`` is refused down to ``SAFE_CLAUDE``."""
    model = model_policy.rung_model(tier, cfg)
    if model is not None and "haiku" in str(model).lower() and label != "routed/ok":
        return SAFE_CLAUDE
    return model


def display(plan_tier: str, tier: str, label: str) -> str:
    """The floor-aware display string: ``"{plan_tier}->{tier}: {label}"`` when ``tier``
    differs from ``plan_tier`` (i.e. floored), else ``plan_tier`` unchanged."""
    if tier != plan_tier:
        return f"{plan_tier}->{tier}: {label}"
    return plan_tier
