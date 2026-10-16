"""explainer/explain_request.py — the explain request bundle.

Public API:
    SCHEMA                  "explain-request/v1"
    KINDS                   the three explain kinds (explain_envelope.KINDS)
    DEFAULT_CHAR_BUDGET     12000
    build_request(root, *, kind, slug, subject=None, base=None,
                  review_digest=None, char_budget=12000) -> dict

The request is the drafter's only input:

    {schema: "explain-request/v1", kind, slug, subject,
     evidence: [{ref, label, text}], evidence_head}

Evidence comes from the explain_sources readers, in this fixed order:
subject:<field>, design:<section>, diffstat, tree:<dir>, config:diff,
audit:verdict, review:digest, ruling:<id>, decision:<n>. Every reader is
best-effort, so a missing source adds no item and never raises; the same
inputs give the same ref list. ``evidence_head`` is ``git rev-parse HEAD`` in
*root*, or "" outside a repo (or before the first commit).

The char budget counts the ``text`` chars of the evidence. Over budget, the
trim drops decision items first (oldest first, decision:1 before
decision:2), then tree items (in list order), and stops once the total fits.
Subject and design items are never dropped, even when the request is still
over budget; no other item is trimmed. The kept items keep their order.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_sources as es  # noqa: E402
from explain_envelope import KINDS  # noqa: E402,F401 — one kinds registry

SCHEMA = "explain-request/v1"
DEFAULT_CHAR_BUDGET = 12000
# The trim order: each prefix's items go, oldest first, before the next's.
_TRIM_PREFIXES = ("decision:", "tree:")


def _evidence_head(root) -> str:
    """``git rev-parse HEAD`` in *root*, or "" when git cannot say."""
    out = es._git_out(root, "rev-parse", "--verify", "-q", "HEAD")
    return (out or "").strip()


def _size(items: list[dict]) -> int:
    return sum(len(item["text"]) for item in items)


def _trim(items: list[dict], char_budget) -> list[dict]:
    """Drop decisions (oldest first), then tree items, until under budget."""
    try:
        budget = int(char_budget)
    except (TypeError, ValueError):
        return items
    total = _size(items)
    dropped: set[int] = set()
    for prefix in _TRIM_PREFIXES:
        for idx, item in enumerate(items):
            if total <= budget:
                break
            if item["ref"].startswith(prefix):
                dropped.add(idx)
                total -= len(item["text"])
    return [item for idx, item in enumerate(items) if idx not in dropped]


def build_request(root, *, kind, slug, subject=None, base=None,
                  review_digest=None,
                  char_budget=DEFAULT_CHAR_BUDGET) -> dict:
    """The explain request for *kind* about design *slug*.

    Raises ValueError for a kind outside KINDS; nothing else raises.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown explain kind {kind!r}; expected one of "
                         f"{', '.join(KINDS)}")
    evidence = [
        *es.subject_items(subject),
        *es.design_items(root, slug),
        *es.git_items(root, base),
        *es.audit_items(root, slug),
        *es.review_items(review_digest),
        *es.ruling_items(root, slug),
        *es.decision_items(root, slug),
    ]
    return {
        "schema": SCHEMA,
        "kind": kind,
        "slug": slug,
        "subject": subject,
        "evidence": _trim(evidence, char_budget),
        "evidence_head": _evidence_head(root),
    }
