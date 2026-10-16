"""THE RESOLVER-SIDE INVARIANT: a mechanical resolve preserves every line, or it defers.

The resolver-side analogue of `test_verify_superset.py`. That module pins "`atoms()` never
subtracts" — the verifier must SEE everything. This one pins the mirror: the resolver must not
DELETE anything it does not understand.

  R0  **Totality** — for every hunk any mechanical resolver returns RESOLVED for, every line of
      `ours` and `theirs` is accounted for in the output, modulo the class's declared licence.
  R1  **Well-formedness** — a hunk whose sides contain a conflict marker is never resolved
      mechanically. Its sides are not what they claim to be.
  R2  **Fall-closed, not give-up** — the legitimate pure shapes still auto-resolve. R0 is
      trivially satisfiable by deferring everything, so the floor is asserted too.
  R3  **No invention** — the mirror of R0 and the only check here that shares NO specification
      with the licence: every output line is an input line, counted. R0 and its oracle both read
      the licence table, so an error in that TABLE is agreed on rather than caught (S-K2, and the
      whole lesson of round 14). R3 reads raw text and no licence at all, which is what lets it
      catch a resolver PADDING a count with a line it was never given (S-K1).

Why R0 must live at the RESOLVER and cannot be delegated to `verify()`: the verifier sees a lost
line only if that line parses as an atom. `ENTRY`/`ROW`/`LOG`/`DECISION_ENTRY` are the whole
inventory, so a deleted line of ordinary prose is not an atom at all, `mechanical_applied=True`
with a non-empty surviving atom set yields VERIFIED, and the loss certifies clean. That blind spot
is known-issue H8, and S-I1 is it firing: an inventory row on ours plus unkeyed prose on theirs
resolved RESOLVED with the prose gone and `verify()` reporting `dropped: []`.

The BASE side is deliberately outside R0 — it is the common ancestor both sides diverged from, so
re-emitting it would be adding content, not preserving it.
"""
import os
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from classify import (  # noqa: E402
    AUTO_RESOLVE, GATED, MECHANICAL, Hunk, classify_file, classify_hunk,
)
from conflict_fixtures import INVENTORY_ROW_MERGE  # noqa: E402
from licence_oracle import lost_lines as _lost_lines  # noqa: E402
from preservation_corpus import corpus as _doc_corpus  # noqa: E402
from resolve import (  # noqa: E402
    DEFER, DEFER_CODES, HunkResult, MECH_RESOLVERS, RESOLVED, _deferred, resolve_file,
    resolve_hunk,
)
from resolve_totality import (  # noqa: E402
    CannotPlace, embedded_marker, overproduced, unplaceable,
)
from resolver_hunk_corpus import generated_hunks  # noqa: E402

# The S-I1 repro, verbatim from the orchestrator's report.
S_I1 = ("<<<<<<< stray\n| D12 | ours row |\n=======\n<<<<<<< nested-open text\n"
        "this trailing important sentence gets silently dropped\n>>>>>>> theirs\n")
S_I1_LOST = "this trailing important sentence gets silently dropped"


# ---- the oracle -------------------------------------------------------------------------------
# A SECOND reading of the per-class licence, written by a different mechanism than the checker
# under test — see `licence_oracle` for what that independence is and is not (S-J5).

def _resolutions(texts):
    """`(name, hunk, result)` for every hunk in `texts`, whatever the verdict."""
    for name, text in texts:
        for seg in classify_file(text).segments:
            if isinstance(seg, Hunk):
                yield name, seg, resolve_hunk(seg)


def _corpus():
    return list(_doc_corpus()) + list(generated_hunks())


# ---- R0: totality ------------------------------------------------------------------------------

def test_r0_every_mechanical_resolution_accounts_for_every_input_line():
    """THE rule. A RESOLVED verdict is a claim that the merge represents both sides; a line of
    either side missing from the output falsifies that claim, whether or not it is an atom."""
    failures = []
    for name, hunk, result in _resolutions(_corpus()):
        if result.status != RESOLVED:
            continue
        lost = _lost_lines(hunk, result)
        if lost:
            failures.append((name, result.label, lost[:3]))
    assert not failures, f"a mechanical resolver DROPPED input lines: {failures[:6]}"


