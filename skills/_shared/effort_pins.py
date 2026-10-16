"""effort_pins.py — report the one proven effort override: `CLAUDE_CODE_EFFORT_LEVEL`.

`detect(env)` returns one `⚠ effort pin` line when the `CLAUDE_CODE_EFFORT_LEVEL`
environment variable is set, else `[]`. It never raises.

Why only the env var: the wire check recorded in
`three-pillars-docs/completed-tp-designs/run-throughput/effort-wire-check.md` (2026-09-28,
Claude Code 2.1.284) returned

    {"session_flag_overrides": false, "slash_effort_overrides": false, "env_overrides_frontmatter": true}

— the env var beats `effort:` frontmatter, so it flattens every agent variant to one
effort. A settings-file `effortLevel` / `modelSettings.<name>.effortLevel` pin does
not: the PR #178 live check (2026-09-29) logged every rung variant at its own effort
under exactly those pins. So settings files are never read here, and no line ever
advises removing them. The clause is a small function of `ENV_OVERRIDES_FRONTMATTER`
(the recorded value); a `false` recording keeps the source naming but drops the claim.
The design doc is cited by file name only — never read or imported at runtime.

Stdlib only; ships in the free surface, so it names no pro skill.
"""
from __future__ import annotations

from typing import Mapping, Optional

EFFORT_ENV = "CLAUDE_CODE_EFFORT_LEVEL"
LINE_PREFIX = "⚠ effort pin"
# Recorded wire-check value (see module docstring): the env var wins over frontmatter.
ENV_OVERRIDES_FRONTMATTER = True

_FLATTENS_CLAUSE = "flattens every agent variant"


def _pin_line(source: str, value: object) -> str:
    line = f"{LINE_PREFIX}: {source} = {value!r}"
    clause = flattens_clause()
    return f"{line} — {clause}" if clause else line


def flattens_clause(env_overrides_frontmatter: Optional[bool] = None) -> str:
    """The clause for the env-var line, from the recorded wire-check value.

    `true` and `null` recordings keep the claim that the pin flattens every
    agent variant; only `false` drops the claim (the source naming stays).
    Omitted input defaults to the recorded `ENV_OVERRIDES_FRONTMATTER`.
    """
    if env_overrides_frontmatter is None:
        env_overrides_frontmatter = ENV_OVERRIDES_FRONTMATTER
    return _FLATTENS_CLAUSE if env_overrides_frontmatter is not False else ""


def detect(env: Mapping[str, object]) -> list[str]:
    """One `⚠ effort pin` line when `CLAUDE_CODE_EFFORT_LEVEL` is set in `env`, else []."""
    value = env.get(EFFORT_ENV)
    return [] if value is None else [_pin_line(EFFORT_ENV, value)]
