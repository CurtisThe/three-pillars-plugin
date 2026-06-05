"""Structured extraction of PR review comments into the classified-comment envelope.

`extract(comment, diff_hunk, verdict)` returns a dict shaped like the
`classified-comment.v1.json` envelope: identifying fields pass through, the
free-text body is collapsed into a sanitized `issue_phrase`, and a coarse
`issue_class` is routed from a keyword scan on the original body.

`issue_phrase` is the load-bearing field — downstream it ends up in commit
messages and other shell-adjacent contexts, so the contract is:

  - no triple- or single-backtick fenced spans (they are replaced with whitespace)
  - no shell metacharacters: ``; & | $ \\ ` ( )``
  - no URLs (`http://…` / `https://…`)
  - whitespace collapsed to single spaces, stripped
  - length ≤ 80 chars
  - idempotent: `sanitize(sanitize(x)) == sanitize(x)`

The `Comment` dataclass is defined locally so this module has no cross-helper
import surface — sibling tasks under Phase 4 each define their own minimal
view of a review comment until the shared model lands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


_FENCE_RE = re.compile(r"```.*?```|`[^`]*`", re.DOTALL)
_URL_RE = re.compile(r"https?://\S+")
_SHELL_META_RE = re.compile(r"[;&|$\\`()]")
_WS_RE = re.compile(r"\s+")

_MAX_ISSUE_PHRASE_LEN = 80
_DIFF_HUNK_REF_LEN = 200

_ISSUE_CLASS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("missing-validation", re.compile(r"validate|missing|sanitize", re.IGNORECASE)),
    ("incorrect-behavior", re.compile(r"bug|broken|incorrect|wrong", re.IGNORECASE)),
    ("performance", re.compile(r"slow|perf|allocation|n\+1", re.IGNORECASE)),
    ("security", re.compile(r"vulnerability|csrf|xss|injection|secret", re.IGNORECASE)),
    ("test-coverage", re.compile(r"coverage|untested|missing test", re.IGNORECASE)),
    ("ergonomics", re.compile(r"confusing|api|signature|naming", re.IGNORECASE)),
)


@dataclass
class Comment:
    """Minimal local view of a PR review comment.

    Sibling Phase-4 helpers each define their own `Comment` until a shared
    model lands — see module docstring.
    """

    id: int
    body: str
    path: str
    user: str
    line: Optional[int] = None


def _sanitize(text: str) -> str:
    """Strip fenced spans / URLs / shell metas, collapse whitespace, truncate to 80.

    Order matters: fences first (they may themselves contain metas/URLs we
    don't want to preserve), then URLs (regex consumes contiguous non-space
    runs), then individual shell metacharacters, finally whitespace collapse +
    truncate. The pipeline is idempotent because every step is monotone — a
    second pass finds nothing left to remove.
    """
    out = _FENCE_RE.sub(" ", text)
    out = _URL_RE.sub("", out)
    out = _SHELL_META_RE.sub("", out)
    out = _WS_RE.sub(" ", out).strip()
    return out[:_MAX_ISSUE_PHRASE_LEN]


def _classify(body: str) -> str:
    """Route to one of the seven issue_class buckets via keyword match."""
    for label, pattern in _ISSUE_CLASS_PATTERNS:
        if pattern.search(body):
            return label
    return "other"


def _line_range_from_diff(diff_hunk: str) -> Optional[list[int]]:
    """Extract `[start, end]` from a unified-diff hunk header, or None.

    Looks for the `+a,b` part of `@@ -x,y +a,b @@`. Returns `[a, a+b-1]`.
    Best-effort: any parse failure yields None — downstream treats absence as
    "no line range known" rather than blowing up.
    """
    match = re.search(r"@@\s*-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s*@@", diff_hunk)
    if not match:
        return None
    start = int(match.group(1))
    span = int(match.group(2)) if match.group(2) else 1
    if span <= 0:
        return [start, start]
    return [start, start + span - 1]


def extract(comment: Comment, diff_hunk: str, verdict: str) -> dict:
    """Return the classified-comment envelope for `comment`.

    `verdict` passes through (the Sonnet judge already produced it upstream);
    `diff_hunk` provides line-range context and a 200-char traceability ref.
    `issue_phrase` is sanitized per the module contract; `issue_class` is a
    coarse keyword routing on the original body.
    """
    return {
        "comment_id": comment.id,
        "reviewer": comment.user,
        "verdict": verdict,
        "file": comment.path,
        "line_range": _line_range_from_diff(diff_hunk),
        "issue_class": _classify(comment.body),
        "issue_phrase": _sanitize(comment.body),
        "diff_hunk_ref": diff_hunk[:_DIFF_HUNK_REF_LEN],
    }