def test_r0_is_not_vacuous_because_hundreds_of_hunks_really_do_resolve():
    """R0 is satisfiable by deferring everything, so the population it checks is the invariant's
    load-bearing half. These floors are measured, not aspirational: a change that halved the
    mechanical lane would fail here rather than quietly making R0 a tautology."""
    verdicts = [(r.label, r.status) for _n, _h, r in _resolutions(_corpus())]
    resolved = [lab for lab, st in verdicts if st == RESOLVED]
    deferred = [lab for lab, st in verdicts if st == DEFER]
    # Measured 2026-09-10 (round 21): 29 resolved / 1183 deferred across 438 documents + 700 hunks.
    # Round 14 measured 95 / 1117; round 17 moved 47 hunks from RESOLVED to a deferral (48 / 1164),
    # round 18 four more (44 / 1168) and round 19 eleven more (33 / 1179) — each a refusal of a
    # shape the old resolvers mis-merged — round 20 two more, by gating `id-renumber-collision`
    # (31 / 1181), and round 21 two more, inventory hunks whose rows could change tables.
    # basesync-three-way-verifier Phase 4: 31 -> 32 resolved, deferred unchanged at 1184 (the new
    # `shaped-line-merge` fixture is the one added RESOLVED hunk), so the floor is the measure.
    # The breakdown is in `test_every_deferral_has_a_named_cause_and_the_breakdown_is_pinned`.
    assert len(resolved) >= 32, len(resolved)
    assert len(deferred) >= 900, len(deferred)
    # ...and EVERY class that may auto-resolve is represented, so none is silently inert, while a
    # GATED class never resolves. (Measured round 21: log-insertion 11, inventory 8,
    # decision-insertion 6, append-log 4. Round 19's two id-renumber resolutions are now `gated`;
    # `last-updated-preamble` is represented by the corpus's one `fixed:last-updated` hunk.)
    assert set(resolved) == set(AUTO_RESOLVE), sorted(set(resolved))
    assert GATED and not GATED & set(resolved) and AUTO_RESOLVE | GATED == MECHANICAL


