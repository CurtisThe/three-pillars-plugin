#!/usr/bin/env python3
"""cheap_tier_default.py — shared cheap-tier resolver (the tier is always on).

design: one-cheap-engine (was cheap-tier-default-flag-everywhere)

    python3 cheap_tier_default.py --root R [--cheap-tier[=ab] | --no-cheap-tier]

Prints `on` to stdout for every input: the cheap tier runs in every invocation.
`--cheap-tier[=ab]`, `--no-cheap-tier` and a set `cheap_tier.default_run_flag` are
deprecated and change nothing; each adds one `deprecated:` line on stderr. The same
module resolves the per-repo `--local` default (`local_implement.default_run_flag`,
`resolve_local`), with the operator's `TP_LOCAL` env input (`on`) ranking above it; at the
seat->run launch only (`ignore_launcher_owned=True`), a `TP_LOCAL` named in
`CLAUDE_LAUNCHER_OWNED` is the seat launcher's and is ignored. Any dropped
`cheap_tier` config is reported as a `warning:` line on stderr. A resolved run exits 0.
An argparse usage error (both flags, an invalid `--cheap-tier` value) exits 2 with
empty stdout.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cheap_deprecation  # noqa: E402
import design_run_command as drc  # noqa: E402
import launcher_env  # noqa: E402  (owned_keys: a launcher-owned TP_LOCAL is ignored)
import local_implement_config as lic  # noqa: E402
import repo_config_load as rcl  # noqa: E402

MODES = drc.CHEAP_TIER_MODES


def default_mode(cfg=None) -> str:
    """The run's cheap-tier mode: always `on`. `cheap_tier.default_run_flag` is
    deprecated and changes nothing (`launch_design_run.default_cheap_tier` aliases this)."""
    return "on"


def _gates_allow(block) -> bool:
    """True when `block` (the `local_implement` config block) passes the
    permission and capability checks Tier 1 runs
    (`local_implement_config.py --check full_design`): it permits a
    full-design `--local` and the runaway-ceiling capability gate holds."""
    if not isinstance(block, dict):
        return False
    if lic.permission_error(block, "full_design") is not None:
        return False
    return lic.runaway_ceiling_error(
        "full_design", lic.load_capability(lic.CAPABILITY_PATH)) is None


def default_local(cfg) -> bool:
    """True when `local_implement.default_run_flag` is `"on"` AND the
    permission and capability checks Tier 1 runs both pass (`_gates_allow`).
    The launcher separately validates the raw block
    (`launch_design_run.main`), so a malformed block is reported there, not
    silently forwarded here. Absent block or key: False."""
    block = cfg.get("local_implement") if isinstance(cfg, dict) else None
    if not isinstance(block, dict) or block.get("default_run_flag") != "on":
        return False
    return _gates_allow(block)


def _env(env):
    return os.environ if env is None else env


def _launcher_owned(env) -> bool:
    """True when `CLAUDE_LAUNCHER_OWNED` names `TP_LOCAL`: the caller's launcher set
    it for the caller's own folder route, not the operator for this run."""
    return "TP_LOCAL" in launcher_env.owned_keys(_env(env))


def _tp_local(env, ignore_launcher_owned: bool = False) -> str:
    """`TP_LOCAL` from `env` (default `os.environ`): `""` when unset, or when
    `ignore_launcher_owned` and it is launcher-owned (the seat->run launch only; an
    in-session reader honours it)."""
    if ignore_launcher_owned and _launcher_owned(env):
        return ""
    return _env(env).get("TP_LOCAL") or ""


def local_source(env=None, *, ignore_launcher_owned: bool = False) -> str:
    """The label for what turned `--local` on without the flag: `TP_LOCAL` when
    it is `on` (and counts), else `local_implement.default_run_flag`."""
    on = _tp_local(env, ignore_launcher_owned) == "on"
    return "TP_LOCAL" if on else "local_implement.default_run_flag"


def env_local_note(cfg, env=None, *, local: bool = False, no_local: bool = False,
                   ignore_launcher_owned: bool = False) -> Optional[str]:
    """One `note:` line when a launcher-owned `TP_LOCAL` is ignored (only with
    `ignore_launcher_owned`, the launch path); one `warning:`
    line when the operator's `TP_LOCAL` is garbage (anything but `on`) or `on` but
    gated off by the `local_implement` block; else None. An explicit
    `--local`/`--no-local` (`local`/`no_local`) makes `TP_LOCAL` irrelevant: None."""
    if local or no_local:
        return None
    raw = _env(env).get("TP_LOCAL") or ""
    if raw and ignore_launcher_owned and _launcher_owned(env):
        return f"note: TP_LOCAL={raw} is the seat launcher's own route; ignored for the run"
    value = _tp_local(env, ignore_launcher_owned)
    if not value:
        return None
    if value != "on":
        return (f'warning: TP_LOCAL="{value}" is not "on"; treated as off, which overrides '
                "local_implement.default_run_flag (no --local from the environment)")
    block = cfg.get("local_implement") if isinstance(cfg, dict) else None
    if _gates_allow(block):
        return None
    return ('warning: TP_LOCAL="on" not applied: local_implement does not permit '
            "a full-design --local here")


