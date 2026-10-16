"""cheap_deprecation.py — deprecation notes for the retired cheap-tier switches.

design: one-cheap-engine

Easy work follows the one cheap-engine rule; the old switches change nothing.
``notes(cfg, cheap_tier=..., no_cheap_tier=...)`` encodes the flags as:
  cheap_tier: None (absent), "on" (``--cheap-tier``) or "ab" (``--cheap-tier=ab``)
  no_cheap_tier: True when ``--no-cheap-tier`` was passed.
"""
from __future__ import annotations

DEPRECATED = (
    "--cheap-tier",
    "--cheap-tier=ab",
    "--no-cheap-tier",
    "cheap_tier.default_run_flag",
    "role_engines",
)

_TAIL = "is deprecated and changes nothing; easy work follows the one cheap-engine rule"


def _line(name: str) -> str:
    return f"deprecated: {name} {_TAIL}"


def notes(cfg, *, cheap_tier=None, no_cheap_tier=False) -> list[str]:
    """One ``deprecated:`` line per retired switch that is present."""
    out: list[str] = []
    if cheap_tier == "ab":
        out.append(_line("--cheap-tier=ab"))
    elif cheap_tier:
        out.append(_line("--cheap-tier"))
    if no_cheap_tier:
        out.append(_line("--no-cheap-tier"))
    cfg = cfg if isinstance(cfg, dict) else {}
    tier = cfg.get("cheap_tier")
    if isinstance(tier, dict) and tier.get("default_run_flag") is not None:
        out.append(_line("cheap_tier.default_run_flag"))
    roles = cfg.get("role_engines")
    if isinstance(roles, dict) and roles:
        out.append(_line("role_engines (" + ", ".join(sorted(map(str, roles))) + ")"))
    return out