def test_every_deferral_has_a_named_cause_and_the_breakdown_is_pinned():
    """m-J1: the causal breakdown of the deferrals was asserted in a commit message and by no test,
    so nothing would notice it drifting. It is a mechanical property of a SEEDED corpus, so it is
    pinned EXACTLY rather than as a floor — a change that moves any bucket has to say which one and
    why, which is the whole value of the number.

    The buckets are the codes of `DEFER_CODES`, the deferrals `resolve_hunk` decides, in its order.

    Round 14 moved exactly seven hunks, all `design-inventory-row-merge`, and every move is
    accounted for: SIX went `would-drop` -> `cannot-place` (the resolver now refuses a theirs line
    it can only place by coincidence, so the refusal happens AT the resolver instead of the
    post-condition catching the drop afterwards — same verdict, better reason), and ONE went
    RESOLVED -> `cannot-place` (S-K1: ours carries `| D12 |` on two DIFFERENT rows, and the old
    code emitted theirs' row twice while dropping the row it did not choose). `would-invent` is
    empty — it is the post-condition for a resolver padding a count, which no resolver does now; it
    is listed so a future one cannot land as `UNCATEGORISED`.

    Round 15 moved NOTHING (the numbers below are unchanged), but it changed how the bucket is
    decided: by `HunkResult.code`, a machine-readable value `resolve_hunk` sets at each deferral
    site, instead of by substring-matching the human-readable `reason`. A reworded reason used to
    silently re-file its bucket as `UNCATEGORISED`, and `would-invent` — the one bucket with no
    corpus instance to notice it — was matched on the word `INVENT` alone. The prose is now free to
    change; the code is asserted against `DEFER_CODES` and the deferral sites are exhaustive.

    Round 17 moved 47 RESOLVED hunks and re-filed 40 already-deferred ones, measured hunk by hunk
    against the round-16 code on this seeded corpus:
      * id-renumber-collision, RESOLVED -> `semantic` 16 / `not-confident` 13 / `cannot-place` 3.
        The class then required no ID heading in base, one letter and a real collision (F4), so
        hunks with an ID heading in base (an EDIT) or two non-colliding IDs relabel
        `generic-prose`, or `append-only-log` and fail its confidence check. Three refuse at the
        resolver: ONE whose ID is already a heading elsewhere in the document (F4b, `generated:241`)
        and TWO where ours carries the same ID twice (`hunk:227`, `hunk:660`). (Round 17's text
        credited all three to the heading-elsewhere arm; the corpus shows one.)
      * append-only-log, RESOLVED -> `cannot-place` 10: the two tails share a non-blank line that
        is not a byte-identical whole tail (F5).
      * design-inventory-row-merge, RESOLVED -> `cannot-place` 5: a row one side deleted and the
        other kept, or an id both sides added with different rows (F3). (The corpus's copy of
        `INVENTORY_ROW_MERGE` was a sixth; the fixture now carries a base row and resolves.)
      * already-deferred id-renumber hunks relabelled by the stricter classifier: `malformed-hunk`
        -> `semantic` 11 / `not-confident` 5, `not-confident` -> `not-confident` 8 (now as
        append-only-log) / `semantic` 7, `cannot-place` -> `not-confident` 5 / `semantic` 4. The
        classifier now rejects these before the marker check runs, hence `malformed-hunk` 41 -> 25.

    Round 18 moved 4 RESOLVED hunks and re-filed 6 already-deferred ones, measured hunk by hunk
    against the round-17 code. Every one is a 2-way region (no `|||||||` section, so no recorded
    base), which `id-renumber-collision` now refuses along with any non-empty base (R2): it
    relabels `generic-prose` and defers as `semantic`. RESOLVED -> `semantic` 4;
    `malformed-hunk` -> `semantic` 3 (25 -> 22); `not-confident` -> `semantic` 2 (71 -> 69);
    `cannot-place` -> `semantic` 1 (42 -> 41, `hunk:227`'s repeated ID). `semantic` 1024 -> 1034.
    No non-blank-base hunk moved: round 17 already refused every one the corpus holds. The corpus's
    copy of `ID_RENUMBER` did not move either — it carried a one-BLANK-line base (`diff3(..., "",
    ...)`), which R2 also refuses, so the fixture now uses the real empty base and still resolves.
    The file-level renumber refusal (R1) is not visible here: this test resolves hunk by hunk.

    Round 19 moved 11 RESOLVED hunks and re-filed 91 already-deferred ones, measured hunk by hunk
    against the round-18 code. Every one now relabels `generic-prose` and defers as `semantic`
    (1034 -> 1136), because the class that claimed it gained a purity predicate (P1/P2):
      * append-only-log, RESOLVED -> `semantic` 10: two differing tails, at least one not whole log
        entries — a continuation, prose, a section heading or a decision line leading or inside
        it — so theirs' first line would have landed under ours' last line (P2). The THREE corpus
        hunks with one empty tail (`hunk:449`, `hunk:513`, `hunk:663`) still resolve: the merged
        region is one side's region verbatim. (Round 19's text said two.)
      * append-only-log, already deferred -> `semantic`: `not-confident` 68 (69 -> 1; the class
        used to claim these and then fail `is_confident` on a heading/row line, and the purity
        predicate now refuses them first), `malformed-hunk` 9 and `cannot-place` 8 (the shared
        tail line of F5), all with a non-log tail.
      * id-renumber-collision -> `semantic` 6: `malformed-hunk` 4 (`generated:37`, `:136`, `:202`,
        `:225` — a marker look-alike, a table line or `## History` before or among the entries on
        both sides, which the whole-entries predicate now refuses before the marker check; 22 ->
        9 with the append-only ones), `cannot-place` 2 (41 -> 31 with the append-only ones):
        `hunk:660`, whose ours side starts with `a body line`, and `generated:241`'s first region,
        which another region follows directly, so `Hunk.post_context` is unknown (None).
      * decision-entry-insertion, RESOLVED -> `semantic` 1 (`generated:332`): the prefix-scan parse
        leaves a stray `>>>>>>> branch` content line directly after the region, which does not
        start an entry, so the far-edge boundary refuses it.

    Round 20 moved 2 RESOLVED hunks and re-filed 1 deferred one, all to the new `gated` bucket,
    measured hunk by hunk against the round-19 code: `id-renumber-collision` is GATED, and
    `resolve_hunk` decides the gate before every other check. RESOLVED -> `gated` 2 (the corpus's
    copy of `ID_RENUMBER` and `adversarial:two-way-region-then-real-conflict`'s second region);
    `malformed-hunk` -> `gated` 1 (`adversarial:mid-region-separator-lookalike`, 9 -> 8). The same
    round widened the purity predicates' heading test (indented ATX and setext headings are foreign)
    and made a hand-built `Hunk`'s `post_context` unknown by default; measured, neither moved a hunk.

    Round 21 moved 2 RESOLVED hunks and re-filed 23 deferred ones, measured hunk by hunk against the
    round-20 code. Every one was `design-inventory-row-merge` and now relabels `generic-prose`,
    deferring as `semantic` (1136 -> 1161), because the class predicate gained the table-run
    refusal (`table_run.table_run_refusal`, S1). By the arm that refuses it first:
      * a blank line on ours: RESOLVED 1 (`generated:379`: a blank above ours' only row, and
        theirs empty — nothing was appended, but the blank refuses whatever the merge would do),
        `cannot-place` 9;
      * a blank line on theirs: `cannot-place` 6;
      * a delimiter row that does not open its side: on ours, RESOLVED 1 (`hunk:39`: ours' new row
        sits on a `| --- |`, which makes it a header, and theirs' row was appended under it),
        `cannot-place` 3, `malformed-hunk` 1 and `would-drop` 2 (both of that bucket's hunks, so
        it is empty now; `test_the_would_drop_bucket_is_reachable_through_resolve_hunks_real_
        dispatch` drives it); on theirs, `cannot-place` 2.
    `cannot-place` 31 -> 11, `malformed-hunk` 8 -> 7, `would-drop` 2 -> 0. The frame-mismatch arm,
    the appended-row checks and the NBSP blank-line change to `_heading_at` moved no corpus hunk.

    Round 22 re-filed 3 deferred hunks and moved no RESOLVED one (29 still resolve), measured hunk
    by hunk against the round-21 code: `malformed-hunk` -> `semantic` 3 (7 -> 4, 1161 -> 1164).
    Each carries a `<<<<<<<` content line on a side (`generated:63` and `hunk:104` as
    `log-entry-insertion`, `hunk:341` as `append-only-log`), which the keep-both line-shape
    allowlist (`line_shapes.keep_both_refusal`) reads as a line opening an HTML block, so the class
    predicate refuses it before the marker check runs. Its other arms and the inventory
    carriage-return arm moved no corpus hunk.

    The keyed-heading-insertion wiring moved exactly one hunk: `hunk:428` (ours one `### L9:` entry,
    theirs `### L5:` and `### L4:`, distinct numbered keys, empty base) went `generic-prose` ->
    RESOLVED as keep-both, so `semantic` 1164 -> 1163. No other bucket moved.

    The `last-updated-preamble` wiring moved none: no seeded hunk is one date-only line per side,
    and the one `fixed:last-updated` hunk the corpus now ends with RESOLVES, so every bucket holds.

    PR #206 round 1 moved 2 RESOLVED `log-entry-insertion` hunks to `cannot-place` (11 -> 13):
    `log-entry-insertion` now emits the whole entries both blocks open or close with once and
    REFUSES when the differing middles still share an entry start, which plain concatenation wrote
    twice. `hunk:347` (theirs carries ours' `2026-07-04` entry three times above the shared
    `design-slug` suffix) and `hunk:689` (both carry the `design-slug` entry, but only ours gives it
    a body line, so it is no common suffix).

    This design (basesync-three-way-verifier) added `shaped-line-merge` and moved NO bucket: the
    seeded corpus holds no hunk of the class but its own fixture, which RESOLVES (resolved 31 ->
    32, deferred 1184 -> 1184), so semantic stays 1163 and every other bucket holds.
    """
    def bucket(r):
        return r.code if r.code in DEFER_CODES else f"UNCATEGORISED: {r.reason}"

    counts = Counter(bucket(r) for _n, _h, r in _resolutions(_corpus()) if r.status == DEFER)
    assert counts == Counter({"semantic": 1163, "not-confident": 1, "malformed-hunk": 4,
                              "cannot-place": 13, "gated": 3}), counts


