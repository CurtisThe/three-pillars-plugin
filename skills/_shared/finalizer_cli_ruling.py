"""finalizer_cli_ruling.py — the ruling scope and ruling-file write for finalizer_cli.

design: fable-escalation (Task 4.3), split out of finalizer_cli.py by its size pin.
``_ruling_scope`` resolves a stop's scope from ``--scope`` or from a ``--decisions``
path under ``tp-designs/<slug>/`` or ``completed-tp-designs/<slug>/`` (Tier 7, after
archive) — never the ledger. ``write_ruling`` writes the ruling file under the
project root (cwd when not in a repo). Stdlib only.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

import finalizer_ruling as fr
import project_root
import ruling_file as rf

_DECISIONS_SCOPE = re.compile(r"(?:^|/)(?:tp-designs|completed-tp-designs)/([^/]+)/decisions\.md$")
_LIVE_DESIGN = re.compile(r"^(?P<head>(?:.*?/)?)tp-designs/(?P<slug>[^/]+)(?P<tail>(?:/.*)?)$")


def archived_path(p):
    """``p`` re-pointed at ``completed-tp-designs/<slug>/`` once Tier 5.6 archived the run.

    design: seat-escalate-first (Task 2.3). A run keeps passing its usual
    ``tp-designs/<slug>/...`` paths after the archive; the rewrite fires only when that
    in-flight directory is gone and the archived one exists, so nothing recreates
    ``tp-designs/<slug>/``. Any other path (and ``None``) comes back unchanged.
    """
    match = _LIVE_DESIGN.match(p) if isinstance(p, str) else None
    if not match:
        return p
    head, slug, tail = match.group("head"), match.group("slug"), match.group("tail")
    archived = f"{head}completed-tp-designs/{slug}"
    if Path(f"{head}tp-designs/{slug}").exists() or not Path(archived).is_dir():
        return p
    return archived + tail


def _ruling_scope(args, stop):
    """The scope for this call: ``--scope`` if given, else the ``<slug>`` of a
    design-shaped ``--decisions`` path; None when neither names a scope."""
    scope = getattr(args, "scope", None)
    if scope:
        return scope
    decisions = Path(str(getattr(args, "decisions", "") or "")).as_posix()
    match = _DECISIONS_SCOPE.search(decisions)
    return match.group(1) if match else None


def ruling_payload(result):
    """The ruling file's result: the CLI result plus every ``EMPTY_RULING`` key it
    lacks — taken from its own nested ``ruling`` (an ``apply`` result), else a deep
    copy of the empty default (an ``escalate`` has no reply, so its ruling is empty).
    """
    out = dict(result)
    nested = result.get("ruling") if isinstance(result.get("ruling"), dict) else {}
    for key, value in fr.EMPTY_RULING.items():
        if key not in out:
            out[key] = copy.deepcopy(nested.get(key, value))
    return out


def write_ruling(args, stop, key, result, model, scope):
    """Write the scoped stop's ruling file; return ``(ruling_id, ruling_path)``.

    Raises what ``ruling_file.write`` raises (a refused scope pairing, a clash
    after ``#3``); the caller fails open with one line.
    """
    root = project_root.find_project_root() or Path.cwd()
    path = rf.write(root, scope=scope, entry=getattr(args, "entry", "run"),
                    stop=stop, key=key, result=ruling_payload(result), model=model)
    return path.stem, str(path)
