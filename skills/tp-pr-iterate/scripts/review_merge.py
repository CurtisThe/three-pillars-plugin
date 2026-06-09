"""review_merge — normalize + dedupe dual-source PR review findings.

Enhancement 1 (pr-fix-targeting-and-auto-review): each `/tp-pr-iterate` round
pairs the GitHub (Copilot) review with a local `/code-review` sub-agent. This
helper maps BOTH sources into one normalized-finding.v1 shape and collapses
near-duplicates so the union can be handed to a single `tp-pr-fix` round.

C1 architectural constraint: the normalize/parse/dedupe core is pure stdlib —
it computes and parses only. The module has NO `import anthropic` and never
shells out to `claude`; the `/code-review` dispatch + any model work live in
SKILL.md prose via `Agent()`. `parse_codereview_response` mirrors
`classifier_judge.parse_response`: it extracts the fenced JSON the dispatched
sub-agent is told to emit, it does not invoke the model. The one I/O helper is
`post_codereview_comment` (the mandatory per-invocation review-summary comment);
it shells `gh` exactly as the sibling C1 helper `thread_resolver` does for
reply/resolve, and is injectable (`post_fn`) so the pure core stays test-isolated.
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
from urllib.parse import urlparse

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
        "summary": str(comment.get("summary") or comment.get("body") or "")[:500],
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
        # str()-coerce before slicing: untrusted LLM output may carry a non-str
        # summary (e.g. an int), which would crash `[:500]`.
        "summary": str(finding.get("summary") or finding.get("body") or "")[:500],
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
        a, b = line_range[0], line_range[1]
        # Guard int(): untrusted LLM output may carry non-numeric range elements
        # (e.g. ["a","b"]) — fall through to the line / (0,0) fallback, never raise.
        # Reject bool explicitly (bool is an int subclass, so [True, False] would
        # otherwise coerce to a nonsense (1, 0) range).
        if not isinstance(a, bool) and not isinstance(b, bool):
            try:
                return int(a), int(b)
            except (TypeError, ValueError):
                pass
    if isinstance(line, int) and not isinstance(line, bool):
        return line, line
    return 0, 0


# ---------- /code-review output parsing ----------


def _array_shape(a: list) -> str:
    """Classify a parsed JSON array as 'empty', 'findings', or 'ambiguous'.

    - 'empty'     — `a` is an empty list `[]`.
    - 'findings'  — at least one depth-1 element is a dict (real findings present).
    - 'ambiguous' — non-empty list with NO depth-1 dicts (all-non-dict elements OR
                    nested sub-lists — e.g. `[[{...}]]` has dicts at depth 2 only).

    Used by `parse_codereview_result` to distinguish parse holes (nested/non-dict
    arrays mis-read as clean) from genuine empty-clean arrays.
    """
    if not a:
        return "empty"
    if any(isinstance(d, dict) for d in a):
        return "findings"
    return "ambiguous"


def parse_codereview_result(text: str) -> "tuple[list[dict], bool]":
    """Parse a `/code-review` reply, distinguishing CLEAN from UNPARSEABLE.

    Returns `(findings, parsed_ok)`:
    - `([...], True)`  — a valid JSON array was found; if any array is 'findings',
      returns the union of all depth-1 dicts across findings arrays. If EVERY array
      is 'empty', returns `([], True)` — a literal `[]` is the only genuine clean
      signal (design Scope L11).
    - `([], False)`    — NO parseable JSON array (no fenced block, invalid JSON,
      non-list payload, or every array is 'ambiguous' with no findings array).

    Via `_array_shape` the three parse holes are closed:
    - Hole 1: nested `[[{...}]]` (dicts at depth 2, none at depth 1) → 'ambiguous'
      → `([], False)` (blocks).
    - Hole 2: all-non-dict `[1,2,3]` alone → 'ambiguous' → `([], False)` (blocks).
    - The coexistence case: a `[1,2,3]` fence alongside a real findings fence →
      findings win, `ok=True` (ambiguous yields to a real findings array, union preserved).

    The distinction is load-bearing: the loop's two-stable terminal treats an empty
    findings list as "clean → may converge". A fail-SOFT parse that mapped an
    unparseable reply to `[]` would let a review that silently failed to parse read
    as clean and contribute to a false convergence. Callers that gate convergence
    MUST use this (or `parse_codereview_findings_or_block`), never the bare list form.
    """
    arrays = _all_json_arrays(text)
    if not arrays:
        # No fenced block parsed as a JSON array → unparseable, NOT clean.
        return [], False
    # Classify each array via _array_shape.
    shapes = [_array_shape(a) for a in arrays]
    # If any array is 'findings' → union ALL depth-1 dicts across findings arrays.
    # This is the content-based UNION (NOT position, NOT tag): ambiguous arrays
    # (stray code-example lists, nested arrays) contribute nothing; the union
    # surfaces every real finding. An early `[]` draft can't shadow later findings,
    # a trailing `[]` ("on reflection, clean") can't suppress earlier ones.
    if "findings" in shapes:
        return (
            [d for a, s in zip(arrays, shapes) if s == "findings"
             for d in a if isinstance(d, dict)],
            True,
        )
    # No 'findings' array. If every array is 'empty' → genuinely clean ([], True).
    if all(s == "empty" for s in shapes):
        return [], True
    # At least one 'ambiguous' and no 'findings' → unparseable, blocks.
    return [], False


def parse_codereview_response(text: str) -> list[dict]:
    """Back-compat list-only form of `parse_codereview_result` (fail-soft).

    Returns just the findings list; an unparseable reply collapses to `[]`. **Do
    NOT use this where the result gates convergence** — it cannot distinguish a
    clean review from an unparseable one (see `parse_codereview_result`). Retained
    for callers that only want findings and tolerate the fail-soft collapse.
    """
    findings, _ok = parse_codereview_result(text)
    return findings


def _unparseable_finding(source: str = "code-review") -> dict:
    """A structural sentinel finding standing in for an UNPARSEABLE review reply.

    Injected fail-CLOSED when a `/code-review` angle's output could not be parsed,
    so the round carries a non-empty `structural` finding: the two-stable terminal
    cannot converge on it, and the mandatory summary comment shows the parse failure
    instead of a misleading "no findings". A review that didn't parse is NOT clean.
    """
    return {
        # Distinct file per source so two angles that BOTH fail to parse stay distinct
        # through dedupe (same file+line+summary would collapse to one, hiding how many
        # angles failed). The merge passes a per-angle source for exactly this.
        "file": f"<review-output:{source}>",
        "line_range": [0, 0],
        "summary": (
            f"{source} output could not be parsed as a findings array — treated as "
            "NOT clean (fail-closed; the loop must not converge on an unparseable review)"
        ),
        "verdict": "structural",
        "source": source,
    }


def parse_codereview_findings_or_block(text: str, *, source: str = "code-review") -> list[dict]:
    """Fail-closed single-source parse for the convergence path.

    A clean review → its (possibly empty) findings. An UNPARSEABLE review → a
    one-element list carrying `_unparseable_finding` (a structural sentinel that
    blocks convergence), NEVER an empty list. This is the form the loop's step 2.5
    uses so an unparseable review can never masquerade as clean.
    """
    findings, ok = parse_codereview_result(text)
    if not ok:
        return [_unparseable_finding(source)]
    return findings


def merge_codereview_angles(responses: "list[str]") -> list[dict]:
    """Parse + normalize + dedupe findings across MULTIPLE `/code-review` angle replies.

    The loop's step 2.5 fans out several finder angles (correctness-leak / edge-cases /
    test-quality) at the loop-driver (top) level — a single `/code-review` subagent
    cannot fan out (L23), so the driver dispatches the angles directly. This merges
    their replies into one deduped finding set for the round.

    FAIL-CLOSED for zero/empty fan-out (Hole 3): a falsy `responses` (`[]` / `None`)
    injects ONE `_unparseable_finding(source="no-angles")` sentinel so an empty fan-out
    blocks the two-stable terminal rather than silently reading clean (the per-angle loop
    over an empty list would produce `[]` — indistinguishable from a genuinely clean
    round). The sentinel shape mirrors the per-angle source, so each failure type surfaces
    distinctly.

    FAIL-CLOSED per angle: an unparseable angle contributes its `_unparseable_finding`
    sentinel (structural) rather than silently dropping to nothing, so a parse failure
    in ANY angle blocks the two-stable terminal. Each angle's findings are normalized
    via `normalize_codereview` and the union is `dedupe`d (so the same defect found by
    two angles collapses to one).
    """
    # Hole 3: falsy responses ([] or None) — inject the no-angles sentinel so an
    # empty fan-out blocks the two-stable terminal rather than reading as clean.
    # NOT normalized through normalize_codereview (which would overwrite `source`);
    # the sentinel's shape is already a valid finding dict ready for the loop.
    if not responses:
        return [_unparseable_finding(source="no-angles")]
    collected: list[dict] = []
    for i, resp in enumerate(responses):
        # Per-angle source keeps each angle's unparseable sentinel distinct (see
        # _unparseable_finding) so N failed angles surface as N, not 1.
        for f in parse_codereview_findings_or_block(resp, source=f"angle-{i + 1}"):
            collected.append(normalize_codereview(f))
    return dedupe(collected)


def _all_json_arrays(text: str) -> "list[list]":
    """Every fenced block in `text` whose body PARSES as a JSON list, in document order.

    - Coerces a non-str input (None / an object — a misbehaving Agent reply) to "" so a
      parse fails CLOSED (no arrays → unparseable sentinel) rather than raising and
      crashing the loop on one bad angle.
    - ONE pass over every fenced block (``` and ```json alike — `_ANY_FENCED_RE` matches
      both). There is deliberately NO tag short-circuit: a `json`-tagged empty `[]` must
      not suppress real findings emitted in an untagged fence (the cross-tag shadow).
    - MALFORMED / non-array fences are skipped (never returned), so a malformed or
      non-list block can neither shadow a valid one nor be mistaken for the answer. The
      caller (`parse_codereview_result`) selects the last array that carries a finding.
    """
    text = text if isinstance(text, str) else ""
    arrays: list[list] = []
    for m in _ANY_FENCED_RE.finditer(text):
        body = m.group(1).strip()
        if not body.startswith("["):
            continue
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, list):
            arrays.append(data)
    return arrays


# ---------- /code-review summary comment (mandatory per invocation) ----------


def _finding_loc(finding: dict) -> str:
    """`file:line` (or `file:start-end`) backtick-wrapped location for a finding."""
    file = finding.get("file") or finding.get("path") or "?"
    lr = finding.get("line_range")
    if isinstance(lr, (list, tuple)) and len(lr) >= 2:
        a, b = lr[0], lr[1]
        return f"`{file}:{a}`" if a == b else f"`{file}:{a}-{b}`"
    line = finding.get("line")
    return f"`{file}:{line}`" if isinstance(line, int) else f"`{file}`"


def format_codereview_comment(findings: list[dict], *, head_sha: str | None = None) -> str:
    """Render a Copilot-style review-summary comment body from `/code-review` findings.

    Groups by `verdict` severity (structural / minor / other) and ALWAYS produces
    a body — an empty `findings` yields an explicit "no findings" comment so a clean
    review is still visible (never silent). `findings` is the raw `/code-review`
    output shape: {file, line_range, summary, verdict, ...}.
    """
    structural = [f for f in findings if (f.get("verdict") or "").lower() == "structural"]
    minor = [f for f in findings if (f.get("verdict") or "").lower() == "minor"]
    other = [
        f for f in findings
        if (f.get("verdict") or "").lower() not in ("structural", "minor")
    ]
    head_note = f" · head `{head_sha[:10]}`" if head_sha else ""

    lines = ["## 🤖 `/code-review` — automated review", ""]
    if not findings:
        lines.append("✅ **No findings** — the diff is clean at this review.")
    else:
        parts = []
        if structural:
            parts.append(f"**{len(structural)} structural**")
        if minor:
            parts.append(f"**{len(minor)} minor**")
        if other:
            parts.append(f"{len(other)} unclassified")
        lines.append(f"Found {len(findings)} finding(s): " + ", ".join(parts) + ".")

        for title, items in (
            ("Structural — must be addressed before merge", structural),
            ("Minor — advisory", minor),
            ("Unclassified", other),
        ):
            if not items:
                continue
            lines.append("")
            lines.append(f"### {title} ({len(items)})")
            for f in items:
                summ = " ".join((f.get("summary") or "").split()) or "(no summary)"
                lines.append(f"- {_finding_loc(f)} — {summ}")

    lines.append("")
    lines.append(
        f"<sub>Posted by three-pillars `/tp-pr-iterate`{head_note}. Structural findings "
        "keep the loop iterating; a clean / minor-only review is a precondition for the "
        "two-stable terminal — this comment makes every `/code-review` invocation "
        "auditable in the PR (parallel to a Copilot review).</sub>"
    )
    return "\n".join(lines)


def _pr_url_parts(pr_url: str) -> tuple[str, str, str]:
    """https://<host>/{owner}/{repo}/pull/{n} -> (owner, repo, number)."""
    parts = [p for p in urlparse(pr_url).path.split("/") if p]
    if len(parts) < 4 or parts[2] != "pull" or not parts[3].isdigit():
        raise ValueError(
            f"pr_url must look like .../{{owner}}/{{repo}}/pull/{{n}}, got: {pr_url!r}"
        )
    return parts[0], parts[1], parts[3]