def test_the_would_drop_bucket_is_reachable_through_resolve_hunks_real_dispatch(monkeypatch):
    """Round 21 emptied the corpus's `would-drop` bucket (its two hunks now fail the inventory
    class predicate), so nothing drove that deferral site any more. This does, the way the
    `would-invent` test below does: a resolver that loses theirs' line, dispatched through
    `resolve_hunk` past the gated/confidence/marker/CannotPlace checks, must defer with that code."""
    h = Hunk(ours=["- **2026-01-02** — ours"], base=[], theirs=["- **2026-01-03** — theirs"],
             label="log-entry-insertion", post_context="")
    lossy = HunkResult("log-entry-insertion", RESOLVED, list(h.ours))
    monkeypatch.setitem(MECH_RESOLVERS, "log-entry-insertion", lambda _h: lossy)
    r = resolve_hunk(h)
    assert r.status == DEFER and r.code == "would-drop", (r.code, r.reason)
    assert "\n".join(r.lines).count("- **2026-01-03** — theirs") == 1, "the deferral round-trips"


def test_the_would_invent_bucket_is_reachable_through_resolve_hunks_real_dispatch(monkeypatch):
    """m-L2. `would-invent` was wired by prose and driven by no test: no resolver overproduces, so
    the ONLY evidence the bucket worked was that the string matched a string. This drives it end to
    end — a resolver that pads its output with a duplicate, dispatched through `resolve_hunk`, past
    the gated/confidence/marker/CannotPlace/`unplaceable` checks that come first — and asserts the
    deferral arrives with the right CODE. `unplaceable` cannot see this: a duplicate loses nothing,
    so only the raw-multiset upper bound (R3) can, which is the whole reason the bucket exists.
    """
    h = Hunk(ours=["| Design | Name |", "| --- | --- |", "| D12 | a | OURS |"], base=[],
             theirs=["| Design | Name |", "| --- | --- |", "| D12 | a | THEIRS |"],
             label="design-inventory-row-merge")
    padded = HunkResult("design-inventory-row-merge", RESOLVED,
                        list(h.ours[:2]) + ["| D12 | a | THEIRS |"] * 2)
    monkeypatch.setitem(MECH_RESOLVERS, "design-inventory-row-merge", lambda _h: padded)

    r = resolve_hunk(h)
    assert r.status == DEFER and r.code == "would-invent", (r.code, r.reason)
    assert "would INVENT" in r.reason, r.reason        # the prose still says so, for the human
    assert "\n".join(r.lines).count("| D12 | a | THEIRS |") == 1, "the deferral round-trips"
    assert unplaceable(h, h.label, padded.lines) == [], "the drop check is blind to a padded copy"


