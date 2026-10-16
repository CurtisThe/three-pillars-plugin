"""pending_flip — the pre-merge flipper for `Completion PR pending` tokens.

At design-complete the living docs carry a pending token (the canonical
`Completion PR pending`, or one of the frozen legacy forms). Before the merge,
`flip` rewrites exactly the canonical token that is attributed to one slug to
the done form (`Done (completion PR)`, or `Done — PR #N` once the PR number is
known), across the six living-doc files (the keys and values of
`living_doc_archive.ARCHIVES`). `scan` reports the tokens that remain for a slug.

Both share one token iterator, so the History / fenced-block / quoted-span
exclusions and the attribution rule (`attributed`) are identical. Attribution
needs a directory-resolving slug (`tp-designs/{t}/` or `completed-tp-designs/{t}/`)
in a documented placement; a token that cannot be attributed is never flipped
silently: on every line that mentions the slug as a whole token (its lead, a
backticked or bold mention, a `tp-designs/{slug}/` link path, plain prose) `flip`
skips it as `unattributable` and `scan` reports it with owner None. A living doc
that is not valid UTF-8 is never passed over: `flip` skips it as `decode-failure`
and `scan` reports it (form `decode-failure`, line 0) for every slug.

stdlib-only. reconcile_docs imports this module lazily (inside `main`), so the
module-level import of its helpers here is cycle-free.

design: design-complete-final-doc-state
"""

from __future__ import annotations

import re
from pathlib import Path

import living_doc_archive
from citation_liveness import STALE_STATUS_RE
from citation_rows import owner_slug_of_row
from reconcile_docs import (
    Edit,
    _bump_last_updated,
    _is_in_history,
    _is_in_quoted_span,
    _quoted_spans,
    _read_strict_utf8,
)

NUMBERLESS = "Done (completion PR)"

# The closed set of pre-token forms /tp-design-learn wrote before this design.
# Frozen: scan reports them, flip never rewrites them.
LEGACY_PENDING_RE = re.compile(
    r"\bawaiting PR\b|\bPR pending\b|\bPR \(pending\)", re.IGNORECASE
)

_TICKED_RE = re.compile(r"`([a-z0-9][a-z0-9-]*)`")
_ADJACENT_RE = re.compile(r"`([a-z0-9][a-z0-9-]*)`(?:\*\*)?\s*$")
_NUMBERED_LEAD_RE = re.compile(
    r"^\s*\d+\.\s+(?:\*\*)?`?([a-z0-9][a-z0-9-]*)`?(?:\*\*)?(?![a-z0-9-])"
)
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s")


def done_label(pr: int | None) -> str:
    """The done text: number-free at archival, `Done — PR #N` once the PR is known."""
    return NUMBERLESS if pr is None else f"Done — PR #{pr}"


def _resolves(root: Path, token: str) -> bool:
    docs = root / "three-pillars-docs"
    return (docs / "tp-designs" / token).is_dir() or (
        docs / "completed-tp-designs" / token
    ).is_dir()


def _ticked(text: str, root: Path) -> list[str]:
    """Distinct directory-resolving backticked slugs in `text`, in order."""
    found: list[str] = []
    for m in _TICKED_RE.finditer(text):
        if m.group(1) not in found and _resolves(root, m.group(1)):
            found.append(m.group(1))
    return found


def _paren_around(line: str, span: tuple[int, int]) -> tuple[int, int] | None:
    """Innermost `( ... )` enclosing the whole token span, or None.

    The token's own characters (the parens of `PR (pending)`) and parens inside
    backtick spans never count.
    """
    s, e = span
    chars = list(line)
    for i in range(s, e):
        chars[i] = " "
    for qs, qe in _quoted_spans(line, is_table_row=False):
        if line[qs] == "`":
            for i in range(qs, qe):
                if chars[i] in "()":
                    chars[i] = " "
    stack: list[int] = []
    best: tuple[int, int] | None = None
    for i, ch in enumerate(chars):
        if ch == "(":
            stack.append(i)
        elif ch == ")" and stack:
            o = stack.pop()
            if o < s and i >= e and (best is None or o > best[0]):
                best = (o, i)
    return best


