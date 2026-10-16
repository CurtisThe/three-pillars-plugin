"""certify_cli_lean — the certifier-lean `certify.py` subcommands, one registration point.

design: certifier-lean (Task 1.1; plan Conventions: one CLI surface).

`certify_cli.build_parser` calls `register(sub)` once, after `certify_cli_checks`.
`MODULES` is the whole list: each named module exposes `register(sub)` (argparse
subparsers, `set_defaults(func=…)`) whose func returns an exit code and raises
`certify_cli.BadInput` for exit 2. A later certifier-lean task adds its module name to
`MODULES` — one line — instead of touching `certify_cli.py`. Each module is imported by
name at call time, so `certify_cli` stays importable on its own and no cycle forms.
"""

from __future__ import annotations

import importlib

MODULES = ("cert_claim_lint", "cert_route", "cert_mutant", "cert_fix_plan", "cert_gap",
           "cert_brief")


def register(sub) -> None:
    """Register every lean subcommand module on `certify.py`'s subparsers."""
    for name in MODULES:
        importlib.import_module(name).register(sub)