def test_every_deferral_site_sets_a_code_and_no_code_is_unreachable():
    """The other half of keying on a code: the codes are exhaustive over the deferral sites, and
    `_deferred` refuses any value not in `DEFER_CODES`, so a new site cannot ship codeless and a
    typo cannot invent a silent bucket. Read off the SOURCE, because that is where the drift would
    be — a site added without a code is the failure this replaces."""
    src = (Path(__file__).resolve().parent / "resolve.py").read_text(encoding="utf-8")
    sites = re.findall(r"_deferred\(h,(.*?)\)\n", src, flags=re.S)
    codes = [c for site in sites for c in DEFER_CODES if f'"{c}"' in site.split(",")[-1]]
    # Eight sites for seven codes: `resolve_file`'s file-level renumber refusal (round 18, R1) is a
    # second `cannot-place` site, after `resolve_hunk`'s own.
    assert len(DEFER_CODES) == 7 and len(sites) == 8, (len(sites), DEFER_CODES)
    assert codes.count("cannot-place") == 2, codes
    assert len(codes) == len(sites), (codes, len(sites))               # every site names one
    assert set(codes) == set(DEFER_CODES), sorted(set(DEFER_CODES) - set(codes))
    with pytest.raises(AssertionError):
        _deferred(Hunk(ours=[], base=[], theirs=[], label="generic-prose"), "x", "not-a-code")