def _paren_owner(line: str, root: Path, paren: tuple[int, int]) -> str | None:
    """The token parenthetical's one backticked slug, else the slug adjacent
    before its `(`, else None (two or more slugs inside, or none at all)."""
    named = _ticked(line[paren[0] + 1:paren[1]], root)
    if named:
        return named[0] if len(named) == 1 else None
    adj = _ADJACENT_RE.search(line[:paren[0]])
    return adj.group(1) if adj and _resolves(root, adj.group(1)) else None


def _paren_claims(line: str, root: Path, paren: tuple[int, int]) -> set[str]:
    """Every resolving slug a documented placement ties to the token's
    parenthetical: those backticked inside it, plus the one adjacent before it."""
    claims = set(_ticked(line[paren[0] + 1:paren[1]], root))
    adj = _ADJACENT_RE.search(line[:paren[0]])
    if adj and _resolves(root, adj.group(1)):
        claims.add(adj.group(1))
    return claims


def _line_lead(line: str, root: Path) -> str | None:
    """The row/bullet owner, else the numbered-item lead, else None."""
    owner = owner_slug_of_row(line, root)
    if owner:
        return owner
    m = _NUMBERED_LEAD_RE.match(line)
    return m.group(1) if m and _resolves(root, m.group(1)) else None


def _names(body: str, slug: str) -> bool:
    """Whether `body` mentions `slug` as a whole token: the line lead, a
    backticked or bold mention, a `tp-designs/{slug}/` link path or plain prose.
    An unattributable token is surfaced for every slug the line mentions, not
    only for the documented placements, so `check` never passes it silently."""
    return re.search(rf"(?<![A-Za-z0-9_-]){re.escape(slug)}(?![A-Za-z0-9_-])", body) is not None


def attributed(line: str, root, token_span: tuple[int, int]) -> str | None:
    """The slug that owns the pending token at `token_span`, or None.

    Ordered rules, the first that applies decides: (1) a line lead (the
    row/bullet owner, else the numbered-item lead) owns the token, unless the
    token's innermost parenthetical names, or directly follows, a different
    slug: two documented placements then disagree, so the token is
    unattributable (reported for every slug the line names, never silently
    handed to one); (2) no lead: the innermost enclosing parenthetical's one
    backticked slug, else the slug adjacent before its `(`, else unattributable
    (two or more slugs, or none); (3) no parenthetical: the line's one
    backticked slug, else unattributable.
    """
    root = Path(root)
    paren = _paren_around(line, token_span)
    lead = _line_lead(line, root)
    if lead:
        if paren is None or not (_paren_claims(line, root, paren) - {lead}):
            return lead
        return None
    if paren is not None:
        return _paren_owner(line, root, paren)
    named = _ticked(line, root)
    return named[0] if len(named) == 1 else None


def _live_lines(text: str):
    """Yield (index, line) outside fenced blocks and `## ...History...` sections."""
    in_history = in_fence = False
    for idx, line in enumerate(text.splitlines(keepends=True)):
        stripped = line.rstrip("\r\n")
        if stripped.startswith("```"):
            in_fence = not in_fence
        elif in_fence:
            continue
        elif stripped.startswith("## "):
            in_history = _is_in_history(stripped[3:].strip())
        elif stripped.startswith("# "):
            in_history = False
        elif not in_history:
            yield idx, line


def _tokens(body: str, *, legacy: bool, numberless: bool) -> list[tuple[int, int, str]]:
    """Unquoted pending tokens on one line as (start, end, form), canonical first.

    The legacy scan ignores any span overlapping a canonical match, so
    `Completion PR pending` (which contains `PR pending`) is reported once.
    """
    quoted = _quoted_spans(body, is_table_row=not _LIST_ITEM_RE.match(body))
    canon = [(m.start(), m.end(), "canonical") for m in STALE_STATUS_RE.finditer(body)]
    found = list(canon)
    if numberless:
        found += [(m.start(), m.end(), "numberless")
                  for m in re.finditer(re.escape(NUMBERLESS), body)]
    if legacy:
        found += [(m.start(), m.end(), "legacy")
                  for m in LEGACY_PENDING_RE.finditer(body)
                  if not any(m.start() < e and m.end() > s for s, e, _ in canon)]
    return sorted(t for t in found if not _is_in_quoted_span(t[0], t[1], quoted))


