"""explainer/explain_sources.py — deterministic evidence readers.

Public API (each returns a list of evidence items ``{ref, label, text}``):
    design_items(root, slug)      design:problem|scope|dependencies|
                                  consumer-repo|forge|loci, in that order
    decision_items(root, slug)    decision:<n> per "### " entry of
                                  decisions.md (1-based)
    ruling_items(root, slug)      ruling:<id> per row of rulings.ndjson, then
                                  of the late ledger (each row stores its id)
    ledger_rows(text)             the valid rows of one rulings ledger's text
    late_ledger_path(root, slug)  the out-of-tree rulings-late.ndjson, or None
    audit_items(root, slug)       audit:verdict, the first line of
                                  implementation-audit.md holding "verdict"
    review_items(review_digest)   review:digest, the review digest file
    subject_items(subject)        subject:<field> per top-level key
    git_items(root, base)         diffstat, tree:<dir> per touched dir
                                  (sorted), then config:diff
    design_dir(root, slug)        the design dir, or None

The design dir is ``three-pillars-docs/tp-designs/<slug>/`` when it exists,
else ``three-pillars-docs/completed-tp-designs/<slug>/`` (archived). Every
reader is best-effort: a missing or unreadable source adds no item and never
raises (``OSError``/``ValueError`` are caught per source; a malformed ledger
row is skipped on its own; a failed git call adds nothing). The ref ids are
the closed set of detailed-design §Interfaces.

The late rulings ledger is ``<state>/<slug>/rulings-late.ndjson`` (``<state>``
is ``explain_state.state_root``, out of tree). ``explain_rulings`` writes a
ruling there once the design is archived, so ``ruling_items`` reads it after
the design-dir ledger and a refresh cites late rulings too. A row id that
both ledgers hold is listed once (the design-dir row wins). A root outside a
git repo has no state root, so only the design-dir ledger is read.

Git runs with the shipped ``task_scope._git_env`` scrub (``git_env`` is
dev-only). Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_state  # noqa: E402
from task_scope import _git_env  # noqa: E402 — git_env is dev-only

DOCS_DIR = "three-pillars-docs"
# The most sibling names one tree:<dir> item lists.
TREE_CAP = 20
CONFIG_PATH = ".three-pillars/config.json"
_STAT_ARG = "--stat=200"  # wide enough that git does not shorten paths
_GIT_TIMEOUT = 30
# Live design dir first; the archived one after /tp-design-complete.
DESIGN_TREES = ("tp-designs", "completed-tp-designs")

# (ref, heading level, accepted heading titles), in the closed ref order.
DESIGN_SECTIONS = (
    ("design:problem", 2, ("problem",)),
    ("design:scope", 2, ("scope",)),
    ("design:dependencies", 2, ("dependencies",)),
    ("design:consumer-repo", 2,
     ("consumer-repo behaviour", "consumer-repo behavior")),
    ("design:forge", 2, ("forge behaviour", "forge behavior")),
    ("design:loci", 3, ("loci",)),
)
DECISION_LEVEL = 3
LEDGER_FILE = "rulings.ndjson"
LATE_LEDGER_FILE = "rulings-late.ndjson"

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
_FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")


def _item(ref: str, label: str, text: str) -> dict:
    return {"ref": ref, "label": label, "text": text}


def _read(path) -> str | None:
    """The file's text, or None when it is missing or unreadable."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError, TypeError):
        return None


def design_dir(root, slug) -> Path | None:
    """The design dir for *slug* (live first, then archived), or None."""
    if (not isinstance(slug, str) or slug in ("", ".", "..")
            or "/" in slug or "\\" in slug):
        return None
    for tree in DESIGN_TREES:
        try:
            candidate = Path(root) / DOCS_DIR / tree / slug
            if candidate.is_dir():
                return candidate
        except (OSError, ValueError, TypeError):
            return None
    return None


def _design_file(root, slug, name: str) -> str | None:
    d = design_dir(root, slug)
    return None if d is None else _read(d / name)


def _sections(text: str) -> list[tuple[int, str, str]]:
    """Every heading outside a code fence as (level, title, body).

    A body runs to the next heading of the same or a higher level, so a
    ``## `` section keeps its ``### `` subsections.
    """
    lines = text.splitlines()
    heads = []  # (line index, level, title)
    in_fence = False
    for idx, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        m = None if in_fence else _HEADING_RE.match(line)
        if m:
            heads.append((idx, len(m.group(1)), m.group(2)))
    out = []
    for pos, (idx, level, title) in enumerate(heads):
        end = len(lines)
        for nxt_idx, nxt_level, _ in heads[pos + 1:]:
            if nxt_level <= level:
                end = nxt_idx
                break
        out.append((level, title, "\n".join(lines[idx + 1:end]).strip()))
    return out


def design_items(root, slug) -> list[dict]:
    """The design.md evidence sections, in the closed ref order."""
    text = _design_file(root, slug, "design.md")
    if text is None:
        return []
    sections = _sections(text)
    items = []
    for ref, level, titles in DESIGN_SECTIONS:
        for s_level, title, body in sections:
            if s_level == level and title.lower() in titles:
                if body:
                    items.append(_item(ref, f"design.md § {title}", body))
                break
    return items


