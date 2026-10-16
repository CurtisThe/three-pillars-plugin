"""explainer/explain_rulings.py — the rulings ledgers, the rolling comment and the late fold.

Public API (every function takes the repo `root` first; there is no cwd default):
    RULINGS_KIND                         "rulings", the delivery kind of the one rulings comment
    append_ruling(root, slug, env) -> str
    all_rows(root, slug) -> list[dict]
    sync_rulings(root, slug, pr, *, context="manual", forge_mod=forge, head=None) -> Result | None
    fold_late(root, slug) -> int

A ruling is an auto-ruling envelope plus its ledger id `r<n>`; the ledger row is the envelope
with that `id` set (a caller-supplied `id` never wins). Two ledgers hold the rows:
    <design dir>/rulings.ndjson          committed with the design (the design dir is
                                         `three-pillars-docs/tp-designs/<slug>/`, or
                                         `completed-tp-designs/<slug>/` once archived);
    <state>/<slug>/rulings-late.ndjson   out of tree (`<state>` is `explain_state.state_root`),
                                         for rulings made after archival.

`append_ruling` never commits and returns the new id.
    Before archival (`tp-designs/<slug>/` exists) it appends the row to the design ledger and
    the log entry (`explain_card.render_log_entry`, the auto-mode Decision Entry) to
    `decisions.md`, creating that file with the schema-v1 header when it is missing. The
    caller's next commit stages both.
    After archival (only `completed-tp-designs/<slug>/` exists), or with no design dir at all,
    it appends only the row to the late ledger, so the tree stays clean and the briefed head
    does not move. The log entry is not stored: it is a pure function of the row, so
    `fold_late` renders it again.
The id continues across both ledgers: `n` is the count of distinct ids in the design-dir (or
archived) ledger and the late ledger, plus 1. If a ledger has a gap (an id above that count),
`n` is one past the highest id, so an id is never reused.

`all_rows` is the rows of both ledgers, one per id (the design-dir row wins), in id order
(`r2` before `r10`).

`sync_rulings` rebuilds the one rulings comment from `all_rows` and hands it to
`explain_deliver.post_or_edit(..., kind="rulings", context=context, forge_mod=forge_mod)`. With
no rows it does nothing and returns None (no forge call, no state written). Otherwise it
returns the forge `Result`; a degraded one is also reported through
`explain_deliver.degrade_line` (one `explainer:` line on stderr, the reason logged once in the
kind's delivery entry), so a forge that cannot post is never silent. The body is built with the
design `slug` in its marker: `post_or_edit` finds the comment again by kind and slug, so a
second sync edits it and does not post a duplicate. The marker `head` is `head` when given,
else the repo's `git rev-parse HEAD` (the head at sync time), else the stored rulings
`posted_head`, else "unknown". The marker fallback ignores the head, so it may change.

`fold_late` copies each late row (ids kept) that the design-dir ledger lacks into that ledger,
adds its rendered log entry to `decisions.md` when the log lacks one, then empties the late
ledger, and returns how many rows it added. It never commits (Tier 7 runs it just before
the terminal log flush, which commits or leaves the files dirty). It does nothing and returns 0
when the late ledger holds no rows or there is no design dir to fold into. A fold that stopped
part way can run again: a row or entry already there is not written twice, and the late ledger
is emptied last, so no ruling is lost.

`slug` must be one path component, else ValueError before anything is written. Stdlib only.
Flat-import package — no __init__.py.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_card  # noqa: E402
import explain_deliver  # noqa: E402
import explain_markdown  # noqa: E402
import explain_sources  # noqa: E402
import explain_state  # noqa: E402
import forge  # noqa: E402

RULINGS_KIND = "rulings"
DECISIONS_FILE = "decisions.md"
SCHEMA_HEADER = "# Decisions log — schema v1\n"
_LIVE_TREE = explain_sources.DESIGN_TREES[0]
_ID_RE = re.compile(r"^r(\d+)$")
_UNKNOWN_HEAD = "unknown"


def _read(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return ""


def _append_text(path: Path, text: str) -> None:
    """Append `text`, first ending a final line the file left open."""
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = ""
    try:
        with path.open("rb") as fh:
            if fh.seek(0, 2):
                fh.seek(-1, 2)
                prefix = "" if fh.read(1) == b"\n" else "\n"
    except FileNotFoundError:
        pass
    with path.open("a", encoding="utf-8") as fh:
        fh.write(prefix + text)


def _append_row(path: Path, row: dict) -> None:
    _append_text(path, json.dumps(row, ensure_ascii=False) + "\n")


def _append_entry(log: Path, entry: str) -> None:
    text = "\n" + entry.rstrip() + "\n"
    _append_text(log, text if log.exists() else SCHEMA_HEADER + text)


def _has_entry(log_text: str, rid: str) -> bool:
    return re.search(rf"^### \[explainer\] Ruling {re.escape(rid)}:", log_text,
                     re.MULTILINE) is not None


def _late_path(root, slug) -> Path | None:
    return explain_sources.late_ledger_path(root, slug)


def _late_rows(root, slug) -> list:
    late = _late_path(root, slug)
    return explain_sources.ledger_rows(_read(late)) if late is not None else []


def _main_rows(design) -> list:
    if design is None:
        return []
    return explain_sources.ledger_rows(_read(design / explain_sources.LEDGER_FILE))


def _next_n(*ledgers) -> int:
    ids = {row["id"] for rows in ledgers for row in rows}
    top = max((int(m.group(1)) for m in map(_ID_RE.match, ids) if m), default=0)
    return max(len(ids), top) + 1


def append_ruling(root, slug, env) -> str:
    """Add `env` to the right ledger, return its id `r<n>`; commit nothing."""
    explain_state._check_slug(slug)
    if not isinstance(env, dict):
        raise ValueError("explain_rulings: a ruling envelope must be an object")
    design = explain_sources.design_dir(root, slug)
    live = design is not None and design.parent.name == _LIVE_TREE
    rid = f"r{_next_n(_main_rows(design), _late_rows(root, slug))}"
    row = {"id": rid, **{k: v for k, v in env.items() if k != "id"}}
    json.dumps(row, ensure_ascii=False)  # fail before any file is touched
    entry = explain_card.render_log_entry(row)
    if live:
        _append_row(design / explain_sources.LEDGER_FILE, row)
        _append_entry(design / DECISIONS_FILE, entry)
        return rid
    late = _late_path(root, slug)
    if late is None:
        raise RuntimeError(f"explain_rulings: {root} has no explainer state root (not a git repo)")
    _append_row(late, row)
    return rid


def _order(row) -> tuple:
    m = _ID_RE.match(row["id"])
    return (0, int(m.group(1)), "") if m else (1, 0, row["id"])


def all_rows(root, slug) -> list:
    """The rows of both ledgers, one per id, in id order."""
    explain_state._check_slug(slug)
    design = explain_sources.design_dir(root, slug)
    merged: dict = {}
    for row in _main_rows(design) + _late_rows(root, slug):
        merged.setdefault(row["id"], row)
    return sorted(merged.values(), key=_order)


def _repo_head(root, slug) -> str:
    out = explain_sources._git_out(root, "rev-parse", "HEAD")
    head = (out or "").strip()
    if head:
        return head
    stored = explain_state.delivery(root, slug, RULINGS_KIND).get("posted_head")
    return str(stored) if stored else _UNKNOWN_HEAD


def sync_rulings(root, slug, pr, *, context="manual", forge_mod=forge, head=None):
    """Rebuild and post-or-edit the one rulings comment; None when there are no rows."""
    rows = all_rows(root, slug)
    if not rows:
        return None
    html_hint = explain_state.delivery(root, slug, RULINGS_KIND).get("html")
    body = explain_markdown.render_rulings_comment(
        rows, head=head or _repo_head(root, slug), html_hint=html_hint, slug=slug)
    result = explain_deliver.post_or_edit(root, slug, pr, body, kind=RULINGS_KIND,
                                          context=context, forge_mod=forge_mod)
    if result.status != "ok":
        explain_deliver.degrade_line(root, slug, RULINGS_KIND, result.line)
    return result


def fold_late(root, slug) -> int:
    """Move the late rows into the design-dir ledger and log; empty the late ledger."""
    explain_state._check_slug(slug)
    late = _late_path(root, slug)
    design = explain_sources.design_dir(root, slug)
    rows = _late_rows(root, slug)
    if late is None or design is None or not rows:
        return 0
    ledger = design / explain_sources.LEDGER_FILE
    log = design / DECISIONS_FILE
    have = {row["id"] for row in _main_rows(design)}
    log_text = _read(log)
    moved = 0
    for row in rows:
        rid = row["id"]
        if rid not in have:
            _append_row(ledger, row)
            have.add(rid)
            moved += 1
        if not _has_entry(log_text, rid):
            entry = explain_card.render_log_entry(row)
            _append_entry(log, entry)
            log_text += "\n" + entry
    late.write_text("", encoding="utf-8")
    return moved