def test_r0_reports_the_pre_fix_inventory_resolver():
    """Non-vacuity as a counterfactual: replay the OLD `resolve_inventory` — which emitted ours'
    block with same-ID rows swapped and appended theirs-only ROWS, silently dropping every other
    theirs line — and show R0 reports it. Guards against a future 'simplification' of the oracle
    that makes the rule unfalsifiable."""
    def _pre_fix(h):
        rx = re.compile(r"^\|\s*([A-Z]\d+)\s*\|")
        theirs_rows = {rx.match(ln).group(1): ln for ln in h.theirs if rx.match(ln)}
        out, ours_ids = [], set()
        for ln in h.ours:
            m = rx.match(ln)
            if m:
                ours_ids.add(m.group(1))
                out.append(theirs_rows.get(m.group(1), ln))
            else:
                out.append(ln)
        return out + [v for k, v in theirs_rows.items() if k not in ours_ids]

    hunk = next(s for s in classify_file(S_I1).segments if isinstance(s, Hunk))

    class _R:            # the shape `_lost_lines` reads, standing in for a HunkResult
        label, renumbered = "design-inventory-row-merge", {}
        lines = _pre_fix(hunk)

    lost = _lost_lines(hunk, _R)
    assert S_I1_LOST in lost, ("the counterfactual no longer reproduces the drop", lost)


# ---- S-I1: the instance ------------------------------------------------------------------------

def test_s_i1_the_unkeyed_theirs_line_survives_resolve_file():
    """THE S-I1 regression. Pre-fix: RESOLVED, no marker anywhere in the output (so the driver's
    staging guard saw nothing), `verify()` VERIFIED with `dropped: []` — and the sentence gone."""
    status, lines, results = resolve_file(S_I1)
    assert S_I1_LOST in lines, ("the sentence was DROPPED", lines)
    assert status == DEFER, "a hunk the resolver cannot fully represent must not certify as clean"
    assert "\n".join(lines) == S_I1, "the deferral must round-trip byte-for-byte"
    assert all(r.status == DEFER for r in results)


def test_s_i1_the_inventory_arm_no_longer_claims_a_mixed_hunk():
    """The classifier half (known-issue H8): the row-merge arm now carries a purity gate, so a
    hunk mixing a row with foreign content is not a pure inventory merge and never reaches the
    resolver at all."""
    hunk = next(s for s in classify_file(S_I1).segments if isinstance(s, Hunk))
    assert hunk.label == "generic-prose", hunk.label
    assert hunk.label not in MECHANICAL


