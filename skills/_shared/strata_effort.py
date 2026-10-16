#!/usr/bin/env python3
"""strata_effort.py — the Strata dispatch-site inventory and the Strata agent mapping.

design: strata-effort-every-call (Task 1.1)

Every call routed to the local Strata model states an effort on purpose: `medium`
or `xhigh`, never a bare `high`. The Agent tool has no effort parameter, so the
effort rides on the agent's frontmatter; a Strata dispatch therefore spawns a
Strata-only variant of the agent instead of the base:

- `council-<name>` and `tp-review-confirmer` get a generated `<base>-medium` copy
  (`agent_variants.py` makes it; the bases keep their Opus/Sonnet effort);
- `tp-review-confirmer-deep`, the `tp-task-worker-local-*` rungs and the
  `tp-drafter` / `tp-drafter-xhigh` pair already state medium/xhigh and map to
  themselves, so every medium->xhigh escalation path is unchanged.

`SITES` is the inventory of Strata dispatch sites (the guard reads it);
`ENGINE_ROLE_EFFORT` is the effort a `local` engine row states per engine role.
CLI::

    python3 "$TP_ROOT"/skills/_shared/strata_effort.py spawn <base-agent> [--root R]

prints `{"agent", "agent_ref", "effort", "rung"}` as JSON (exit 0), or one stderr
line and exit 1 when the agent would run Strata at an effort outside
`STRATA_EFFORTS` or cannot be resolved. Stdlib only; reads `model_policy` for efforts.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import NamedTuple

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import agent_ref  # noqa: E402 — in-repo, stdlib-only siblings
import local_implement_config  # noqa: E402
import model_policy  # noqa: E402

STRATA_EFFORTS = ("medium", "xhigh")  # the only efforts a Strata call may state
VARIANT_SUFFIX = "medium"  # the generated Strata-only copy: <base>-medium
STRATA_VARIANTS = ("council-*", "tp-review-confirmer")  # bases that get a variant

# Effort a `local` engine row states, per engine role (role_engine reads it).
ENGINE_ROLE_EFFORT = {
    "council_member": "medium",
    "review_finder": "medium",
    "context_scout": "medium",
    "explainer": "medium",
}


class Site(NamedTuple):
    """One Strata dispatch site: its doc, agents (globs allowed), engine roles, stronger check."""

    id: str
    doc: str
    agents: tuple
    roles: tuple
    check: str


SITES = (
    Site("S1", "skills/_shared/local-dispatch.md",
         ("tp-task-worker-local-medium", "tp-task-worker-local-xhigh"), (),
         "task_verify plus the Opus review"),
    Site("S2", "skills/_shared/cheap-dispatch.md", ("tp-drafter", "tp-drafter-xhigh"), (),
         "the slot oracle"),
    Site("S3", "skills/council/strata-members.md", ("council-*-medium",), ("council_member",),
         "the Opus synth"),
    Site("S4", "skills/tp-pr-iterate/strata-finders.md",
         ("tp-review-confirmer-deep", "tp-review-confirmer-medium"),
         ("review_finder", "context_scout"), "the Opus check"),
    Site("phase-check", "skills/_shared/phase-check.md", ("tp-review-confirmer-medium",), (),
         "tp-phase-checker"),
    Site("explainer", "skills/_shared/explainer.md", ("tp-explainer",), ("explainer",),
         "the Opus check"),
    Site("smoke", "skills/_shared/child-spawn.md", ("tp-runbook",), (), ""),
)


class StrataEffortError(ValueError):
    """A Strata dispatch would run at an effort outside `STRATA_EFFORTS` (or is unknown)."""


def strata_agent(base: str) -> str:
    """The agent a Strata dispatch of `base` spawns: `<base>-medium` for a
    `STRATA_VARIANTS` base, else `base` itself (a `-medium` name, `-deep`, the
    task rungs and the drafters already state a Strata effort)."""
    if base.endswith(f"-{VARIANT_SUFFIX}"):
        return base
    if any(fnmatch.fnmatchcase(base, pattern) for pattern in STRATA_VARIANTS):
        return f"{base}-{VARIANT_SUFFIX}"
    return base


def variant_bases(names) -> list[str]:
    """The sorted base names among `names` that get a generated Strata variant."""
    return sorted(n for n in names if strata_agent(n) != n)


def effort(agent: str) -> str:
    """The effort `agent` runs at (the `model_policy.AGENTS` row); KeyError when unknown."""
    return model_policy.agent_spec(agent, None, local_implement_config.DEFAULTS)["effort"]


def role_effort(role: str) -> str:
    """The effort a `local` engine row states for `role`; ValueError for a non-engine role."""
    if role not in ENGINE_ROLE_EFFORT:
        raise ValueError(f"no Strata effort for role {role!r} — roles: {', '.join(ENGINE_ROLE_EFFORT)}")
    return ENGINE_ROLE_EFFORT[role]


def spawn(base: str, root=None) -> dict:
    """What a Strata dispatch of `base` spawns: `{agent, agent_ref, effort, rung}`.

    Raises `StrataEffortError` when the agent's effort is not in `STRATA_EFFORTS`
    (or it has no policy row), `agent_ref.AgentRefError` when it cannot be resolved.
    """
    agent = strata_agent(base)
    try:
        level = effort(agent)
    except KeyError as exc:
        raise StrataEffortError(f"strata-effort: {exc.args[0]}") from None
    if level not in STRATA_EFFORTS:
        raise StrataEffortError(
            f"strata-effort: {agent} runs at {level!r}; Strata takes {' or '.join(STRATA_EFFORTS)}")
    return {"agent": agent, "agent_ref": agent_ref.resolve(agent, root), "effort": level,
            "rung": f"local-{level}"}


def split(path) -> dict:
    """Counts of Strata-bound dispatch rows in a dispatch ndjson, keyed by effort.

    A row is Strata-bound when its `rung` starts with `local-` or its
    `served_by` is `local`; it counts under the `effort` string it states.
    Fail-open: a missing/unreadable file, a malformed line or a row with no
    string effort counts nothing and never raises."""
    counts: dict[str, int] = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return counts
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        rung = str(rec.get("rung") or "")
        if not (rung.startswith("local-") or rec.get("served_by") == "local"):
            continue
        level = rec.get("effort")
        if not isinstance(level, str) or not level:
            continue
        counts[level] = counts.get(level, 0) + 1
    return counts


def render_split(counts: dict) -> str:
    """One line: the medium/xhigh counts (a zero still prints) and, only when
    other efforts exist, each named as `other=<effort>:<n>` (sorted, comma-joined)."""
    line = (f"strata effort: medium={counts.get('medium', 0)} "
            f"xhigh={counts.get('xhigh', 0)}")
    others = sorted(k for k in counts if k not in STRATA_EFFORTS)
    if others:
        line += " other=" + ",".join(f"{k}:{counts[k]}" for k in others)
    return line


def main(argv=None) -> int:
    """`spawn <base> [--root R]`: print the JSON, or one stderr line + exit 1."""
    parser = argparse.ArgumentParser(description="Strata dispatch effort inventory.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    spawn_p = sub.add_parser("spawn", help="print the Strata agent, reference and effort for a base agent")
    spawn_p.add_argument("base")
    spawn_p.add_argument("--root", default=None, help="framework root (default: this install)")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(spawn(args.base, args.root)))
    except (StrataEffortError, agent_ref.AgentRefError) as exc:
        print(str(exc).splitlines()[0] if str(exc) else "strata-effort: refused", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