def resolve_local(cfg, *, local: bool = False, no_local: bool = False, env=None,
                  ignore_launcher_owned: bool = False) -> bool:
    """Whether the launch carries `--local`: an explicit `--local` wins, then
    `--no-local`, then the operator's `TP_LOCAL` (`on` asks for it, behind the
    same gates as the repo default but without needing `default_run_flag`; any
    other non-empty value is off; a launcher-owned one is ignored only with
    `ignore_launcher_owned`, which only the seat->run launch passes), else
    `default_local(cfg)`."""
    if local and no_local:
        raise ValueError("local and no_local are mutually exclusive")
    if local:
        return True
    if no_local:
        return False
    value = _tp_local(env, ignore_launcher_owned)
    if value:
        block = cfg.get("local_implement") if isinstance(cfg, dict) else None
        return value == "on" and _gates_allow(block)
    return default_local(cfg)


def is_drop_warning(warning: str) -> bool:
    """True for a loader warning that dropped the `cheap_tier` block itself
    or a key under it."""
    key = warning.removeprefix("config: dropped ").split(" ", 1)[0]
    return key == "cheap_tier" or key.startswith("cheap_tier.")


def is_local_drop_warning(warning: str) -> bool:
    """True for a loader warning that dropped `local_implement.default_run_flag`
    or the whole `local_implement` block."""
    key = warning.removeprefix("config: dropped ").split(" ", 1)[0]
    return key in ("local_implement", "local_implement.default_run_flag")


def resolve(
    cfg,
    warnings: Sequence[str],
    *,
    cheap_tier: Optional[str] = None,
    no_cheap_tier: bool = False,
) -> Tuple[str, List[str]]:
    """`("on", notes)`: the cheap tier is always on. `notes` is each dropped
    `cheap_tier` config warning, then one `deprecated:` line per retired switch
    present (`cheap_deprecation.notes`). Both flags together, or a `cheap_tier`
    outside `MODES`, is a usage error."""
    if cheap_tier is not None and no_cheap_tier:
        raise ValueError("cheap_tier and no_cheap_tier are mutually exclusive")
    if cheap_tier is not None and cheap_tier not in MODES:
        raise ValueError(f"cheap_tier must be one of {MODES}")
    notes = [f"warning: {w}" for w in warnings if is_drop_warning(w)]
    notes += cheap_deprecation.notes(cfg, cheap_tier=cheap_tier, no_cheap_tier=no_cheap_tier)
    return default_mode(cfg), notes


def resolve_root(
    root,
    *,
    cheap_tier: Optional[str] = None,
    no_cheap_tier: bool = False,
    err=None,
) -> str:
    """Load `root`'s config, resolve, and print any notes to `err`."""
    loaded = rcl.load_repo_config(root)
    mode, notes = resolve(loaded.config, loaded.warnings,
                          cheap_tier=cheap_tier, no_cheap_tier=no_cheap_tier)
    for note in notes:
        print(note, file=err or sys.stderr)
    return mode


def flag_arg(mode: Optional[str]) -> str:
    """The `--cheap-tier` argument text for `mode`, else `""`."""
    if mode is None:
        return ""
    if mode == "on":
        return "--cheap-tier"
    if mode == "ab":
        return "--cheap-tier=ab"
    raise ValueError(f"mode must be one of {MODES} or None")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    cheap = ap.add_mutually_exclusive_group()
    cheap.add_argument("--cheap-tier", nargs="?", const="on", default=None,
                       choices=MODES,
                       help="deprecated: accepted, changes nothing (bare = on)")
    cheap.add_argument("--no-cheap-tier", action="store_true",
                       help="deprecated: accepted, changes nothing")
    return ap


def main(argv: Optional[Sequence[str]] = None, *, out=None, err=None) -> int:
    args = build_parser().parse_args(argv)
    mode = resolve_root(args.root, cheap_tier=args.cheap_tier,
                        no_cheap_tier=args.no_cheap_tier, err=err)
    (out or sys.stdout).write(mode + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
