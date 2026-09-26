"""review_merge_dedupe — the collapse-near-duplicates half of review_merge.

Split out of `review_merge.py` purely for the file-size cap (CLAUDE.md
§File Size Limits); `review_merge` re-exports every name defined here, so
`review_merge.dedupe(...)` / `review_merge._is_duplicate(...)` call sites are
unchanged. This module is the single home of the collapse predicate family.

C1 architectural constraint (inherited from review_merge): pure stdlib, no
`import anthropic`, never shells out to `claude` — it computes only.
"""

from __future__ import annotations

import difflib

# Dedup tunables (detailed-design §Decisions). Conservative on purpose: a
# false-merge silently drops a real finding, an over-keep just costs one extra
# fix attempt.
_PROXIMITY_SLACK = 3
_SIMILARITY_THRESHOLD = 0.6

# The range every finding with NO usable line anchor normalizes to. It is a
# sentinel, not a coordinate: GitHub file-level / outdated review comments and
# `thread_resolver.list_review_threads` rows (which carry `path` and no line
# field at all) all land here, so two findings sharing it are NOT thereby at the
# same place. Excluded from the exact-match short-circuit for that reason, and
# `_line_proximity` treats it as a sentinel rather than as line 0.
_NO_RANGE = (0, 0)

# Survivor severity order for an exact collision. Anything not named here
# (Copilot's default 'unclear', a free-text verdict) ranks below both.
_VERDICT_RANK = {"structural": 2, "minor": 1}


def _line_proximity(a, b, slack: int = _PROXIMITY_SLACK) -> bool:
    """True when two same-file line ranges overlap after padding each by `slack`.

    `_NO_RANGE` is a SENTINEL, not line 0, so it is handled before the padding
    arithmetic. Two anchorless findings are equally place-less and stay eligible
    for the fuzzy path (which still demands summary similarity); an anchorless
    finding versus a real range is never proximate. Treating the sentinel as
    line 0 made every anchorless finding proximate to lines 1..3 of its file,
    so a file-level comment could collapse into a finding at the top of the file
    on wording alone.
    """
    a_none, b_none = (a == _NO_RANGE), (b == _NO_RANGE)
    if a_none or b_none:
        return a_none and b_none
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


def _norm_range(r) -> tuple[int, int]:
    """A line_range as an ordered (start, end) tuple; missing/blank → (0, 0).

    Agrees with `review_merge._coerce_range` — which produces every normalized
    `line_range` — on TYPE, ARITY and element handling:

    * only a list/tuple is a range, so a stray `"12"` degrades to `_NO_RANGE`
      instead of being iterated into the span (1, 2);
    * `len(r) >= 2`, so a 1-element `[7]` is not a range either;
    * only `r[0]` and `r[1]` are read, so a 3-element `[3, 9, 1]` is the span
      (3, 9) here exactly as `_coerce_range` reads it, not (1, 9);
    * `bool` elements are rejected — `bool` is an `int` subclass, so
      `[True, False]` would otherwise coerce to a nonsense (0, 1) range.
    """
    if not isinstance(r, (list, tuple)) or len(r) < 2:
        return _NO_RANGE
    a, b = r[0], r[1]
    if isinstance(a, bool) or isinstance(b, bool):
        return _NO_RANGE
    try:
        a, b = int(a), int(b)
    except (TypeError, ValueError, OverflowError):
        return _NO_RANGE
    return (min(a, b), max(a, b))


def _same_file(x: dict, y: dict) -> bool:
    """True when both findings name the same NON-EMPTY file.

    Truthiness, not `!= ""`: a finding may carry `file: None` (an unanchored
    review comment), and two Nones must never be read as "the same file".
    """
    return bool(x.get("file")) and x.get("file") == y.get("file")


def _distinct_threads(x: dict, y: dict) -> bool:
    """True when both findings carry a real, DIFFERENT `thread_id`.

    Only Copilot findings have one (`normalize_codereview` sets it to None), so
    this is exactly the Copilot-vs-Copilot case. Two GitHub review threads are
    two comments by construction — collapsing them would drop a `thread_id`
    that reply-and-resolve needs to ever close that thread.
    """
    tx, ty = x.get("thread_id"), y.get("thread_id")
    return bool(tx) and bool(ty) and tx != ty


