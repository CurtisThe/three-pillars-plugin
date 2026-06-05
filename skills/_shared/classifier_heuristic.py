"""classifier_heuristic.py — deterministic keyword + file-scope triage for PR review comments.

Used by the parallel-design-worktrees fix loop. Callers:

  - skills/tp-pr-iterate/   (loop driver — prefilter before the LLM judge call)
  - skills/tp-pr-fix/       (single-round worker — re-classify on entry)

The module is pure-deterministic: no LLM, no network, no filesystem. Given a
`Comment` and the raw `diff_hunk` for the file the comment lives on, `classify`
returns `{"verdict": "structural" | "minor" | "unclear", "reason": str}`.

Rules (per detailed-design.md):

  1. Keyword match on `comment.body` (case-insensitive substring):
       structural: bug | race | broken | incorrect | vulnerability
       minor:      typo | docstring | comment | rename | nit
  2. File-scope override on the diff hunk paths:
       all `*.md`              → minor
       source AND test paths   → structural
     (A path is a "test" path if it contains `/test` or its basename starts
     with `test_`.)
  3. Otherwise → `unclear`.

The shared location lives next to other deterministic helpers
(collaboration.md, repo-config.md, branch_protection_check.py) under the same
`skills/_shared/` convention.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_KEYWORDS_STRUCTURAL: tuple[str, ...] = (
    "bug",
    "race",
    "broken",
    "incorrect",
    "vulnerability",
)

_KEYWORDS_MINOR: tuple[str, ...] = (
    "typo",
    "docstring",
    "comment",
    "rename",
    "nit",
)

# Captures paths from `+++ b/<path>` lines in unified diff hunks. Falls back to
# `diff --git a/<path> b/<path>` parsing when the hunk omits the file header
# (rare; happens when the caller passes a sliced hunk).
_PATH_RE_PLUS = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)
_PATH_RE_DIFF = re.compile(r"^diff --git a/\S+ b/(\S+)$", re.MULTILINE)


@dataclass
class Comment:
    """Minimal PR review comment shape used by the heuristic.

    Other modules in this design (structured_extract, fix_round) define their
    own local Comment dataclasses with overlapping fields. We will consolidate
    when fix_round.run_round wires the pipeline together.
    """

    id: int
    body: str
    path: str
    user: str


def _extract_paths(diff_hunk: str) -> list[str]:
    """Return the list of file paths touched by `diff_hunk`.

    Prefers `+++ b/<path>` lines; falls back to `diff --git` headers when the
    hunk header is absent. De-duplicates while preserving order.
    """
    paths: list[str] = []
    seen: set[str] = set()
    for match in _PATH_RE_PLUS.finditer(diff_hunk):
        path = match.group(1).strip()
        if path and path not in seen:
            paths.append(path)
            seen.add(path)
    if not paths:
        for match in _PATH_RE_DIFF.finditer(diff_hunk):
            path = match.group(1).strip()
            if path and path not in seen:
                paths.append(path)
                seen.add(path)
    return paths


def _is_test_path(path: str) -> bool:
    """Heuristic: `/test` substring OR basename starts with `test_`."""
    if "/test" in path:
        return True
    basename = path.rsplit("/", 1)[-1]
    return basename.startswith("test_")


def _is_md_path(path: str) -> bool:
    return path.lower().endswith(".md")


def _match_keyword(body_lower: str, keywords: tuple[str, ...]) -> str | None:
    for keyword in keywords:
        if keyword in body_lower:
            return keyword
    return None


def classify(comment: Comment, diff_hunk: str) -> dict:
    """Classify a PR review comment as structural, minor, or unclear.

    Returns a dict with two keys:
      - `verdict`: one of "structural", "minor", "unclear"
      - `reason`:  short human-readable explanation (which rule fired)

    Rule precedence: keyword match first (structural beats minor when both
    apply — safety bias toward action), then file-scope, then `unclear`.
    """
    body_lower = comment.body.lower()

    structural_kw = _match_keyword(body_lower, _KEYWORDS_STRUCTURAL)
    if structural_kw is not None:
        return {
            "verdict": "structural",
            "reason": f"keyword match: {structural_kw!r} in comment body",
        }

    minor_kw = _match_keyword(body_lower, _KEYWORDS_MINOR)
    if minor_kw is not None:
        return {
            "verdict": "minor",
            "reason": f"keyword match: {minor_kw!r} in comment body",
        }

    paths = _extract_paths(diff_hunk)
    if paths:
        if all(_is_md_path(p) for p in paths):
            return {
                "verdict": "minor",
                "reason": "file-scope: all diff paths are *.md",
            }
        has_source = any(not _is_test_path(p) and not _is_md_path(p) for p in paths)
        has_test = any(_is_test_path(p) for p in paths)
        if has_source and has_test:
            return {
                "verdict": "structural",
                "reason": "file-scope: hunk touches both source and test files",
            }

    return {
        "verdict": "unclear",
        "reason": "no keyword or file-scope rule fired — defer to judge",
    }