def _line_hits(root: Path, text: str, *, legacy: bool, numberless: bool):
    """Yield (index, line, body, [(start, end, form, owner), ...]) per token line."""
    for idx, line in _live_lines(text):
        body = line.rstrip("\r\n")
        toks = _tokens(body, legacy=legacy, numberless=numberless)
        if toks:
            yield idx, line, body, [
                (s, e, form, attributed(body, root, (s, e))) for s, e, form in toks
            ]


def _living_files() -> list[str]:
    return [rel for pair in living_doc_archive.ARCHIVES.items() for rel in pair]


def flip(repo_root, slug: str, pr: int | None, *, apply: bool) -> tuple[list[Edit], list[dict]]:
    """Flip the canonical pending tokens attributed to `slug` to the done form.

    With `pr` set, an existing number-free `Done (completion PR)` is upgraded to
    `Done — PR #N` too. Returns (edits, skipped); skipped entries are
    `{file, line_no, reason}` with reason `unattributable`,
    `ambiguous-multi-match` (more than one token on the line) or
    `decode-failure`. A missing file is a no-op. Legacy forms are never
    rewritten. A second run on the output finds nothing to flip.
    """
    root = Path(repo_root)
    label = done_label(pr)
    edits: list[Edit] = []
    skipped: list[dict] = []
    for rel in _living_files():
        text, bad = _read_strict_utf8(root / rel)
        if bad:
            skipped.append({"file": rel, "line_no": 0, "reason": "decode-failure"})
            continue
        if text is None:
            continue
        lines = text.splitlines(keepends=True)
        file_edits: list[Edit] = []
        for idx, line, body, toks in _line_hits(
            root, text, legacy=False, numberless=pr is not None
        ):
            owners = [t[3] for t in toks]
            mine = slug in owners
            if not mine and not (None in owners and _names(body, slug)):
                continue
            reason = (
                "ambiguous-multi-match" if len(toks) > 1
                else None if mine else "unattributable"
            )
            if reason:
                skipped.append({"file": rel, "line_no": idx + 1, "reason": reason})
                continue
            s, e, _form, _owner = toks[0]
            new = line[:s] + label + line[e:]
            if new == line:
                continue
            lines[idx] = new
            file_edits.append(Edit(path=rel, line=idx + 1, before=body,
                                   after=new.rstrip("\r\n"), kind="status-flip", slug=slug))
        if file_edits and apply:
            (root / rel).write_text(_bump_last_updated("".join(lines)), encoding="utf-8")
        edits.extend(file_edits)
    return edits, skipped


def scan(repo_root, slug: str) -> list[dict]:
    """Report the pending tokens that remain for `slug` as `{file, line, form, owner}`.

    `form` is `canonical` (STALE_STATUS_RE) or `legacy` (the frozen pre-token
    forms); `owner` is `slug` (attributed) or None (unattributable on a line that
    mentions `slug`). A token attributed to another slug is not reported. A
    living doc that cannot be decoded is reported as `{file, line: 0, form:
    "decode-failure", owner: None}`: the scan could not read it, so it never
    passes as clean.
    """
    root = Path(repo_root)
    found: list[dict] = []
    for rel in _living_files():
        text, bad = _read_strict_utf8(root / rel)
        if bad:
            found.append({"file": rel, "line": 0, "form": "decode-failure", "owner": None})
            continue
        if text is None:
            continue
        for idx, _line, body, toks in _line_hits(root, text, legacy=True, numberless=False):
            for _s, _e, form, owner in toks:
                if owner == slug or (owner is None and _names(body, slug)):
                    found.append({"file": rel, "line": idx + 1, "form": form, "owner": owner})
    return found
