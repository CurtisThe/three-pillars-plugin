"""review_merge — normalize + dedupe dual-source PR review findings.

Enhancement 1 (pr-fix-targeting-and-auto-review): each `/tp-pr-iterate` round
pairs the GitHub (Copilot) review with a local `/code-review` sub-agent. This
helper maps BOTH sources into one normalized-finding.v1 shape and collapses
near-duplicates so the union can be handed to a single `tp-pr-fix` round.

C1 architectural constraint: the normalize/parse/dedupe core is pure stdlib —
it computes and parses only. The module has NO `import anthropic` and never
shells out to `claude`; the `/code-review` dispatch + any model work live in
SKILL.md prose via `Agent()`. `parse_codereview_result` reads the one JSON object
the dispatched sub-agent is told to emit (the shared strict contract in
`_shared/strict_json_reply.py`); it does not invoke the model. The one I/O helper is
`post_codereview_comment` (the mandatory per-invocation review-summary comment);
it shells `gh` exactly as the sibling C1 helper `thread_resolver` does for
reply/resolve, and is injectable (`post_fn`) so the pure core stays test-isolated.
"""

from __future__ import annotations

import json
import subprocess  # noqa: F401 (kept: tests patch `review_merge.subprocess.run`)
import sys
from pathlib import Path
from urllib.parse import urlparse

# The dedupe family (collapse predicate, survivor rules, tunables) lives in the
# sibling `review_merge_dedupe` module — split out for the file-size cap only.
# Every name is RE-EXPORTED here, so `review_merge.dedupe(...)` and the private
# `review_merge._is_duplicate(...)` call sites are unchanged.
_HERE = Path(__file__).resolve().parent
_SHARED = _HERE.parents[1] / "_shared"
for _p in (_HERE, _SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from review_merge_dedupe import (  # noqa: E402,F401
    _NO_RANGE,
    _PROXIMITY_SLACK,
    _SIMILARITY_THRESHOLD,
    _VERDICT_RANK,
    _carry_reproducers,
    _distinct_threads,
    _is_duplicate,
    _is_exact_duplicate,
    _line_proximity,
    _matches_cluster,
    _more_specific,
    _norm_range,
    _promote_verdict,
    _same_file,
    _summary_similar,
    _survives,
    _verdict_rank,
    dedupe,
)
from automation_identity import DISCOVER, BotAuthUnavailable, run_gh_write  # noqa: E402
from finding_class import coerce  # noqa: E402
from strict_json_reply import one_object  # noqa: E402

# The only keys an angle reply may carry: an unknown key (`blocking_findings`, say) could hold
# findings the loop would never read, so it is unparseable rather than ignored.
_REPLY_KEYS = {"findings", "notes"}


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
        "verdict": _coerce_verdict(comment.get("verdict"), "unclear"),
        "merged_from": None,
    }


def normalize_codereview(finding: dict) -> dict:
    """A `/code-review` finding → normalized-finding.v1 (local: no thread/comment id).
    Reviewer `class`/`blocking`/`reproducer` tags go through `finding_class.coerce`."""
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
        "verdict": _coerce_verdict(finding.get("verdict"), "structural"),
        "merged_from": None,
    }
    conf = _coerce_confidence(finding.get("confidence"))
    if conf is not None:
        out["confidence"] = conf
    out.update(coerce(finding))
    return out


_VERDICT_ENUM = {"structural", "minor", "unclear"}


def _coerce_verdict(value, default: str) -> str:
    """Canonicalize a free-text verdict to the schema's lowercase enum.

    The severity rules compare case-insensitively (`_verdict_rank` lowercases)
    but downstream consumers test the STORED string exactly (`loop_driver`'s
    `_detect_conflicts` and the `has_structural` behind the `minor-only` round
    verdict both do `== "structural"`), and `/code-review` output arrives here
    unvalidated — so a `"Structural"` ranked as structural, won its collision, then
    read as NOT structural downstream, flipping a round holding a structural finding
    to minor-only. Canonicalizing once here keeps the two readings agreeing; casing
    and whitespace only — anything else falls back to the CALLER's own default.
    """
    if not isinstance(value, str):
        return default
    lowered = value.strip().lower()
    return lowered if lowered in _VERDICT_ENUM else default


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
            except (TypeError, ValueError, OverflowError):
                pass
    if isinstance(line, int) and not isinstance(line, bool):
        return line, line
    return 0, 0


