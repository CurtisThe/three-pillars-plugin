#!/usr/bin/env python3
"""strata_effort_check.py — the Strata effort guard.

design: strata-effort-every-call (Task 3.3)

`strata_effort.SITES` is the inventory of Strata dispatch sites. This guard reads
it against the framework tree and prints one problem line per break, so a new
Strata site that skips the inventory cannot land quietly (design Behaviors 3 and
5). Four checks, one line each per break:

(a) every `agents/*.md` whose policy model (under `local_implement_config.DEFAULTS`)
    is the local alias must map, through `strata_effort.strata_agent`, to an agent
    file that exists, states a `STRATA_EFFORTS` effort, and matches a site;
(b) every agent an inventory site names must exist at a `STRATA_EFFORTS` effort
    (a glob site agent must match at least one agent file);
(c) every engine role must have an `ENGINE_ROLE_EFFORT` at a Strata effort, and
    every role an inventory site names must be an engine role;
(d) every `--site S<n>` id in the shipped `skills/**/*.md` must be an inventory
    site id (`child-spawn.md`'s `--site <site>` placeholder is not an id).

Efforts come from `model_policy`, never from frontmatter — `agent_variants.py
--check` owns frontmatter drift. An agent with no `model_policy.AGENTS` row is
skipped here for the same reason.

CLI::

    python3 "$TP_ROOT"/skills/_shared/strata_effort_check.py [--root R]

prints the problem lines (or `strata effort: ok`) and exits 1 when there are any.
Stdlib only.
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import local_implement_config  # noqa: E402 — in-repo, stdlib-only siblings
import model_policy  # noqa: E402
import strata_effort  # noqa: E402

FRAMEWORK_ROOT = _SHARED.parents[1]

# A site id as a doc names it. `--site <site>` (the child-spawn placeholder) is not one.
SITE_ID = re.compile(r"--site (S\d+)")


def _is_glob(pattern: str) -> bool:
    return any(c in pattern for c in "*?[")


def _stems(fw_root) -> list[str]:
    """The agent names a framework root ships (`agents/*.md` stems)."""
    return sorted(path.stem for path in (Path(fw_root) / "agents").glob("*.md"))


def _has_agent(fw_root, name: str) -> bool:
    return (Path(fw_root) / "agents" / f"{name}.md").exists()


def _local_alias() -> str:
    """The model alias a Strata-routable agent resolves to under the framework defaults."""
    return model_policy.agent_alias(local_implement_config.DEFAULTS["model"])


def _effort_line(what: str, level: str) -> str:
    return (f"{what}: effort {level!r} — Strata takes "
            f"{' or '.join(strata_effort.STRATA_EFFORTS)}")


def agent_lines(fw_root, stems, sites) -> list[str]:
    """(a) each Strata-routable agent maps to an inventoried agent at medium/xhigh."""
    alias = _local_alias()
    lines: list[str] = []
    for stem in stems:
        try:
            spec = model_policy.agent_spec(stem, None, local_implement_config.DEFAULTS)
        except KeyError:
            continue  # no policy row: `agent_variants.py --check` owns that drift
        if spec["model"] != alias:
            continue  # not Strata-routable — its effort is a Claude one
        mapped = strata_effort.strata_agent(stem)
        if not _has_agent(fw_root, mapped):
            lines.append(f"{mapped}: no agent file (Strata dispatch of {stem})")
            continue
        level = strata_effort.effort(mapped)
        if level not in strata_effort.STRATA_EFFORTS:
            lines.append(_effort_line(mapped, level))
        elif not any(any(fnmatch.fnmatchcase(mapped, p) for p in site.agents)
                     for site in sites):
            lines.append(f"{mapped}: no inventory site")
    return lines


def site_lines(fw_root, stems, sites) -> list[str]:
    """(b) each agent a site names exists at a Strata effort (a glob needs a match)."""
    lines: list[str] = []
    for site in sites:
        for pattern in site.agents:
            where = f" ({site.doc})"
            if _is_glob(pattern):
                if not any(fnmatch.fnmatchcase(stem, pattern) for stem in stems):
                    lines.append(f"{site.id}: no agent matches {pattern!r}{where}")
                continue
            if not _has_agent(fw_root, pattern):
                lines.append(f"{site.id}: {pattern}: no agent file{where}")
                continue
            level = strata_effort.effort(pattern)
            if level not in strata_effort.STRATA_EFFORTS:
                lines.append(f"{site.id}: {_effort_line(pattern, level)}")
    return lines


def role_lines(sites, roles) -> list[str]:
    """(c) each engine role states a Strata effort; each site role is an engine role."""
    lines: list[str] = []
    for role in roles:
        level = strata_effort.ENGINE_ROLE_EFFORT.get(role)
        if level is None:
            lines.append(f"{role}: no strata_effort.ENGINE_ROLE_EFFORT entry")
        elif level not in strata_effort.STRATA_EFFORTS:
            lines.append(_effort_line(role, level))
    for site in sites:
        for role in site.roles:
            if role not in roles:
                lines.append(f"{site.id}: {role} is not a {model_policy.__name__} engine role")
    return lines


def doc_lines(fw_root, sites) -> list[str]:
    """(d) each `--site S<n>` id in the shipped docs names an inventory site."""
    known = {site.id for site in sites}
    lines: list[str] = []
    for path in sorted(Path(fw_root).glob("skills/**/*.md")):
        rel = path.relative_to(Path(fw_root)).as_posix()
        for sid in SITE_ID.findall(path.read_text(encoding="utf-8")):
            if sid not in known:
                lines.append(f"{sid}: `--site {sid}` in {rel} has no inventory site")
    return lines


def check(fw_root, sites=strata_effort.SITES, roles=model_policy.ENGINE_ROLES) -> list[str]:
    """The problem lines for a framework root, in check order, deduped."""
    stems = _stems(fw_root)
    lines = (agent_lines(fw_root, stems, sites) + site_lines(fw_root, stems, sites)
             + role_lines(sites, roles) + doc_lines(fw_root, sites))
    return list(dict.fromkeys(lines))


def main(argv=None) -> int:
    """Print the problem lines (or `strata effort: ok`); exit 1 when there are any."""
    parser = argparse.ArgumentParser(description="Strata effort inventory guard.")
    parser.add_argument("--root", default=str(FRAMEWORK_ROOT),
                        help="framework root (default: this install)")
    args = parser.parse_args(argv)
    problems = check(args.root)
    for line in problems:
        print(line)
    if not problems:
        print("strata effort: ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
