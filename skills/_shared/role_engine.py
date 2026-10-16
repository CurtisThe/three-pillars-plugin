#!/usr/bin/env python3
"""role_engine.py — the role → engine table and validator.

design: local-role-routing (Task 1.1). The engine roles are named ONCE, in
`model_policy.ENGINE_ROLES`; this module re-exports that same tuple and owns the
engine vocabulary (`local` / `sonnet`; the engine follows the run: `--local` with a
backend is `local`, else `sonnet`), the row efforts (`row_effort`: a `local` row
states its role's Strata effort, every other engine the Sonnet one) and the
config key.
`validate` returns a validated copy of a `role_engines` block plus one warning
per drop, the same drop-and-warn pattern as `model_policy.validate_models`.
`resolve` turns one role into the `{role, engine, model, effort, note}` a
dispatch row is written from. `main` is the CLI (Task 1.3): `resolve <role>`
prints that row as one JSON line and exits 0 (a bad role exits 2), reading the
repo's own config through `load_config` unless `--config` names a file, and
`--decisions` records the resolved engine in decisions.md once per role. Stdlib-only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import cheap_deprecation  # noqa: E402
import cheap_engine  # noqa: E402
import local_backend  # noqa: E402
import local_implement_config  # noqa: E402
import model_policy  # noqa: E402
import strata_effort  # noqa: E402

# The three routable roles — the same tuple object model_policy names them.
ENGINE_ROLES = model_policy.ENGINE_ROLES

# The legal values of the deprecated `role_engines` key. `resolve` never returns `opus`:
# the engine it returns is `local` or `sonnet`, following the run.
ENGINES = ("local", "opus")

# The effort a non-local (Sonnet) engine row states. A `local` row states the
# Strata effort for its role instead — never a bare `high` on Strata
# (design: strata-effort-every-call).
SONNET_ROW_EFFORT = "high"

# The repo-config block holding the role → engine map.
CONFIG_KEY = "role_engines"

# The repo's own config file, read raw by `load_config`.
CONFIG_REL = ".three-pillars/config.json"

# The backend probe, looked up on THIS module at call time by `main`, so a test
# injects it with `monkeypatch.setattr(role_engine, "available", ...)` instead of
# mocking `local_backend`.
available = local_backend.available


def row_effort(role: str, engine: str) -> str:
    """The effort an engine row states: the role's Strata effort when `local`.

    A `local` row states the effort `strata_effort` maps for the role (medium
    or xhigh — never a bare `high` on Strata); every other engine states
    `SONNET_ROW_EFFORT`. A role `strata_effort` has no row for raises
    `ValueError`.
    """
    return strata_effort.role_effort(role) if engine == "local" else SONNET_ROW_EFFORT


def _warning(key: str, value, is_role: bool) -> str:
    vocab = " or ".join(ENGINE_ROLES) if is_role else " or ".join(ENGINES)
    what = "role" if is_role else "engine"
    return (
        f"config: dropped {CONFIG_KEY}.{key} ({value!r}) — legal {what} values: {vocab}"
    )


def validate(block) -> tuple[dict, list[str]]:
    """Return a validated copy of a `role_engines` block plus one warning per drop.

    A key outside `ENGINE_ROLES` is dropped with one warning; a value outside
    `ENGINES` is dropped with one warning. Non-dict -> `({}, [])` (the same
    shape as `model_policy.validate_models`).
    """
    if not isinstance(block, dict):
        return {}, []
    kept: dict = {}
    warnings: list[str] = []
    for key, value in block.items():
        if key not in ENGINE_ROLES:
            warnings.append(_warning(str(key), value, True))
        elif value not in ENGINES:
            warnings.append(_warning(str(key), value, False))
        else:
            kept[key] = value
    return kept, warnings


def _local_model(root) -> tuple[str, str | None]:
    """The Agent alias for the local backend's model, plus a note when it is not one.

    The model comes from the `local_implement` block (`DEFAULTS` when the block
    is absent). That config only validates the model as a non-empty string, and
    `Agent(model=)` takes an `AGENT_ALIASES` member, so a non-alias model is
    reported and replaced by `local_implement_config.DEFAULTS["model"]`.
    """
    cfg = local_implement_config.load(root) or local_implement_config.DEFAULTS
    configured = cfg["model"]
    alias = model_policy.agent_alias(configured)
    if alias is not None:
        return alias, None
    return (
        local_implement_config.DEFAULTS["model"],
        f"role-engine: local model {configured} is not an Agent alias; using "
        f"{local_implement_config.DEFAULTS['model']}",
    )


def run_local(config) -> bool:
    """Whether the run is `--local`: flag-less, so `TP_LOCAL` > the repo default.

    A module-level seam: callers that pass no `local` follow the run, and tests
    fake this with `monkeypatch.setattr(role_engine, "run_local", ...)`.
    """
    cfg = config if isinstance(config, dict) else {}
    return bool(cheap_engine.resolve_run(cfg)["local"])


def resolve(role: str, config, *, root=".", available=local_backend.available,
            local=None) -> dict:
    """`{role, engine, model, effort, note}` — the dispatch row's engine and model.

    The engine follows the run (design: one-cheap-engine) through
    `cheap_engine.engine_for`: no `--local` -> `sonnet`; `--local` with a backend
    -> `local` (the `local_implement` model normalised through
    `model_policy.agent_alias`); `--local` without one -> `sonnet` plus the M51
    note. `local=None` follows the run via `run_local(config)`. A set
    `role_engines` key changes nothing; it adds one deprecation line to `note`.
    A role outside `ENGINE_ROLES` raises `ValueError`.
    """
    if role not in ENGINE_ROLES:
        raise ValueError(
            f"unknown engine role: {role!r} — roles: {', '.join(ENGINE_ROLES)} "
            "(judgment roles have no role_engines key; they stay on opus)"
        )
    cfg = config if isinstance(config, dict) else {}
    on = run_local(cfg) if local is None else bool(local)
    # The route is checked at spawn (strata_spawn.wait), so it is "routed/ok" here.
    got = cheap_engine.engine_for(role, {"local": on}, "routed/ok", available, root=root)
    notes = [got["note"]] if got["note"] else []
    engine, model = got["engine"], got["model"]
    if engine == "strata":
        engine = "local"
        model, model_note = _local_model(root)
        if model_note:
            notes.append(model_note)
    notes += cheap_deprecation.notes(cfg)
    return {"role": role, "engine": engine, "model": model,
            "effort": row_effort(role, engine),
            "note": "; ".join(notes) if notes else None}


def _read_raw(path):
    """Parse `path` as JSON, or `{}` when it is missing or unparseable."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return {}