def test_the_resolver_itself_refuses_rather_than_dropping():
    """The resolver half, stated at the resolver: called DIRECTLY on a hunk it cannot represent,
    `resolve_inventory` RAISES instead of returning a lossy result. Belt and braces: the classifier
    could be wrong again, the resolver cannot.

    Two refusals, two hunks. S-I1's prose line is refused first, by the class re-check at the top
    of `resolve_inventory` (`classify._is_inventory_row_merge`, round 21). A hunk that PASSES the
    class predicate — theirs adds a `|` line that is neither a design-ID row nor ours' table frame —
    reaches the placement check at the end instead, which is the one that stops the drop there."""
    from resolve import resolve_inventory
    prose = Hunk(ours=["| D12 | ours row |"], base=[], theirs=["an unkeyed line of prose"])
    with pytest.raises(CannotPlace, match="not rows of one inventory table on every side"):
        resolve_inventory(prose)
    note = "| note | a non-row table line |"
    h = Hunk(ours=["| D12 | ours row |"], base=[], theirs=["| D12 | ours row |", note],
             line_after="", post_context="", label="design-inventory-row-merge")
    assert classify_hunk(h) == "design-inventory-row-merge"
    with pytest.raises(CannotPlace, match="this line is neither") as exc:
        resolve_inventory(h)
    assert note in str(exc.value)
    assert resolve_hunk(h).code == "cannot-place"


def test_a_theirs_line_already_present_in_the_output_is_not_a_drop():
    """The floor the row-merge licence exists for: both sides of a real inventory conflict carry
    the same table header and `| --- |` delimiter, and ours' copy PLACES theirs'. Without it the
    rule would defer every genuine inventory merge — the fall-closed direction taken too far.

    Round 14 scoped that permission to those two lines specifically (`table_frame_lines`: the
    delimiter row and the header sitting on it), so this test now also pins WHICH lines it covers —
    `test_s_k2_*` pins the other side, that a table-shaped line which is not frame does not get it.
    """
    text = ("<<<<<<< ours\n| Design | Name | Status |\n| --- | --- | --- |\n| D12 | a | BASE |\n"
            "||||||| base\n| D12 | a | BASE |\n=======\n| Design | Name | Status |\n"
            "| --- | --- | --- |\n| D12 | a | THEIRS |\n| D14 | b | y |\n>>>>>>> theirs")
    status, lines, results = resolve_file(text)
    assert status == RESOLVED and results[0].label == "design-inventory-row-merge"
    merged = "\n".join(lines)
    assert "| D14 | b | y |" in merged and "THEIRS" in merged
    assert merged.count("| Design | Name | Status |") == 1


# ---- R3: no mechanical resolution invents a line -----------------------------------------------

def test_r3_no_mechanical_resolution_emits_a_line_it_was_not_given():
    """The corpus-wide form of the check that does not read the licence. Raw multiset containment:
    a resolver may reorder, choose and collapse, but every copy it emits was handed to it.

    What it does NOT cover, said plainly: it bounds the output from above only (a DROP is invisible
    to it — that is R0's job), and `id-renumber-collision` is exempt because rewriting a line's
    text is precisely its licence."""
    invented = [(n, r.label, extra[:2]) for n, h, r in _resolutions(_corpus())
                if r.status == RESOLVED and (extra := overproduced(h, r.label, r.lines))]
    assert not invented, f"a mechanical resolver INVENTED output lines: {invented[:6]}"


def test_r3_catches_the_padded_duplicate_no_licence_key_could_see():
    """Non-vacuity, and the reason R3 exists. The pre-fix inventory resolver answered ours' two
    `| D3 |` rows by emitting THEIRS' row twice — which `_row_key` licensed (two `<row D3>` keys in,
    two out) and the oracle licensed identically, because both read the same table. R3 needs no
    table: theirs' row was handed over once, so a second copy is invented."""
    h = Hunk(ours=["| D3 | Widget A | active |", "| D3 | Widget A | legacy |"], base=[],
             theirs=["| D3 | Widget A | archived |"], label="design-inventory-row-merge")

    class _R:            # the shape `_lost_lines` reads, standing in for a HunkResult
        label, renumbered = "design-inventory-row-merge", {}
        lines = ["| D3 | Widget A | archived |", "| D3 | Widget A | archived |"]

    assert unplaceable(h, h.label, _R.lines) == [], "the licence key genuinely cannot see it"
    assert _lost_lines(h, _R) == [], "...and neither can the oracle"
    assert overproduced(h, h.label, _R.lines) == ["| D3 | Widget A | archived |"]