def _is_exact_duplicate(x: dict, y: dict) -> bool:
    """True when two findings name the SAME file AND the SAME real line range.

    The exact-match short-circuit. Two `/code-review` angles that describe one
    defect in their own words agree byte-for-byte on `file` + `line_range` but
    can score well under the summary-similarity threshold; without this rule the
    twin survived and the PR comment overstated the finding count. Identical
    coordinates are treated as the same defect regardless of summary wording.

    Ranges are compared normalized (`_norm_range`) so `[10, 12]` and `[12, 10]`
    — the same span written in either order — collapse.

    `_NO_RANGE` is EXCLUDED. A missing / null / non-numeric `line_range` (with
    no `line` either) normalizes to `(0, 0)`, which is the absence of a line
    anchor rather than a location — GitHub file-level and outdated review
    comments, and every `list_review_threads` row, look like this. Collapsing on
    it would unconditionally merge two DISTINCT file-level findings on one path
    and lose the dropped twin's `thread_id`. Such pairs fall through to the
    fuzzy path, which still demands summary similarity before collapsing them.

    Two findings with DISTINCT non-null `thread_id`s are excluded for the same
    reason. The rationale above — "two angles word one defect differently" —
    holds only for the local `/code-review` fan-out, which has no threads. Two
    separate GitHub review threads anchored on one line are two comments by
    construction, so short-circuiting them would silently drop one thread_id.
    Copilot-vs-code-review and code-review-vs-code-review at identical
    coordinates still collapse; that is the short-circuit's whole point.
    """
    rx = _norm_range(x.get("line_range"))
    return (
        _same_file(x, y)
        and rx != _NO_RANGE
        and rx == _norm_range(y.get("line_range"))
        and not _distinct_threads(x, y)
    )


def _is_duplicate(x: dict, y: dict) -> bool:
    """The full collapse predicate: exact coordinates OR the fuzzy near-miss.

    Order matters — the exact-match short-circuit runs BEFORE the similarity
    comparison so identical file+range collapses unconditionally. Near-miss
    ranges (proximate but not identical) and anchorless `_NO_RANGE` pairs — the
    one exact-path exclusion that can still collapse — have to clear the summary
    similarity threshold here. The exact path's OTHER exclusion is absolute: a
    pair holding two distinct `thread_id`s is rejected on this branch too, by
    the LAST conjunct (`not _distinct_threads(x, y)`). The similarity test may
    well run first and pass — what it cannot do is make such a pair collapse, on
    either path. An anchorless finding paired with a REAL range is not proximate
    at all (see `_line_proximity`), so that pair never collapses on either
    branch either.

    Both branches normalize the range through `_norm_range`: the raw value is
    untrusted LLM / GitHub output, and handing `None` or `[]` straight to
    `_line_proximity` raises (TypeError / ValueError on `min()`).

    `_distinct_threads` guards BOTH branches, not just the exact one. Two Copilot
    threads a line or two apart, worded alike, is exactly how one hunk draws two
    comments — collapsing them on the fuzzy path dropped a `thread_id` just as
    surely as collapsing them on the exact path did.
    """
    if _is_exact_duplicate(x, y):
        return True
    return (
        _same_file(x, y)
        and _line_proximity(_norm_range(x.get("line_range")), _norm_range(y.get("line_range")))
        and _summary_similar(x.get("summary", ""), y.get("summary", ""))
        and not _distinct_threads(x, y)
    )


def _more_specific(a: dict, b: dict) -> bool:
    """True when `a`'s summary is the longer/more specific of the two."""
    return len(str(a.get("summary") or "")) >= len(str(b.get("summary") or ""))


def _verdict_rank(f: dict) -> int:
    """Severity of a finding's verdict — higher is more severe."""
    return _VERDICT_RANK.get(str(f.get("verdict") or "").strip().lower(), 0)


