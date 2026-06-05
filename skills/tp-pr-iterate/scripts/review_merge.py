"""review_merge — normalize + dedupe dual-source PR review findings.

Enhancement 1 (pr-fix-targeting-and-auto-review): each `/tp-pr-iterate` round
pairs the GitHub (Copilot) review with a local `/code-review` sub-agent. This
helper maps BOTH sources into one normalized-finding.v1 shape and collapses
near-duplicates so the union can be handed to a single `tp-pr-fix` round.

C1 architectural constraint: this helper is pure stdlib — it computes and
parses only. It has NO `import anthropic` and never shells out to `claude`.
The `/code-review` dispatch + any model work live in SKILL.md prose via
`Agent()`. `parse_codereview_response` mirrors `classifier_judge.parse_response`:
it extracts the fenced JSON the dispatched sub-agent is told to emit, it does
not invoke the model.
"""

from __future__ import annotations

import difflib
import json
import re

# Dedup tunables (detailed-design §Decisions). Conservative on purpose: a
# false-merge silently drops a real finding, an over-keep just costs one extra
# fix attempt.
_PROXIMITY_SLACK = 3
_SIMILARITY_THRESHOLD = 0.6

_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_ANY_FENCED_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


# ---------- normalization ----------


def normalize_copilot(comment: dict) -> dict:
    """A GitHub review-comment dict → normalized-finding.v1 (source='copilot').

    Carries `thread_id` + `comment_id` so the reply-and-resolve step can act
    on the thread later.
    """
    start, end = _coerce_range(comment.get("line_range"), comment.get("line"))
    return {
        "source": "copilot",
        "finding_id": comment.get("comment_id", comment.get("id", "")),
        "thread_id": comment.get("thread_id"),
        "comment_id": comment.get("comment_id", comment.get("id")),
        "reviewer": comment.get("reviewer", "copilot-pull-request-reviewer[bot]"),
        "file": comment.get("file", comment.get("path", "")),
        "line_range": [start, end],
        "summary": comment.get("summary", comment.get("body", ""))[:500],
        "verdict": comment.get("verdict", "unclear"),
        "merged_from": None,
    }


def normalize_codereview(finding: dict) -> dict:
    """A `/code-review` finding dict → normalized-finding.v1 (source='code-review').

    `/code-review` is local and has no GitHub thread, so `thread_id` and
    `comment_id` are None.
    """
    start, end = _coerce_range(finding.get("line_range"), finding.get("line"))
    out = {
        "source": "code-review",
        "finding_id": finding.get("finding_id", finding.get("id", "")),
        "thread_id": None,
        "comment_id": None,
        "reviewer": "code-review",
        "file": finding.get("file", finding.get("path", "")),
        "line_range": [start, end],
        "summary": finding.get("summary", finding.get("body", ""))[:500],
        "verdict": finding.get("verdict", "structural"),
        "merged_from": None,
    }
    conf = _coerce_confidence(finding.get("confidence"))
    if conf is not None:
        out["confidence"] = conf
    return out


_CONFIDENCE_ENUM = {"High", "Medium", "Low"}


def _coerce_confidence(value) -> str | None:
    """Title-case a free-text confidence into the schema enum; drop if unknown.

    A `/code-review` sub-agent may emit 'high'/'HIGH'/etc.; the
    normalized-finding schema only accepts High/Medium/Low. Coerce rather than
    let a stray casing fail downstream validation.
    """
    if not isinstance(value, str):
        return None
    titled = value.strip().title()
    return titled if titled in _CONFIDENCE_ENUM else None


def _coerce_range(line_range, line) -> tuple[int, int]:
    if isinstance(line_range, (list, tuple)) and len(line_range) >= 2:
        return int(line_range[0]), int(line_range[1])
    if isinstance(line, int):
        return line, line
    return 0, 0


# ---------- /code-review output parsing ----------


def parse_codereview_response(text: str) -> list[dict]:
    """Extract the fenced JSON findings array a `/code-review` sub-agent emits.

    Mirrors `classifier_judge.parse_response`: prefer a ```json block, fall
    back to any fenced block whose content is a JSON array. Malformed or empty
    input → [] (fail-soft; a round with an unparseable review is treated as
    'no local findings', not a crash).
    """
    block = _extract_json_block(text)
    if not block:
        return []
    try:
        data = json.loads(block)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict)]


def _extract_json_block(text: str) -> str:
    m = _JSON_BLOCK_RE.search(text or "")
    if m:
        return m.group(1).strip()
    for m in _ANY_FENCED_RE.finditer(text or ""):
        body = m.group(1).strip()
        if body.startswith("[") or body.startswith("{"):
            return body
    return ""


# ---------- dedupe ----------


def _line_proximity(a: list[int], b: list[int], slack: int = _PROXIMITY_SLACK) -> bool:
    """True when two same-file line ranges overlap after padding each by `slack`."""
    a0, a1 = min(a), max(a)
    b0, b1 = min(b), max(b)
    return (a0 - slack) <= b1 and (b0 - slack) <= a1


def _summary_similar(a: str, b: str, threshold: float = _SIMILARITY_THRESHOLD) -> bool:
    """difflib ratio on lowercased / whitespace-collapsed summaries ≥ threshold."""
    na = " ".join((a or "").lower().split())
    nb = " ".join((b or "").lower().split())
    if not na or not nb:
        return False
    return difflib.SequenceMatcher(None, na, nb).ratio() >= threshold


def _is_duplicate(x: dict, y: dict) -> bool:
    return (
        x.get("file") == y.get("file")
        and x.get("file") != ""
        and _line_proximity(x.get("line_range", [0, 0]), y.get("line_range", [0, 0]))
        and _summary_similar(x.get("summary", ""), y.get("summary", ""))
    )


def dedupe(findings: list[dict]) -> list[dict]:
    """Collapse near-duplicate findings across sources, order-stable.

    Collapse key: same file AND line-proximity AND summary-similarity. On a
    collision the Copilot finding is KEPT (it carries the `thread_id` the
    reply-and-resolve step needs); the dropped twin's `finding_id` is recorded
    in the kept finding's `merged_from`. If neither is Copilot, the
    first-seen finding wins.
    """
    kept: list[dict] = []
    for f in findings:
        match_idx = next((i for i, k in enumerate(kept) if _is_duplicate(k, f)), None)
        if match_idx is None:
            kept.append(dict(f))
            continue
        existing = kept[match_idx]
        # Decide which survives: prefer the copilot finding.
        if existing.get("source") == "copilot" or f.get("source") != "copilot":
            survivor, dropped = existing, f
        else:
            survivor, dropped = dict(f), existing
            kept[match_idx] = survivor
        # Carry the dropped twin's OWN provenance too, not just its id — in a
        # 3+-way collision the dropped finding may already have absorbed others.
        merged = list(survivor.get("merged_from") or [])
        for mid in list(dropped.get("merged_from") or []) + [dropped.get("finding_id")]:
            if mid not in (None, "") and mid not in merged:
                merged.append(mid)
        survivor["merged_from"] = merged or None
    return kept
