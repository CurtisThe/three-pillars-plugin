#!/usr/bin/env python3
"""dispatch_select.py — the gate-role floor, a thin layer over model_policy.

design: run-throughput (Part A §Floors)

`enforce_floor(role, agent, config=None)` never raises. A role outside
`model_policy.GATE_ROLES` returns `agent` unchanged with no note. An agent
missing from `model_policy.AGENTS` (a `KeyError`/`ValueError` from
`agent_spec`) returns `agent` unchanged with a `floor-unchecked` note. An
effort below the role's floor effort, or — for `impl-audit`/`certify` only —
a model other than `model_policy.PINNED`, substitutes `role_agent(role)`
with a `floor-substituted` note. `review` is reconciled with parity, not
competing with it: its model is whatever `models.review` resolves to and is
never substituted, only its effort is floored; a configured non-`PINNED`
value is kept with a `floor-note`.

CLI::

    python3 skills/_shared/dispatch_select.py floor --role R --agent A [--root .]

prints one JSON object `{"agent": ..., "note": ...}` and always exits 0.
Stdlib-only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_implement_config  # noqa: E402
import model_policy  # noqa: E402
import repo_config_load  # noqa: E402


# An agent whose own policy role is one of these is a Strata-only finder, kept
# clear of the gate floor by design (model_policy.AGENTS); the floor must not
# swap it back to the base agent at `high` (known issue M65).
_FLOOR_EXEMPT_AGENT_ROLES = ("review_finder",)


def enforce_floor(role: str, agent: str, config=None) -> tuple[str, str | None]:
    """The gate-role floor for `agent` filling `role`; never raises."""
    if role not in model_policy.GATE_ROLES:
        return agent, None
    try:
        spec = model_policy.agent_spec(agent, config, local_implement_config.DEFAULTS)
    except (KeyError, ValueError):
        return agent, f"floor-unchecked: {agent} not in model_policy.AGENTS"

    if spec["role"] in _FLOOR_EXEMPT_AGENT_ROLES:
        return agent, None

    floor_spec = model_policy.floor(role, config)
    fallback = model_policy.role_agent(role)
    efforts = model_policy.EFFORTS
    effort_below = efforts.index(spec["effort"]) < efforts.index(floor_spec["effort"])
    model_below = (
        role in ("impl-audit", "certify") and spec["model"] != model_policy.PINNED
    )
    if effort_below or model_below:
        return fallback, f"floor-substituted: {agent} → {fallback}"

    if role == "review" and floor_spec["model"] != model_policy.PINNED:
        return agent, f"floor-note: models.review={floor_spec['model']} (configured)"

    return agent, None


def _load_config(root: str):
    try:
        return repo_config_load.load_repo_config(root).config
    except Exception:
        return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="dispatch_select")
    sub = parser.add_subparsers(dest="command", required=True)
    floor_cmd = sub.add_parser("floor")
    floor_cmd.add_argument("--role", required=True)
    floor_cmd.add_argument("--agent", required=True)
    floor_cmd.add_argument("--root", default=".")
    args = parser.parse_args(argv)

    config = _load_config(args.root)
    agent, note = enforce_floor(args.role, args.agent, config)
    print(json.dumps({"agent": agent, "note": note}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