# ---------- /code-review output parsing ----------


def parse_codereview_result(text: str) -> "tuple[list[dict], bool]":
    """Parse a `/code-review` angle reply, distinguishing CLEAN from UNPARSEABLE.

    The reply is exactly one JSON object `{"findings": [...], "notes"?: str}`, bare or in
    one fence (`strict_json_reply.one_object`: no prose around it, no second object or
    fence, no repeated key at any depth). `findings` must be a list of objects, lows
    included; `notes`, if present, a string or null, is context only and is never read.
    Returns `(findings, parsed_ok)`:

    - `([...], True)` — a conforming reply; `{"findings": []}` is the only clean signal.
    - `([], False)`   — anything else: prose, a bare list (the old format), a JSON string,
      an unknown key, a non-object finding. Never partially read.

    The distinction is load-bearing: the loop's two-stable terminal treats an empty
    findings list as "clean → may converge". The earlier lenient parser searched every
    fence for arrays, so an example `[]` fence plus a findings fence cut short by backticks
    inside a reproducer read as clean and hid a blocker (known issue M27, PRs #188/#191).
    Callers that gate convergence MUST use this (or `parse_codereview_findings_or_block`),
    never the bare list form.
    """
    data = one_object(text)
    notes = data.get("notes") if isinstance(data, dict) else None
    if data is None or not set(data) <= _REPLY_KEYS or not isinstance(notes, (str, type(None))):
        return [], False
    findings = data.get("findings")
    if not isinstance(findings, list) or not all(isinstance(f, dict) for f in findings):
        return [], False
    return findings, True


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
            f"{source} output could not be parsed as one {{\"findings\": [...]}} JSON "
            "object — treated as NOT clean (fail-closed; the loop must not converge on an "
            "unparseable review)"
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


def _default_comment_post(pr_url: str, body: str, *, config=DISCOVER, runner=None,
                          token_runner=None) -> bool:
    """Post `body` as an issue comment on the PR via REST (never `gh pr comment`/edit).

    Uses `gh api repos/{owner}/{repo}/issues/{n}/comments` — the same REST path the
    label and reviewer-request flows use to avoid the classic-Projects GraphQL break.
    The write runs as the configured automation account (`automation_identity.run_gh_write`,
    which discovers the repo config by default); an unavailable bot raises `BotAuthUnavailable`
    and nothing is posted. `config=None` is the plain ambient call.
    """
    owner, repo, number = _pr_url_parts(pr_url)
    result = run_gh_write(
        ["gh", "api", f"repos/{owner}/{repo}/issues/{number}/comments", "-f", f"body={body}"],
        config=config,
        runner=runner,
        token_runner=token_runner,
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
    digest: "str | None" = None,
    config=DISCOVER,
) -> bool:
    """MANDATORY per `/code-review` invocation: post a summary comment to the PR.

    Every `/code-review` call in the loop (step 2.5) MUST call this immediately after
    parsing, INCLUDING when `findings == []` — a clean review still posts so there are
    no silent reviews; the PR carries a visible record of every review and its findings'
    severity, parallel to a Copilot review.

    Fail-OPEN: returns True on success, False on any failure (a failed comment-post must
    not crash the loop) — but the comment is ALWAYS attempted. `post_fn(pr_url, body)`
    is injectable for tests; the default posts via REST as the configured automation account
    (`config`: `DISCOVER` loads the repo config, `None` is the ambient login). Fail-open does
    NOT cover an unavailable bot: `BotAuthUnavailable` is re-raised (never post as the ambient
    login in the bot's place), with nothing posted.

    digest: optional proof-of-review digest (from review_proof.format_proof_digest).
    When provided, appended as `\\n` + digest to the body. Absent digest → body
    is byte-identical to the pre-digest form.
    """
    body = format_codereview_comment(findings, head_sha=head_sha)
    if digest is not None:
        body = body + "\n" + digest
    poster = post_fn or (lambda url, text: _default_comment_post(url, text, config=config))
    try:
        return bool(poster(pr_url, body))
    except BotAuthUnavailable:
        raise
    except Exception:
        return False


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
