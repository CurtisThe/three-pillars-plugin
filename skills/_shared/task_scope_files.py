"""task_scope_files.py — plan **File**-field parsing and allowed-change classes.

design: local-implement-and-review

Split out of `task_scope.py` by responsibility (file-size cap); `task_scope`
re-exports `parse_files` and `classify_path`, so callers use `task_scope.<name>`.
Both `task_verify` and the Tier 3.5 re-run classify changed paths through
`classify_path`; only their design-dir policy differs.

Stdlib only.
"""
from __future__ import annotations

import re

_SPAN_RE = re.compile(r"`([^`]*)`")
_NONE_FORM_RE = re.compile(
    r"\(?\s*(?:none\b|n/?a\b|no\s+(?:new\s+)?(?:source|production|file|files|code)\b"
    r"|verification[- ]only\b)", re.I)
_EXT_RE = re.compile(r"\.[A-Za-z0-9]+\Z")
_UNSAFE_RE = re.compile(r"[()<>|;=\"'$!\\*?\[\]:]")
_BRACE_RE = re.compile(r"\{([^{}]*)\}")
_LINE_REF_RE = re.compile(r":\d+(?:-\d+)?\Z")
_PAREN_GROUP_RE = re.compile(r"\([^()]*\)")
_BARE_SEP_RE = re.compile(r"[;,]|\s\+\s|\s&\s")


def _pathish(span: str) -> bool:
    if not span or span.startswith(("#", "-", "::")) or "://" in span:
        return False
    return "/" in span or span.startswith(".") or bool(_EXT_RE.search(span))


def _expand_braces(span: str) -> list[str] | None:
    """`a/{b,c}.md` → [a/b.md, a/c.md]; None when a brace group is not a comma list."""
    m = _BRACE_RE.search(span)
    if m is None:
        return None if ("{" in span or "}" in span) else [span]
    parts = [p.strip() for p in m.group(1).split(",")]
    if len(parts) < 2 or not all(parts):
        return None
    out: list[str] = []
    for part in parts:
        sub = _expand_braces(span[:m.start()] + part + span[m.end():])
        if sub is None:
            return None
        out.extend(sub)
    return out


def norm_path(path: str) -> str:
    """Strip whitespace and any leading ``./``."""
    path = path.strip()
    while path.startswith("./"):
        path = path[2:]
    return path


def parse_files(field: str) -> tuple[list[str], list[str]]:
    """Parse a **File** field → ``(paths, unparsed)``.

    Backtick spans that look like paths are kept (spaces allowed inside backticks);
    ``{a,b}`` brace forms are expanded; ``none (...)`` yields nothing. A path-like span
    that cannot be resolved to concrete paths (glob, placeholder brace) and a field that
    is only prose go to ``unparsed`` — recorded, never counted as an escape.
    """
    field = (field or "").strip()
    if not field or _NONE_FORM_RE.match(field):
        return [], []
    paths: list[str] = []
    unparsed: list[str] = []
    spans = [m.group(1).strip() for m in _SPAN_RE.finditer(field)]
    for span in spans or _bare_paths(field):
        if not _pathish(span):
            continue
        expanded = _expand_braces(_LINE_REF_RE.sub("", norm_path(span)))
        if expanded is None or any(_UNSAFE_RE.search(p) for p in expanded):
            unparsed.append(span)
            continue
        paths.extend(p for p in expanded if p not in paths)
    if not paths and not unparsed:
        unparsed.append(field)
    return paths, unparsed


def _bare_paths(field: str) -> list[str]:
    """Corpus gap: an unbackticked list (``a.py (new); b.py``) whose every segment,
    parentheticals dropped, is one path-like token. Anything else is prose → []."""
    text, prev = field, None
    while text != prev:
        prev, text = text, _PAREN_GROUP_RE.sub(" ", text)
    segments = [s.strip() for s in _BARE_SEP_RE.split(text) if s.strip()]
    if segments and all(" " not in s and _pathish(s) for s in segments):
        return segments
    return []


def classify_path(path: str, listed, design_dir_rel: str) -> str:
    """``listed`` | ``design-dir`` | ``unlisted`` — the same answer for every caller.

    A listed entry ending in ``/`` covers its contents. ``design-dir`` wins over
    ``listed``: a File or Targets entry naming a design-dir path does not make it the
    worker's (the dispatcher owns every design-dir write). The exception is the worker
    work dirs ``<design-dir>/ledgers/`` and ``<design-dir>/staging/``: they are not
    ``design-dir``, so they are allowed only when the task's File/Targets list names
    them, else ``unlisted``. Callers own the policy: the Tier 3.5 re-run allows
    ``design-dir`` changes, a single task attempt does not.
    """
    p = norm_path(path)
    d = norm_path(design_dir_rel or "").strip("/")
    if d and (p == d or p.startswith(d + "/")) and not p.startswith(
            (d + "/ledgers/", d + "/staging/")):
        return "design-dir"
    for entry in listed:
        e = norm_path(entry)
        if p == e or (e.endswith("/") and p.startswith(e)):
            return "listed"
    return "unlisted"
