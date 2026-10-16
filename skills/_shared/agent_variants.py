#!/usr/bin/env python3
"""agent_variants.py — render the generated agent variants; drift check.

design: run-throughput (Task 3.2)

`model_policy.AGENTS` is the one policy table naming every agent's model and
effort. This module keeps the shipped `agents/*.md` files (and the plugin
manifest's `agents` array) in sync with that table:

- `expected(name)` — the policy spec `{role, model, effort}` for an agent name
  (`model_policy.agent_spec`, resolved against `local_implement_config.DEFAULTS`).
- `variants(fw_root)` — every generated variant: the spawn-rung workers
  (`tp-task-worker-<rung>` for `rung in ladder_rungs.SPAWN_RUNGS`), the round-1 review
  angle `tp-review-confirmer-deep`, and one Strata-only `-medium` copy of every
  `strata_effort` variant base (`families()`: base agent → suffixes).
- `render(base_text, suffix, base=...)` — one variant's file text: the base
  file's body byte-identical, frontmatter `name`/`model`/`effort`/
  `description` from `expected()`.
- `check(fw_root)` — drift lines: a variant file that differs from
  `render()`; any `agents/*.md` whose frontmatter `model`/`effort` differs
  from `expected(name)`; any `agents/*.md` with no policy entry and no
  variant match; a `.claude-plugin/plugin.json` `agents` array that differs
  from the sorted `./agents/*.md` set.
- `write(fw_root)` — regenerates every variant file, rewrites only the
  `model:`/`effort:` lines of the other listed agents (adding an `effort:`
  line right after `model:` when missing), and rewrites the plugin's
  `agents` array. Comparison always runs policy -> file, never back.

CLI::

    python3 skills/_shared/agent_variants.py --check [--framework-root PATH]
    python3 skills/_shared/agent_variants.py --write [--framework-root PATH]

`--check` exits 1 when any drift is reported, 0 when clean. `--write` always
exits 0. The variants differ from their base only in frontmatter (no per-spawn effort
exists, so an effort variant is its own agent file). `FRAMEWORK_ROOT` is `Path(__file__).resolve().parents[2]`;
`--framework-root` is a test override only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import ladder_rungs  # noqa: E402
import local_implement_config  # noqa: E402
import model_policy  # noqa: E402
import strata_effort  # noqa: E402
import weight_class  # noqa: E402

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]

# base agent → the suffixes of its generated variants (one mechanism for every family).
# `families()` adds the Strata `-medium` family for every `strata_effort` variant base.
FAMILIES = {"tp-task-worker": tuple(ladder_rungs.SPAWN_RUNGS), "tp-review-confirmer": ("deep",)}
# a Strata-only variant's whole description: short (the agent listing stays small) and it
# names the base, so nobody spawns the copy standalone (strata-effort-every-call 2.1).
STRATA_DESCRIPTION = ("Strata-only medium-effort copy of {base}; "
                      "spawned via strata_effort.py spawn.")
_FM_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")


def expected(name: str) -> dict:
    """The policy spec for `name` (`KeyError` when `name` has no entry)."""
    spec = model_policy.agent_spec(name, None, local_implement_config.DEFAULTS)
    if model_policy._entry(name)[1] == "cheap":  # call carries model=; file keeps the fail-safe
        spec["model"] = model_policy.PINNED
    return spec


def variants(fw_root=FRAMEWORK_ROOT) -> list[str]:
    """Every generated variant name (all `families(fw_root/agents)`)."""
    return [f"{base}-{sfx}" for base, sfxs in families(_agents_dir(fw_root)) for sfx in sfxs]


def _split_frontmatter(text: str) -> tuple[list[str], str]:
    """`(frontmatter_lines, body)`; frontmatter_lines excludes both fences."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("base text has no leading frontmatter block")
    close = next(
        (i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if close is None:
        raise ValueError("base text frontmatter block is never closed")
    return lines[1:close], "".join(lines[close + 1:])


def _variant_description(raw_value: str, label: str) -> str:
    text = raw_value.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    return f'"{text} ({label})"'


def render(base_text: str, rung: str, base: str = "tp-task-worker") -> str:
    """The variant file text for `<base>-<rung>`: base body untouched, frontmatter
    `name`/`model`/`effort`/`description` from `expected()`."""
    name = f"{base}-{rung}"
    spec = expected(name)
    label = f"rung {rung}" if base == "tp-task-worker" else rung
    strata = strata_effort.strata_agent(base) == name
    fm_lines, body = _split_frontmatter(base_text)

    new_fm: list[str] = []
    for line in fm_lines:
        match = _FM_KEY_RE.match(line)
        if not match:
            new_fm.append(line)
            continue
        key, value = match.group(1), match.group(2)
        if key == "name":
            new_fm.append(f"name: {name}\n")
        elif key == "description":
            if strata:
                new_fm.append(f'description: "{STRATA_DESCRIPTION.format(base=base)}"\n')
            else:
                new_fm.append(f"description: {_variant_description(value, label)}\n")
        elif key == "model":
            new_fm.append(f"model: {spec['model']}\n")
            new_fm.append(f"effort: {spec['effort']}\n")
        elif key == "effort":
            continue  # re-emitted right after model above
        else:
            new_fm.append(line)
    return "---\n" + "".join(new_fm) + "---\n" + body


def _rewrite_model_effort(text: str, spec: dict) -> str:
    """Rewrite only the `model:`/`effort:` lines of an agent file's
    frontmatter to `spec`; adds `effort:` right after `model:` when missing.
    Returns `text` unchanged if there is no parseable frontmatter block."""
    try:
        fm_lines, body = _split_frontmatter(text)
    except ValueError:
        return text
    model_idx = None
    effort_idx = None
    for i, line in enumerate(fm_lines):
        match = _FM_KEY_RE.match(line)
        if not match:
            continue
        if match.group(1) == "model":
            model_idx = i
        elif match.group(1) == "effort":
            effort_idx = i
    new_fm = list(fm_lines)
    if model_idx is not None:
        new_fm[model_idx] = f"model: {spec['model']}\n"
    if effort_idx is not None:
        new_fm[effort_idx] = f"effort: {spec['effort']}\n"
    elif model_idx is not None:
        new_fm.insert(model_idx + 1, f"effort: {spec['effort']}\n")
    return "---\n" + "".join(new_fm) + "---\n" + body


def _rewrite_plugin_agents(path: Path, want: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    entries = ",\n".join(f'    "{name}"' for name in want)
    block = "\"agents\": [\n" + entries + ("\n" if entries else "") + "  ]"
    new_text = re.sub(r'"agents":\s*\[.*?\]', block, text, count=1, flags=re.DOTALL)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")


def _agents_dir(fw_root) -> Path:
    return Path(fw_root) / "agents"


def _plugin_path(fw_root) -> Path:
    return Path(fw_root) / ".claude-plugin" / "plugin.json"


def _base_text(fw_root, base: str = "tp-task-worker") -> str:
    return (_agents_dir(fw_root) / f"{base}.md").read_text(encoding="utf-8")


def families(agents_dir: Path) -> list[tuple[str, tuple[str, ...]]]:
    """Every family this tree generates: the static `FAMILIES` whose base file exists
    (a tree may ship only some bases), plus the Strata `-medium` family for each base
    `strata_effort.variant_bases` names among the agent stems here. So a tree with both
    `tp-review-confirmer.md` and `council-ada.md` gives `("deep", "medium")` and
    `("medium",)` — one mechanism, one source, for every variant."""
    if not agents_dir.is_dir():
        return []
    found: dict[str, list[str]] = {b: list(s) for b, s in FAMILIES.items()
                                   if (agents_dir / f"{b}.md").exists()}
    for base in strata_effort.variant_bases(p.stem for p in agents_dir.glob("*.md")):
        found.setdefault(base, []).append(strata_effort.VARIANT_SUFFIX)
    return [(b, tuple(s)) for b, s in found.items()]


def _plugin_want(agents_dir: Path) -> list[str]:
    if not agents_dir.is_dir():
        return []
    return sorted(f"./agents/{p.name}" for p in agents_dir.glob("*.md"))


def check(fw_root) -> list[str]:
    """Drift lines for the variant files, agent frontmatter, and the plugin
    manifest's `agents` array. Empty when everything matches policy."""
    fw_root = Path(fw_root)
    agents_dir = _agents_dir(fw_root)
    drift: list[str] = []

    for base, sfxs in families(agents_dir):
        base_text = _base_text(fw_root, base)
        for sfx in sfxs:
            path = agents_dir / f"{base}-{sfx}.md"
            current = path.read_text(encoding="utf-8") if path.exists() else None
            if current != render(base_text, sfx, base):
                drift.append(f"variant drift: {base}-{sfx}.md does not match render()")
    for base, sfxs in FAMILIES.items():
        if not (agents_dir / f"{base}.md").exists() and any(
                (agents_dir / f"{base}-{sfx}.md").exists() for sfx in sfxs):
            drift.append(f"variant drift: {base}-* present without its base {base}.md")
    for path in sorted(agents_dir.glob(f"*-{strata_effort.VARIANT_SUFFIX}.md")):
        base = path.stem[: -len(strata_effort.VARIANT_SUFFIX) - 1]
        if strata_effort.strata_agent(base) == path.stem and not (
                agents_dir / f"{base}.md").exists():
            drift.append(f"variant drift: {base}-* present without its base {base}.md")

    if agents_dir.is_dir():
        for path in sorted(agents_dir.glob("*.md")):
            name = path.stem
            try:
                spec = expected(name)
            except KeyError:
                drift.append(
                    f"no policy: {name}.md has no model_policy.AGENTS entry "
                    "and matches no variant rung"
                )
                continue
            fm = weight_class.parse_frontmatter(path.read_text(encoding="utf-8"))
            if fm.get("model") != spec["model"] or fm.get("effort") != spec["effort"]:
                drift.append(
                    f"model/effort drift: {name}.md has "
                    f"model={fm.get('model')!r} effort={fm.get('effort')!r}, "
                    f"expected model={spec['model']!r} effort={spec['effort']!r}"
                )

    plugin_path = _plugin_path(fw_root)
    if plugin_path.exists():
        try:
            have = json.loads(plugin_path.read_text(encoding="utf-8")).get("agents", [])
        except json.JSONDecodeError:
            have = None
        if have != _plugin_want(agents_dir):
            drift.append("plugin.json: agents array does not match sorted ./agents/*.md")

    return drift


def write(fw_root) -> list[str]:
    """Fix everything `check()` reports; returns the drift lines it fixed."""
    fw_root = Path(fw_root)
    agents_dir = _agents_dir(fw_root)
    fixed = check(fw_root)
    if not fixed:
        return fixed

    variant_names = {f"{b}-{sfx}" for b, sfxs in families(agents_dir) for sfx in sfxs}
    if agents_dir.is_dir():
        for path in sorted(agents_dir.glob("*.md")):
            name = path.stem
            if name in variant_names:
                continue
            try:
                spec = expected(name)
            except KeyError:
                continue
            text = path.read_text(encoding="utf-8")
            new_text = _rewrite_model_effort(text, spec)
            if new_text != text:
                path.write_text(new_text, encoding="utf-8")
    for base, sfxs in families(agents_dir):  # after the bases' own frontmatter is current
        base_text = _base_text(fw_root, base)
        for sfx in sfxs:
            (agents_dir / f"{base}-{sfx}.md").write_text(render(base_text, sfx, base),
                                                         encoding="utf-8")

    plugin_path = _plugin_path(fw_root)
    if plugin_path.exists():
        _rewrite_plugin_agents(plugin_path, _plugin_want(agents_dir))

    return fixed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agent_variants", description=__doc__)
    parser.add_argument(
        "--framework-root", default=None,
        help="Override FRAMEWORK_ROOT (test override only)",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Report drift; exit 1 if any")
    mode.add_argument("--write", action="store_true", help="Fix drift reported by --check")
    args = parser.parse_args(argv)

    fw_root = Path(args.framework_root) if args.framework_root else FRAMEWORK_ROOT

    if args.write:
        for line in write(fw_root):
            print(line)
        return 0

    drift = check(fw_root)
    for line in drift:
        print(line)
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
