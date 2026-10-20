"""Re-arm the ready state after a base-sync (ready-ping-after-basesync 1.2).

A ``ready`` ping skipped while the PR conflicted leaves an ``owed`` record in
the slug's ledger (task 1.1). After a base-sync pushes a new head, ``rearm``
checks that the PR once converged, polls the mergeability until it settles,
and when MERGEABLE puts the ``tp:ready-for-human-merge`` label back and sends
the ready ping for the new head. A PR that never converged gets neither; a PR
still conflicting (or unsettled after the last poll) stays owed for ``head``.

Fail-open: ``rearm`` never raises into its caller and ``main`` always returns 0.
"""

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import ready_ping
from ready_ping_owed import converged_before, record_owed

READY_LABEL = "tp:ready-for-human-merge"
MERGEABLE = "MERGEABLE"
CONFLICTING = "CONFLICTING"
_LABEL_MODULE = (Path(__file__).resolve().parents[1]
                 / "tp-pr-fix" / "scripts" / "label_manager.py")


def _fetch(info_fn, pr_url):
    """One mergeability lookup as a dict; ``{}`` on a raise or a bad shape."""
    try:
        info = (info_fn or ready_ping.pr_info)(pr_url)
    except Exception:
        return {}
    return info if isinstance(info, dict) else {}


def _default_label(pr_url, label):
    """Put ``label`` back via the shipped label manager, loaded by path."""
    spec = importlib.util.spec_from_file_location("label_manager", _LABEL_MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ensure_pr_label(pr_url, label)


def _set_label(label_fn, pr_url):
    """``"set"`` when the label is applied, ``"failed: <type>"`` otherwise."""
    try:
        (label_fn or _default_label)(pr_url, READY_LABEL)
        return "set"
    except Exception as exc:
        return f"failed: {type(exc).__name__}"


def _settle(info, info_fn, pr_url, attempts, sleep_fn, delay):
    """Poll until MERGEABLE/CONFLICTING or ``attempts`` lookups; return (info, state)."""
    state = info.get("mergeable")
    tries = 1
    while state not in (MERGEABLE, CONFLICTING) and tries < attempts:
        sleep_fn(delay)
        info = _fetch(info_fn, pr_url)
        state = info.get("mergeable")
        tries += 1
    return info, state


def rearm(pr_url, head, *, info_fn=None, label_fn=None, ledger=None, decisions=None,
          push_fn=None, out=None, err=None, attempts=4, delay=5.0, sleep_fn=time.sleep):
    """Re-arm ``pr_url`` for ``head`` when it converged before, else do nothing.

    Returns ``{"status": "skipped", "reason": ...}`` for a PR that never
    converged, a PR that is not mergeable, or one whose mergeability is
    unavailable; ``{"status": "rearmed", "label": ..., "ready_ping": ...}``
    when MERGEABLE (label set, ready ping sent or duplicate).
    """
    err = err if err is not None else sys.stderr
    info = _fetch(info_fn, pr_url)
    if not info:
        print(f"ready-ping: mergeability unavailable for {pr_url}; "
              f"no ready ping sent", file=err)
        return {"status": "skipped", "reason": "mergeability-unavailable"}
    slug = ready_ping._slug_from_ref(info.get("headRefName"))
    ledger_file = ledger if ledger is not None else ready_ping.ledger_path(slug)
    if not converged_before(ledger_file):
        return {"status": "skipped", "reason": "not-converged"}
    info, state = _settle(info, info_fn, pr_url, attempts, sleep_fn, delay)
    if state != MERGEABLE:
        print(f"ready-ping: PR {pr_url} still owed for {head} "
              f"(mergeable={state}); ready ping skipped", file=err)
        record_owed(slug, ready_ping.pr_number(pr_url), head, ledger_file)
        return {"status": "skipped", "reason": "not-mergeable"}
    label_status = _set_label(label_fn, pr_url)
    result = ready_ping.ping_ready(
        pr_url, head, info_fn=lambda _u: info, ledger=ledger_file,
        decisions=decisions, push_fn=push_fn, out=out,
    )
    return {"status": "rearmed", "label": label_status, "ready_ping": result}


def _parser():
    parser = argparse.ArgumentParser(
        prog="ready_ping_rearm",
        description="Re-arm the ready state of a PR after a base-sync.")
    parser.add_argument("--pr-url", required=True, help="the PR URL")
    parser.add_argument("--head", required=True, help="the new head sha")
    parser.add_argument("--decisions", default=None, help="decisions.md to append to")
    return parser


def main(argv=None):
    """CLI: one JSON line on stdout, exit 0 always (fail-open)."""
    try:
        args = _parser().parse_args(argv)
        result = rearm(args.pr_url, args.head, decisions=args.decisions)
    except SystemExit as exc:  # argparse: usage error (or --help, which prints and exits 0)
        if exc.code in (0, None):
            return 0
        result = {"status": "error", "reason": f"usage: argparse exit {exc.code}"}
    except Exception as exc:
        result = {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
