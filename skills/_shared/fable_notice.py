#!/usr/bin/env python3
"""fable_notice.py — the design-run fable warning + decisions.md entry.

One responsibility: when a design run's resolved model contains `fable` (the
rare-exception `models.design_run` value, never a default), print one stderr
warning and append one decisions.md entry. The launchers call it once per run;
`model_policy` holds only the model policy and imports nothing here.
Stdlib-only; imports no other project module.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def fable_notice(model, decisions_path, *, write=True, launcher=None):
    """Warn once for a fable design run and append one decisions.md entry.

    A model containing `fable` (case-insensitive) is the rare-exception path:
    print one stderr line and, when `write`, append one `### [design-run] fable
    model` entry (file created if absent). Any other model returns None and
    touches nothing; one warning + entry per call is the launcher's contract.
    """
    if "fable" not in str(model).lower():
        return None
    line = (
        "WARNING: design run using fable (models.design_run) — "
        "rare-exception model, not the default"
    )
    print(line, file=sys.stderr)
    if write:
        _append_fable_entry(decisions_path, str(model), launcher)
    return line


def _append_fable_entry(decisions_path, model, launcher):
    """Append one short fable entry (a single O_APPEND write); create the file
    (and parent dirs) if absent."""
    path = Path(decisions_path)
    if launcher is None:
        launcher = Path(sys.argv[0] or "").name or "design run launcher"
    entry = (
        "### [design-run] fable model\n"
        f"**Model**: {model}\n"
        f"**Launcher**: {launcher}\n"
        "**Note**: rare-exception model set explicitly in models.design_run; "
        "never a default\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    # One O_APPEND write: never rewrites what concurrent writers already appended.
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        prefix = ""
        if os.fstat(fd).st_size:  # existing file: one blank line before the entry
            with open(path, "rb") as fh:
                fh.seek(-1, os.SEEK_END)
                prefix = "\n" if fh.read(1) == b"\n" else "\n\n"
        os.write(fd, (prefix + entry).encode("utf-8"))
    finally:
        os.close(fd)