def decision_items(root, slug) -> list[dict]:
    """One decision:<n> item per ``### `` entry of decisions.md (1-based)."""
    text = _design_file(root, slug, "decisions.md")
    if text is None:
        return []
    entries = [(t, b) for lvl, t, b in _sections(text) if lvl == DECISION_LEVEL]
    return [
        _item(f"decision:{n}", title or f"decision {n}", body or title)
        for n, (title, body) in enumerate(entries, start=1)
        if body or title
    ]


def ledger_rows(text: str | None) -> list[dict]:
    """The rows of a rulings ledger that are objects with a string id."""
    rows = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        rid = row.get("id") if isinstance(row, dict) else None
        if isinstance(rid, str) and rid and not any(c.isspace() for c in rid):
            rows.append(row)
    return rows


def late_ledger_path(root, slug) -> Path | None:
    """``<state>/<slug>/rulings-late.ndjson``, or None for a bad slug or non-repo root."""
    try:
        explain_state._check_slug(slug)
        return explain_state.state_root(root) / slug / LATE_LEDGER_FILE
    except (ValueError, RuntimeError, OSError, TypeError):
        return None


def ruling_items(root, slug) -> list[dict]:
    """One ruling:<id> item per row of the design-dir ledger, then the late one."""
    late = late_ledger_path(root, slug)
    rows = ledger_rows(_design_file(root, slug, LEDGER_FILE))
    if late is not None:
        rows += ledger_rows(_read(late))
    items, seen = [], set()
    for row in rows:
        rid = row["id"]
        if rid in seen:
            continue
        seen.add(rid)
        text = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)
        items.append(_item(f"ruling:{rid}", f"ruling {rid}", text))
    return items


def audit_items(root, slug) -> list[dict]:
    """audit:verdict from the first implementation-audit.md verdict line."""
    text = _design_file(root, slug, "implementation-audit.md")
    for line in (text or "").splitlines():
        if "verdict" in line.lower():
            return [_item("audit:verdict", "implementation-audit.md verdict",
                          line.strip())]
    return []


def review_items(review_digest) -> list[dict]:
    """review:digest from the review digest file at *review_digest*."""
    if not review_digest:
        return []
    text = _read(review_digest)
    if text is None or not text.strip():
        return []
    return [_item("review:digest", "review digest", text.strip())]


def subject_items(subject) -> list[dict]:
    """One subject:<field> item per top-level key of the subject dict."""
    if not isinstance(subject, dict):
        return []
    items = []
    for key, value in subject.items():
        if not isinstance(key, str) or not key:
            continue
        if isinstance(value, str) and value:
            text = value
        else:
            text = json.dumps(value, sort_keys=True, ensure_ascii=False,
                              default=str)
        items.append(_item(f"subject:{key}", f"subject {key}", text))
    return items


def _git_out(root, *argv: str) -> str | None:
    """The stdout of a git call in *root*, or None when it fails."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *argv], capture_output=True,
            encoding="utf-8", errors="replace", env=_git_env(),
            timeout=_GIT_TIMEOUT, check=False,
        )
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _touched_dirs(names: str | None) -> list[str]:
    """The sorted parent dirs of the NUL-separated paths ("." is the root)."""
    paths = [p for p in (names or "").split("\0") if p]
    return sorted({PurePosixPath(p).parent.as_posix() for p in paths})


def _tree_text(root, rel_dir: str) -> str:
    """The sorted names in *rel_dir* at HEAD, capped at TREE_CAP."""
    tree = "HEAD" if rel_dir == "." else f"HEAD:{rel_dir}"
    out = _git_out(root, "ls-tree", "--name-only", "-z", tree)
    names = sorted(n for n in (out or "").split("\0") if n)
    text = "\n".join(names[:TREE_CAP])
    if len(names) > TREE_CAP:
        text += f"\n(+{len(names) - TREE_CAP} more)"
    return text


def _added_lines(diff: str | None) -> str:
    """The added ``+`` lines inside the hunks of a unified diff."""
    added, in_hunk = [], False
    for line in (diff or "").splitlines():
        if line.startswith("diff --git"):
            in_hunk = False
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            added.append(line)
    return "\n".join(added)


def git_items(root, base) -> list[dict]:
    """diffstat, tree:<dir> per touched dir (sorted), then config:diff.

    The range is ``<base>...HEAD`` (the changes since the merge base). With
    no base, a bad base, or *root* outside a git repo, it returns [].
    """
    if not isinstance(base, str) or not base.strip() or base.startswith("-"):
        return []
    span = f"{base}...HEAD"
    stat = _git_out(root, "diff", "--no-color", _STAT_ARG, span)
    if stat is None:
        return []
    items = []
    if stat.strip():
        items.append(_item("diffstat", f"git diff --stat {span}", stat.strip()))
    names = _git_out(root, "diff", "--name-only", "-z", span)
    for rel_dir in _touched_dirs(names):
        text = _tree_text(root, rel_dir)
        if text:
            items.append(_item(f"tree:{rel_dir}", f"names in {rel_dir}/", text))
    diff = _git_out(root, "diff", "--no-color", "--no-ext-diff",
                    "--no-textconv", "-U0", span, "--", CONFIG_PATH)
    added = _added_lines(diff)
    if added:
        items.append(_item("config:diff", f"{CONFIG_PATH} added lines", added))
    return items