def _default_comment_post(pr_url: str, body: str) -> bool:
    """Post `body` as an issue comment on the PR via REST (never `gh pr comment`/edit).

    Uses `gh api repos/{owner}/{repo}/issues/{n}/comments` — the same REST path the
    label and reviewer-request flows use to avoid the classic-Projects GraphQL break.
    """
    owner, repo, number = _pr_url_parts(pr_url)
    result = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/issues/{number}/comments", "-f", f"body={body}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def post_codereview_comment(
    pr_url: str,
    findings: list[dict],
    *,
    head_sha: str | None = None,
    post_fn=None,
) -> bool:
    """MANDATORY per `/code-review` invocation: post a summary comment to the PR.

    Every `/code-review` call in the loop (step 2.5) MUST call this immediately after
    parsing, INCLUDING when `findings == []` — a clean review still posts so there are
    no silent reviews; the PR carries a visible record of every review and its findings'
    severity, parallel to a Copilot review.

    Fail-OPEN: returns True on success, False on any failure (a failed comment-post must
    not crash the loop) — but the comment is ALWAYS attempted. `post_fn(pr_url, body)`
    is injectable for tests; the default posts via REST.
    """
    body = format_codereview_comment(findings, head_sha=head_sha)
    poster = post_fn or _default_comment_post
    try:
        return bool(poster(pr_url, body))
    except Exception:
        return False


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


# ---------- Phase 1: degraded-review predicate ----------


def _is_sentinel(f: dict) -> bool:
    """True iff a finding is a degraded/unavailable sentinel.

    A sentinel is either:
    - source == "no-angles"  (the empty fan-out sentinel from merge_codereview_angles([]))
    - file.startswith("<review-output:")  (the _unparseable_finding shape)
    """
    if f.get("source") == "no-angles":
        return True
    return str(f.get("file", "")).startswith("<review-output:")


def is_degraded_review(findings: list[dict]) -> bool:
    """True iff findings is non-empty AND every element is a degraded/unavailable sentinel.

    Distinguishes "reviewed clean" (empty []) from "no reviewer ran / parse failed"
    (non-empty list of only sentinel findings). An empty [] is a genuinely clean review;
    a list of sentinels means the fan-out was degraded or unavailable.

    A list with >= 1 real finding (even alongside sentinels) returns False — real evidence
    was found, so the review is not degraded even if some angles failed.
    """
    if not findings:
        return False
    return all(_is_sentinel(f) for f in findings)