def _survives(a: dict, b: dict) -> bool:
    """True when `a` should survive a collision with `b`; ties go to `a`.

    Order: a real `thread_id` first, then Copilot source, then the more SEVERE
    verdict, then the longer/more specific summary, then first-seen.

    The thread test comes before the source test because the source is only a
    PROXY for the thread. `source == "copilot"` wins collisions solely because
    Copilot findings carry the `thread_id` reply-and-resolve needs to ever close
    the thread — but a Copilot-shaped record whose `thread_id` is null (a
    file-level comment row, a hand-built finding) carries nothing, and letting
    it take the slot from a record that DOES hold a thread dropped exactly what
    the rule exists to protect. Severity outranks length because the round
    verdict is derived from the surviving findings: letting a wordy `minor` twin
    beat a terse `structural` one at the same coordinates reported the round as
    minor-only while a structural finding had actually been raised.

    This picks the surviving RECORD only. Because the thread/source tests run
    first, the survivor can be the LESS severe of the pair — `dedupe` therefore
    promotes the survivor's `verdict` separately (`_promote_verdict`) so no
    severity is lost when the record is chosen for its thread_id.
    """
    a_thread, b_thread = bool(a.get("thread_id")), bool(b.get("thread_id"))
    if a_thread != b_thread:
        return a_thread
    a_copilot = a.get("source") == "copilot"
    b_copilot = b.get("source") == "copilot"
    if a_copilot != b_copilot:
        return a_copilot
    ra, rb = _verdict_rank(a), _verdict_rank(b)
    if ra != rb:
        return ra > rb
    return _more_specific(a, b)


def _promote_verdict(survivor: dict, dropped: dict) -> None:
    """Raise `survivor['verdict']` to the more severe of the collapsed pair.

    Never a downgrade: only a strictly higher `_verdict_rank` overwrites. The
    survivor record is chosen by `_survives`, which tests Copilot precedence
    (for the `thread_id`) BEFORE severity — so a Copilot `minor`/`unclear` can
    legitimately win a collision with a code-review `structural`. Without this
    the structural verdict vanished with the dropped twin, the round read
    `minor-only`, and the fix round it should have triggered was skipped.

    The CANONICAL lowercase form is stored, not the dropped twin's raw string.
    Rank is case-insensitive, so a `"Structural"` that outranks the survivor
    would otherwise be copied verbatim onto it and fail the exact
    `== "structural"` test downstream — promoting the severity in name only.
    `review_merge._coerce_verdict` canonicalizes both normalizers' output, so
    this is a backstop for hand-built findings that skip normalization; a rank
    above 0 is by construction a `_VERDICT_RANK` key.

    The finding-class tags (`blocking`/`class`/`reproducer`) travel with the
    promoted verdict, so a blocking claim keeps its reproducer.
    """
    if _verdict_rank(dropped) > _verdict_rank(survivor):
        survivor["verdict"] = str(dropped.get("verdict") or "").strip().lower()
        for key in ("blocking", "class", "reproducer"):
            if key in dropped:
                survivor[key] = dropped[key]


def _carry_reproducers(survivor: dict, dropped: dict) -> None:
    """Keep a blocking twin's reproducer(s) as the survivor's `alt_reproducers`.

    Two blocking twins are one defect, but each angle wrote its own reproducer.
    Keeping only the survivor's let a non-reproducing survivor downgrade the
    finding while the dropped twin's reproducer would have demonstrated it;
    `reproduce.run_reproducers` tries the alternates before downgrading.

    A legacy-shape survivor (no `class`/`blocking` tags, same `structural`
    rank, so `_promote_verdict` is a no-op) adopts a blocking twin's tags —
    otherwise it is downgraded `legacy-no-reproducer` and the demonstrated
    defect is lost.
    """
    if dropped.get("blocking") is not True:
        return
    if "class" not in survivor and "blocking" not in survivor:
        for key in ("blocking", "class", "reproducer", "alt_reproducers"):
            if key in dropped:
                survivor[key] = dropped[key]
        return
    if survivor.get("blocking") is not True:
        return
    alts = list(survivor.get("alt_reproducers") or [])
    for r in [dropped.get("reproducer"), *(dropped.get("alt_reproducers") or [])]:
        if isinstance(r, dict) and r != survivor.get("reproducer") and r not in alts:
            alts.append(r)
    if alts:
        survivor["alt_reproducers"] = alts