def load_config(root=".") -> dict:
    """The raw repo config at `<root>/.three-pillars/config.json` (missing/bad → `{}`).

    Deliberately raw JSON, never `repo_config_load.load_repo_config`: that one
    prunes root keys its schema does not yet know, so it would drop the
    `role_engines` block until Task 1.4 adds it to the schema. A missing or
    unparseable file is `{}`, so every role follows the run (`sonnet`, or `local`
    under `--local`) instead of raising.
    """
    return _read_raw(Path(root) / CONFIG_REL)


def _decisions_line(row) -> str:
    """`[role-engine] <role> → <engine> (<model>)`, plus `: <note>` when one is set."""
    line = f"[role-engine] {row['role']} → {row['engine']} ({row['model']})"
    if row["note"] is not None:
        line += f": {row['note']}"
    return line


def _record_decisions(path, row) -> None:
    """Append the row's line to decisions.md `path` unless that line is already there.

    Once per role per run, and idempotent across runs: an existing file keeps its
    content, a missing file (or a missing parent dir) is created.
    """
    line = _decisions_line(row)
    dest = Path(path)
    existing = dest.read_text(encoding="utf-8") if dest.exists() else ""
    if line in existing.splitlines():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main(argv=None) -> int:
    """`resolve <role>` — one JSON line for the dispatch row, exit 0 (bad role: 2).

    `--root` is the repo whose `.three-pillars/config.json` is the default config
    source (also passed to `resolve(root=)`, which reads its `local_implement`
    block); `--config` overrides it with a path to a full config file. The
    backend probe is read off this module's `available` at call time.
    `--decisions D` records the resolved engine in `D` once per role.
    """
    ap = argparse.ArgumentParser(prog="role_engine.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resolve", help="print one role's engine row as JSON")
    r.add_argument("role")
    r.add_argument("--root", default=".", help="repo to read config from (default: .)")
    r.add_argument("--config", default=None, help="path to a full config JSON file")
    r.add_argument("--decisions", default=None, help="decisions.md to record the row in")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--local", action="store_true")
    g.add_argument("--no-local", action="store_true")
    a = ap.parse_args(argv)

    root = a.root
    config = _read_raw(a.config) if a.config else load_config(root)
    local = True if a.local else False if a.no_local else None
    try:
        row = resolve(a.role, config, root=root, available=available, local=local)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(row))
    if a.decisions:
        _record_decisions(a.decisions, row)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
