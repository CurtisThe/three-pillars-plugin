#!/usr/bin/env python3
"""explainer/explain_cli.py — the command line for the explainer pipeline.

Usage:
    explain_cli.py [--root R] <subcommand> [options]

`--root R` is the repo to work on (default: the cwd); it goes to every handler. Each
subcommand prints one JSON line on stdout and returns an exit code: 0 unless noted, 1 for
`enabled` when the explainer is off, 2 for a bad input on a pipeline subcommand
(`{"error": ...}`), 3 for `gate` on a failing draft, 1 for `refresh-needed` when the brief is
current. A bad input on a delivery subcommand is a degrade line instead (see below): it
exits 0 and prints nothing on stdout. The handlers live in
`explain_cli_cmds.py` (pipeline) and `explain_cli_deliver.py` (delivery); this module owns the
argument parser and `main`.

Subcommands (the pipeline set):
    enabled
    request   --kind K --slug S [--subject F] [--base B] [--review-digest F] --out F
    gate      --request F --envelope F
    finalize  --request F --envelope F [--checked F] --out F
    render    --envelope F --format html|markdown|card|log [--head H] [--title T]
              [--slug S] [--html-path P]
    telemetry --row JSON
    report

Subcommands (the delivery set; a forge failure or a bad input prints one `explainer:` line
and exits 0):
    brief           --slug S --envelope F --head H
    headline        --slug S                  (prints nothing when the explainer is off)
    post            --slug S --pr N [--context manual|autonomous] [--kind pr-brief|rulings]
                    [--envelope F]            (--envelope: the refresh form, edits in place)
    refresh-needed  --slug S --pr N           (exit 0 when stale, 1 when current)
    ruling-append   --slug S --envelope F
    rulings-sync    --slug S --pr N [--context manual|autonomous]
    rulings-fold    --slug S
    record-artifact --slug S --kind pr-brief|rulings --url U

A new group of subcommands adds one `_add_<group>(sub)` function and one line in
`build_parser`; each registers its handler with `_command`.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_cli_cmds as cmds  # noqa: E402
import explain_cli_deliver as deliver  # noqa: E402
import explain_state  # noqa: E402

RENDER_FORMATS = ("html", "markdown", "card", "log")
CONTEXTS = ("manual", "autonomous")


def _command(sub, name, handler, help_text):
    """Register subcommand `name`; its parser carries `handler` as `func`."""
    parser = sub.add_parser(name, help=help_text)
    parser.set_defaults(func=handler)
    return parser


def _delivery(sub, name, handler, help_text):
    """`_command` for a delivery subcommand: `main` degrades its errors (exit 0)."""
    parser = _command(sub, name, handler, help_text)
    parser.set_defaults(delivery=True)
    return parser


def _add_pipeline(sub) -> None:
    _command(sub, "enabled", cmds.cmd_enabled, "exit 0 when the explainer is on, 1 when off")
    p = _command(sub, "request", cmds.cmd_request, "build the explain request file")
    p.add_argument("--kind", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--subject", default=None, help="JSON file with the subject object")
    p.add_argument("--base", default=None, help="base ref for the diff evidence")
    p.add_argument("--review-digest", default=None, help="review digest file")
    p.add_argument("--out", required=True)
    p = _command(sub, "gate", cmds.cmd_gate, "run the gate on a drafted envelope")
    p.add_argument("--request", required=True)
    p.add_argument("--envelope", required=True)
    p = _command(sub, "finalize", cmds.cmd_finalize, "write the envelope to render")
    p.add_argument("--request", required=True)
    p.add_argument("--envelope", required=True)
    p.add_argument("--checked", default=None, help="the Opus-checked envelope")
    p.add_argument("--out", required=True)
    p = _command(sub, "render", cmds.cmd_render, "render a final envelope")
    p.add_argument("--envelope", required=True)
    p.add_argument("--format", required=True, choices=RENDER_FORMATS)
    p.add_argument("--head", default=None, help="briefed head (default: the current HEAD)")
    p.add_argument("--title", default=None)
    p.add_argument("--slug", default=None)
    p.add_argument("--html-path", default=None, help="the full explanation, for the card")
    p = _command(sub, "telemetry", cmds.cmd_telemetry, "append one telemetry row")
    p.add_argument("--row", required=True, help="the row, as a JSON object")
    _command(sub, "report", cmds.cmd_report, "print the per-engine rates")


def _slug_pr(parser, *, pr=True) -> None:
    parser.add_argument("--slug", required=True)
    if pr:
        parser.add_argument("--pr", required=True, type=int, help="the PR number")


def _add_delivery(sub) -> None:
    p = _delivery(sub, "brief", deliver.cmd_brief, "write brief.md, the HTML and the envelope")
    _slug_pr(p, pr=False)
    p.add_argument("--envelope", required=True)
    p.add_argument("--head", required=True, help="the head the brief was drafted at")
    p = _delivery(sub, "headline", deliver.cmd_headline, "print the PR-body headline")
    _slug_pr(p, pr=False)
    p = _delivery(sub, "post", deliver.cmd_post, "post or edit the explainer comment")
    _slug_pr(p)
    p.add_argument("--context", choices=CONTEXTS, default="manual")
    p.add_argument("--kind", choices=explain_state.DELIVERY_KINDS, default="pr-brief")
    p.add_argument("--envelope", default=None, help="refresh: render this envelope and edit")
    p = _delivery(sub, "refresh-needed", deliver.cmd_refresh_needed,
                  "exit 0 when the posted brief is stale, 1 when current")
    _slug_pr(p)
    p = _delivery(sub, "ruling-append", deliver.cmd_ruling_append, "append one auto-ruling")
    _slug_pr(p, pr=False)
    p.add_argument("--envelope", required=True)
    p = _delivery(sub, "rulings-sync", deliver.cmd_rulings_sync, "post or edit the rulings comment")
    _slug_pr(p)
    p.add_argument("--context", choices=CONTEXTS, default="manual")
    p = _delivery(sub, "rulings-fold", deliver.cmd_rulings_fold,
                  "fold late rulings into the ledger")
    _slug_pr(p, pr=False)
    p = _delivery(sub, "record-artifact", deliver.cmd_record_artifact, "store the artifact URL")
    _slug_pr(p, pr=False)
    p.add_argument("--kind", required=True, choices=explain_state.DELIVERY_KINDS)
    p.add_argument("--url", required=True)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="explain_cli.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=".", help="repo to work on (default: .)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    _add_pipeline(sub)
    _add_delivery(sub)
    return ap


def main(argv=None) -> int:
    """Run one subcommand; return its exit code (see the module docstring)."""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (cmds.CliError, ValueError, RuntimeError) as exc:
        if getattr(args, "delivery", False):
            return deliver.fail_open(args, exc)
        cmds.emit({"error": str(exc)})
        return cmds.EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