def _matches_cluster(members: list[dict], f: dict) -> bool:
    """True when `f` belongs to an already-collapsed cluster of findings.

    Two admission routes, and they have different reach:

    * the FUZZY comparison (proximate range + similar summary) runs against
      `members[0]` — the cluster's FIRST-SEEN member — never against whichever
      record currently survives it. The survivor can change on any collision
      (`_survives` may hand the slot to a record at a different line), and
      comparing against a moved survivor let a cluster walk up the file:
      `[10]`, `[13]`, `[16]` with similar wording collapsed into one, though 10
      and 16 are nowhere near each other. Proximity is not transitive, so the
      fuzzy comparison key stays put;
    * an EXACT coordinate twin (same file, same real line range) of ANY member
      joins regardless. Identical coordinates are one defect by design — that
      is the short-circuit's whole premise — and it does not stop being true
      because the twin arrived after a sibling absorbed the anchor.

    The invariant this preserves is a SPAN, not "the cluster never moves": every
    member is within `_PROXIMITY_SLACK` lines of the first-seen anchor (a fuzzy
    joiner by construction, an exact joiner because it shares a member's
    coordinates, inductively), so a cluster cannot creep. It is still a greedy
    single pass — a finding joins the first cluster that accepts it — so the
    INPUT ORDER decides which finding anchors which cluster, and a different
    order over the same findings can legitimately produce a different grouping.

    The distinct-thread exclusion is the one test applied to EVERY member on
    BOTH routes: the anchor may be a thread-less `/code-review` finding that a
    Copilot record has since taken the slot from, and no cluster may ever
    swallow a second `thread_id`.
    """
    if any(_distinct_threads(m, f) for m in members):
        return False
    return _is_duplicate(members[0], f) or any(_is_exact_duplicate(m, f) for m in members[1:])


def dedupe(findings: list[dict]) -> list[dict]:
    """Collapse near-duplicate findings across sources, order-stable.

    Collapse key: same file AND (identical real line range OR line-proximity
    plus summary-similarity). On a collision the Copilot finding is KEPT (it
    carries the `thread_id` the reply-and-resolve step needs); the dropped
    twin's `finding_id` is recorded in the kept finding's `merged_from`, and its
    `verdict` is promoted onto the survivor when it is the more severe of the
    two — a record can be kept for its thread_id, but never at the cost of a
    severity. When neither side is Copilot the more severe verdict wins, then
    the longer/more specific summary (ties go to first-seen, preserving order
    stability). The exact and fuzzy paths take this same route.

    A cluster spans at most `_PROXIMITY_SLACK` lines around its first-seen
    anchor, and the pass is greedy — see `_matches_cluster`.
    """
    kept: list[dict] = []
    # `clusters[i]` is every finding that landed in `kept[i]`, first-seen first.
    # `kept[i]` is a COPY, so a promoted verdict never edits a cluster member.
    clusters: list[list[dict]] = []
    for f in findings:
        match_idx = next((i for i, c in enumerate(clusters) if _matches_cluster(c, f)), None)
        if match_idx is None:
            kept.append(dict(f))
            clusters.append([f])
            continue
        clusters[match_idx].append(f)
        existing = kept[match_idx]
        # `_survives` owns the whole precedence order; `existing` wins ties so
        # the output stays order-stable.
        if _survives(existing, f):
            survivor, dropped = existing, f
        else:
            survivor, dropped = dict(f), existing
            kept[match_idx] = survivor
        _promote_verdict(survivor, dropped)
        _carry_reproducers(survivor, dropped)
        # Carry the dropped twin's OWN provenance too, not just its id — in a
        # 3+-way collision the dropped finding may already have absorbed others.
        merged = list(survivor.get("merged_from") or [])
        for mid in list(dropped.get("merged_from") or []) + [dropped.get("finding_id")]:
            if mid not in (None, "") and mid not in merged:
                merged.append(mid)
        survivor["merged_from"] = merged or None
    return kept
