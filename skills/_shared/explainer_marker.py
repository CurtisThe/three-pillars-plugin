"""Marker for explainer-posted PR comments, so the review loop can skip them."""
from __future__ import annotations

import re

MARKER_PREFIX = "<!-- tp-explainer:"

_PARSE_RE = re.compile(
    r"^<!-- tp-explainer:(?P<kind>\S+) slug=(?P<slug>\S+) head=(?P<head>\S+) -->"
)


def marker(kind: str, slug: str, head: str) -> str:
    return f"{MARKER_PREFIX}{kind} slug={slug} head={head} -->"


def parse(body):
    m = _PARSE_RE.match(body or "")
    if not m:
        return None
    return {"kind": m.group("kind"), "slug": m.group("slug"), "head": m.group("head")}


def is_explainer(body) -> bool:
    return (body or "").startswith(MARKER_PREFIX)


def _body(comment):
    if isinstance(comment, dict):
        return comment.get("body")
    return getattr(comment, "body", None)


def drop_marked(comments) -> list:
    return [c for c in comments if not is_explainer(_body(c))]
