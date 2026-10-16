"""explainer/explain_state.py — the explainer's out-of-tree local state.

Public API (every function takes the repo `root` first and resolves the state root
itself; there is no module-level or cwd default):
    DELIVERY_KINDS                       ("pr-brief", "rulings") — the closed delivery kinds
    TELEMETRY_KEYS                       the ten keys of one telemetry row
    state_root(root) -> Path             <git common dir>/three-pillars/explainer/
    delivery(root, slug, kind, update=None) -> dict
    record_degraded(root, slug, kind, reason) -> dict
    telemetry_append(root, row) -> dict  appends one NDJSON line; returns the row written
    report(root) -> dict                 {engine: {n, rewrite_rate, check_rewritten_rate}}

State lives under the git common dir (`git rev-parse --git-common-dir`, run with
cwd=root and resolved to an absolute path). That dir is out of tree, shared by every
linked worktree of the repo, and kept after a worktree is torn down, so telemetry builds
up. `state_root` only computes the path; the writers create directories on demand.
A root that is not inside a git repo raises RuntimeError.

Delivery record: `<state_root>/<slug>/delivery.json`, keyed by delivery kind:
    {"pr-brief": {comment_id, posted_head, html, artifact_url, degraded: [...]},
     "rulings": {...}}
`delivery(root, slug, kind)` is the read form; it returns a copy of that kind's entry,
or `{}` when none is stored. `delivery(root, slug, kind, update={...})` is the write
form: it merges `update` into that kind's entry (a key in `update` replaces the stored
value; a `degraded` list is unioned into the stored one, keeping first-seen order and
storing each reason once), writes the file atomically and returns the merged entry. It
reads and writes only its own kind's entry, so the brief and the rulings comment never
share a `comment_id`. Any kind outside DELIVERY_KINDS raises ValueError. `slug` must be
a single path component (no separator, not `.` or `..`), else ValueError. A missing,
unreadable or non-object delivery file reads as empty and is replaced on the next write.
`record_degraded(root, slug, kind, reason)` adds one reason to `degraded`.

Telemetry: `<state_root>/telemetry.ndjson`, one JSON object per line with exactly
TELEMETRY_KEYS; keys the caller leaves out get a default (`ts` the current UTC time,
`rewrite_used` / `facts_only` False, `degraded` [], the rest None) and unknown keys are
dropped. `report` groups rows by `engine` (a row without one counts under "unknown") and
gives, per engine, `n`, `rewrite_rate` (rows with `rewrite_used` over n) and
`check_rewritten_rate` (rows whose `check_outcome` is "rewritten" over n), rounded to
four places. A missing file gives `{}`; a malformed line is skipped.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

DELIVERY_KINDS = ("pr-brief", "rulings")
TELEMETRY_KEYS = ("ts", "slug", "kind", "engine", "served", "gates", "rewrite_used",
                  "check_outcome", "facts_only", "degraded")
_STATE_SUBPATH = ("three-pillars", "explainer")
_DELIVERY_FILE = "delivery.json"
_TELEMETRY_FILE = "telemetry.ndjson"
_UNKNOWN_ENGINE = "unknown"
_RATE_PLACES = 4


def state_root(root) -> Path:
    """`<git common dir>/three-pillars/explainer/` for the repo containing `root`."""
    base = Path(root)
    try:
        proc = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=str(base),
                              capture_output=True, text=True, check=False)
    except OSError as exc:
        raise RuntimeError(f"explain_state: cannot run git in {base}: {exc}") from exc
    out = proc.stdout.strip()
    if proc.returncode != 0 or not out:
        detail = proc.stderr.strip() or "no output"
        raise RuntimeError(f"explain_state: {base} is not inside a git repo ({detail})")
    common = Path(out)
    if not common.is_absolute():
        common = base / common
    return common.resolve().joinpath(*_STATE_SUBPATH)


def _check_kind(kind) -> None:
    if kind not in DELIVERY_KINDS:
        raise ValueError(f"explain_state: unknown delivery kind {kind!r}; "
                         f"expected one of {DELIVERY_KINDS}")


def _check_slug(slug) -> None:
    if (not isinstance(slug, str) or not slug or slug in (".", "..")
            or "/" in slug or "\\" in slug or "\0" in slug):
        raise ValueError(f"explain_state: slug {slug!r} must be a single path component")


def _read_json_object(path: Path) -> dict:
    """The JSON object in `path`, or `{}` when it is missing, unreadable or not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _union(stored, incoming) -> list:
    """`stored` then the items of `incoming` not already present, first-seen order."""
    merged: list = []
    for item in _as_list(stored) + _as_list(incoming):
        if item not in merged:
            merged.append(item)
    return merged


def delivery(root, slug, kind, update=None) -> dict:
    """Read (`update` None) or merge-update one delivery kind's entry; return the entry."""
    _check_kind(kind)
    _check_slug(slug)
    path = state_root(root) / slug / _DELIVERY_FILE
    record = _read_json_object(path)
    entry = record.get(kind)
    entry = dict(entry) if isinstance(entry, dict) else {}
    if update is None:
        return entry
    for key, value in dict(update).items():
        if key == "degraded":
            entry[key] = _union(entry.get(key), value)
        else:
            entry[key] = value
    record[kind] = entry
    _write_json_atomic(path, record)
    return dict(entry)


def record_degraded(root, slug, kind, reason) -> dict:
    """Add `reason` to the kind's `degraded` list (once); return the entry."""
    return delivery(root, slug, kind, update={"degraded": [reason]})


_ROW_DEFAULTS = {"slug": None, "kind": None, "engine": None, "served": None, "gates": None,
                 "check_outcome": None}


def _telemetry_row(row) -> dict:
    src = dict(row)
    out: dict = {"ts": src.get("ts") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    for key in TELEMETRY_KEYS[1:]:
        if key in src:
            out[key] = src[key]
        elif key == "degraded":
            out[key] = []
        elif key in ("rewrite_used", "facts_only"):
            out[key] = False
        else:
            out[key] = _ROW_DEFAULTS[key]
    return out


def telemetry_append(root, row) -> dict:
    """Append one telemetry row as a single NDJSON line; return the row as written."""
    out = _telemetry_row(row)
    path = state_root(root) / _TELEMETRY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(out, sort_keys=False) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
    return out


def _telemetry_rows(path: Path) -> list:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def report(root) -> dict:
    """Per-engine `{n, rewrite_rate, check_rewritten_rate}` over the telemetry rows."""
    tally: dict = {}
    for row in _telemetry_rows(state_root(root) / _TELEMETRY_FILE):
        engine = row.get("engine") or _UNKNOWN_ENGINE
        counts = tally.setdefault(engine, [0, 0, 0])
        counts[0] += 1
        counts[1] += 1 if row.get("rewrite_used") else 0
        counts[2] += 1 if row.get("check_outcome") == "rewritten" else 0
    return {
        engine: {"n": n,
                 "rewrite_rate": round(rewrites / n, _RATE_PLACES),
                 "check_rewritten_rate": round(rewritten / n, _RATE_PLACES)}
        for engine, (n, rewrites, rewritten) in tally.items()
    }
