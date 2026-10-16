#!/usr/bin/env python3
"""router_main_thread.py — sessions whose MAIN thread took Strata (the S3 leak).

design: main-thread-direct-backend S3 (Task 1.3)

Strata is meant for fenced children: their requests carry `agent=<8ch>`. A session that
also sends an **unagented** `-> local` request has its main thread in the local slot —
the thing the direct-backend design exists to stop. The tell is the pair in one session:
an unagented `-> local` request, and an unagented `-> upstream` request that is not a
classifier call (by `router_checks.parse_line`'s test: it carries `effort=`, or its model
is not the classifier model — i.e. the host's own Claude turn, not its cost-check call).

An all-Strata session (sanctioned cheap-tier run) has no such upstream turn, and a
child-spawn session has every `-> local` line agent-tagged, so both stay clean. `router_checks.main`
turns each leak into one `ALARM main_thread_strata <sess>` line and a non-zero exit.
`REQUEST_RE` is imported, never re-declared, so the router's line shape has one source.
Nothing here raises: an unreadable file or line is skipped.
"""
from __future__ import annotations

from pathlib import Path

import router_stats
from router_checks import DEFAULT_CLASSIFIER_MODEL, REQUEST_RE


def _agented(mid: str) -> bool:
    """Whether the `sess=`…`->` span carries `agent=` — a child-spawn call."""
    return "agent=" in mid


def _main_thread_upstream(model: str, mid: str, classifier_model: str) -> bool:
    """An unagented `-> upstream` request that is NOT a classifier call.

    A classifier call is `classifier_model` with no `agent=` and no `effort=`; anything
    else unagented upstream is the main thread's own turn on Claude."""
    if _agented(mid):
        return False
    return "effort=" in mid or model != classifier_model


def leak_sessions(path, since=None, until=None,
                  classifier_model: str = DEFAULT_CLASSIFIER_MODEL) -> list[str]:
    """Sessions in `path` (within [since, until]) whose main thread took Strata.

    A session leaks when it holds both an unagented `-> local` request and an unagented
    `-> upstream` request that is not a classifier call. Leaks come back in
    first-appearance order, one entry per session. `since`/`until` are epoch seconds (or
    None); a missing or unreadable file, and any line that is not a matched request with
    a readable `<ts>`, gives nothing."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except (OSError, TypeError):
        return []
    order: list[str] = []
    seen: set[str] = set()
    local: set[str] = set()
    mainline: set[str] = set()
    for line in text.splitlines():
        m = REQUEST_RE.match(line)
        if not m:
            continue
        epoch = router_stats.ts_epoch(m["ts"])
        if epoch is None:
            continue
        if since is not None and epoch < since:
            continue
        if until is not None and epoch > until:
            continue
        sess = m["sess"]
        if sess not in seen:
            seen.add(sess)
            order.append(sess)
        mid = m["mid"] or ""
        if m["route"].startswith("local") and not _agented(mid):
            local.add(sess)
        elif m["route"] == "upstream" and _main_thread_upstream(
                m["model"], mid, classifier_model):
            mainline.add(sess)
    return [s for s in order if s in local and s in mainline]