# ---- R1: a structurally-invalid hunk never resolves mechanically -------------------------------

def test_r1_no_resolved_hunk_ever_contained_a_conflict_marker():
    """A hunk carrying a marker in its sides is the OUTERMOST-wins over-merge of two regions (or
    prose quoting conflict syntax). Merging it would pair the wrong two sides even if it dropped
    nothing, so no mechanical class may claim it."""
    offenders = [(n, r.label) for n, h, r in _resolutions(_corpus())
                 if r.status == RESOLVED and embedded_marker(h) is not None]
    assert not offenders, f"a structurally-invalid hunk resolved mechanically: {offenders[:6]}"


def test_r1_is_not_vacuous_the_corpus_really_contains_such_hunks():
    with_markers = [n for n, h, _r in _resolutions(_corpus()) if embedded_marker(h) is not None]
    assert len(with_markers) >= 400, len(with_markers)   # measured 2026-09-10: 455


def test_r1_a_marker_lookalike_inside_ours_defers_and_survives():
    """S-I2 at the resolver: `======= see example above` is CONTENT of `ours` (the structural
    separator is the one after `|||||||`), and a hunk carrying it defers with the line intact.

    The hunk is a `log-entry-insertion`, a class that may auto-resolve, so the deferral can only
    come from the marker check (`embedded_marker`). Until round 21 it used `### L4:` entries, an
    `id-renumber-collision`, which is GATED since round 20 and deferred before that check ran."""
    text = ("<<<<<<< ours\n- **2026-01-02** — ours\n======= see example above\n||||||| base\n"
            "=======\n- **2026-01-03** — theirs\n>>>>>>> theirs")
    status, lines, results = resolve_file(text)
    assert status == DEFER
    assert [(r.label, r.code) for r in results] == [("log-entry-insertion", "malformed-hunk")]
    assert "embedded conflict marker '======= see example above'" in results[0].reason
    assert "======= see example above" in lines
    assert "\n".join(lines) == text


# ---- R2: the legitimate shapes still resolve ---------------------------------------------------

def test_r2_the_pure_class_fixtures_all_still_auto_resolve():
    """The regression floor for "expect fewer mechanical resolutions": FEWER, not none. Every
    ground-truth fixture of a class that may auto-resolve must still resolve; the fixture of the
    GATED `id-renumber-collision` (round 20) must defer, as that class and for that reason."""
    from conflict_fixtures import ALL_FIXTURES
    resolved = {}
    for name, text in ALL_FIXTURES:
        status, _lines, results = resolve_file(text)
        resolved[name] = (status, [(r.label, r.code) for r in results])
    assert resolved["inventory-row-merge"][0] == RESOLVED, resolved["inventory-row-merge"]
    for name in ("name-keyed-log", "wrapped-dated-log", "append-only-log",
                 "decisions-observed", "decisions-collision", "decisions-nested"):
        assert resolved[name][0] == RESOLVED, (name, resolved[name])
    assert resolved["id-renumber"] == (DEFER, [("id-renumber-collision", "gated")])
    assert resolved["shaped-line-merge"] == (RESOLVED, [("shaped-line-merge", "")])


def test_r2_the_inventory_class_is_still_reachable_end_to_end():
    """The inventory class on its own fixture: rows still merge, theirs' edit of a row ours left
    as base wins (round 17 made that decision base-aware, F3), and nothing defers."""
    status, lines, results = resolve_file(INVENTORY_ROW_MERGE)
    assert status == RESOLVED and results[0].label == "design-inventory-row-merge"
    merged = "\n".join(lines)
    assert "THEIRS" in merged and "| D14 | b | design | y |" in merged
    assert "| D15 | c | design | x |" in merged        # ours-only row kept
