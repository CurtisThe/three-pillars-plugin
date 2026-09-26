"""The cold-resume contract is stated in TWO SKILL.md files — pin that they AGREE.

`tp-pr-iterate/SKILL.md` §Cold-resume contract and `tp-run-full-design/SKILL.md`'s
Tier-7 `run_round.py` bullet describe the same seam for two different readers. Twin-file
drift is the real risk: the last time this contract was corrected, one twin was fixed
and the other kept asserting the opposite, and the suite stayed green.

So each fact below must be asserted in BOTH files. Editing one twin's claim without the
other fails here, which is the failure that actually matters.

**What this deliberately gives up** (corrected in round 13 — the round-12 disclosure
named only the first of these). It replaces ~900 lines of byte-equality pins
(`test_pr_iterate_state_contract_doc.py`, `test_cold_resume_state_prose.py`,
`test_cold_resume_state_seam.py`), and with them:

1. **Inversion that carries the old phrasing along.** Appending "*Superseded: the state
   IS committed*" leaves every phrase below intact and passes — and so does the sharper
   form a reviewer demonstrated in round 14: rewrite both twins' resume claims
   destructively **in place** while keeping the three enumerated phrases inside a
   "*the superseded note said…*" clause that disowns them. Re-measured in round 14
   against THIS module as it now stands, region scoping included: **15 passed, 0
   failed** — the break survives. Still given up, on purpose (operator-approved,
   logged at Medium confidence in `decisions.md`). A fact list cannot tell a phrase
   that is ASSERTED from one that is QUOTED in order to be repudiated.
2. **Whole-region integrity.** Equality caught ANY edit to the pinned prose; a fact list
   only catches the loss of a phrase someone thought to enumerate. Still given up.

What round 13 put BACK, because the round-12 disclosure did not mention it and it was
not a byte-equality property at all: **direction**. Destructive *in-place* inversion —
rewriting the claim to "the state file is committed each round, so a fresh clone resumes
cold" — passed all eight original facts (measured: 98 passed), because the resume fact
matched the bare token `gitignored`, which has decoy occurrences on the same line. The
fix is not equality; it is a handful of facts whose regexes carry the NEGATION
("no code path commits", "not cross-clone"), plus a pin on the second, unguarded
persistence site.

**Exactly what that buys, stated no higher than the mutations support**: a **deletion**
of one of those phrases fails here, and so does an **inversion that does not carry the
old phrasing along** — the naive rewrite that simply states the opposite. Measured in
round 14: deleting a phrase → **3 failed**; a naive in-place inversion → **3 failed**;
stripping the persistence line → **1 failed**. What it does NOT buy is immunity to
inversion as such; see give-up 1 above. The earlier wording of this docstring — "an
inversion now has to delete a phrase to survive" — was false, and contradicted give-up 1
in this same docstring and the Medium-confidence residual in `decisions.md`. Stating a
guard's strength above its measurements is the exact defect this module exists to catch
in the prose it pins, so it is not tolerable here either.

Each fact is matched against the **section that makes the claim**, not the whole file
(see :func:`_section`), so the phrases cannot be satisfied from an unrelated historical
note elsewhere in the document. Measured: gutting the claim and re-homing the identical
sentence under a trailing "## Historical note" heading was **green** against the whole
file and is **3 failed** scoped. That narrows the surface — 37k chars of `tp-pr-iterate`
to 6.1k, 117k of `tp-run-full-design` to 6.5k (re-measured at this commit; round 14 quoted
5.9k, which was the region's size at that commit's PARENT). Round 15 then closed the two
single-edit ways back OUT of the region — a DUPLICATE opening heading and a DEMOTED
terminator, each measured **15 passed** before and **15 errors** after (errors, because
the region fixture is module-scoped: a broken bound invalidates every fact below it, not
one of them). Both are asserted in :func:`_section`, which explains them. None of this
closes give-up 1: a disowning clause sits inside the region as happily as outside it.

This is the cheap half that catches the common failures, not the whole of it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_SKILLS = Path(__file__).resolve().parent.parent.parent
PR_ITERATE_MD = _SKILLS / "tp-pr-iterate" / "SKILL.md"
RUN_FULL_DESIGN_MD = _SKILLS / "tp-run-full-design" / "SKILL.md"

# (fact name, regex over the whitespace-normalised file). Each must hold in BOTH twins.
_SHARED_FACTS = (
    (
        "absent state is the start condition, not an error",
        r"absent state file is the documented\s+\*{0,2}start condition\*{0,2}",
    ),
    (
        "the round-0 seed is reported in the envelope",
        r"state_bootstrapped:?\s*`?\s*true",
    ),
    # `state-read-failed`'s refusal set, pinned by SUBSTANCE rather than by the bare
    # token. The token alone was worthless: it occurs in both files no matter what they
    # claim ABOUT it, so the round-12 correction ("exists with content" is false in both
    # directions — a FIFO/socket/directory/`/dev/null` exists with no content and still
    # exits 2; a dangling symlink exits 2 with `Path.exists()` False) landed on ONE twin
    # and this test stayed green. Each member of the set is its own fact.
    (
        "state-read-failed covers content that is not a JSON object",
        r"not a JSON object",
    ),
    (
        "state-read-failed covers a dangling symlink (exists() is False)",
        r"dangling symlink",
    ),
    (
        "state-read-failed covers a non-regular node (FIFO/socket/directory)",
        r"non-regular\*{0,2}\s+node",
    ),
    (
        "'exists with content' is NOT the test — the false framing must stay corrected",
        r"exists?\*{0,2} with\*{0,2} .{0,10}content.{0,40}wrong test"
        r"|wrong test in both directions",
    ),
    (
        "a zero-length state file counts as absent and is re-seeded",
        r"zero-length.{0,120}?re-seeded",
    ),
    (
        "serial callers only; parallel loops need their own state_path",
        r"[Ss]erial callers only|serial\*{0,2} caller",
    ),
    (
        "iteration is NOT what a racing re-seed loses",
        r"[Nn]ot\*{0,2}\s+`iteration`|`iteration`[^.]{0,80}increments it",
    ),
    # The resume claim, pinned by DIRECTION-BEARING phrases rather than by `gitignored`.
    # `gitignored` was a decoy: it occurs three times on the same line (the
    # `review_proof_root` gloss and the persistence line among them), so the claim could
    # be rewritten to its OPPOSITE in place — "the state file is committed each round, so
    # a fresh clone resumes cold" — or deleted outright from `tp-run-full-design`, and the
    # fact stayed green (measured, round 13). Each phrase below carries the NEGATION that
    # makes the claim mean something, so the naive in-place inversion — which just states
    # the opposite — loses all three and fails. An inversion that QUOTES the old phrasing
    # in order to disown it keeps them and passes; that residual is give-up 1 above.
    (
        "nothing commits the state — the negation is the whole claim",
        r"no code path commits",
    ),
    (
        "resume is in-worktree only, NOT cross-clone / not a fresh clone",
        r"not\*{0,2},?\s+\*{0,2}(a\s+\*{0,2})?(cross-clone|fresh clone)",
    ),
    (
        "a committed per-round state is INTENDED, not something any code performs",
        r"intended\*{0,2},?\s*contract,?\s*\*{0,2}not\*{0,2}\s+one any current code",
    ),
)


# The heading that opens each twin's cold-resume claim, and the heading expected to CLOSE
# it. Every fact above is asserted INSIDE this section in both files (verified), so the
# facts are scoped to it rather than to the whole document. BOTH bounds are checked — see
# :func:`_section` for why pinning only the opening one leaves the region movable.
_SECTION_HEADINGS = {
    "tp-pr-iterate/SKILL.md": "### Cold-resume contract",
    "tp-run-full-design/SKILL.md": "### Step 1 — Orchestrator-owned round loop",
}
_SECTION_TERMINATORS = {
    "tp-pr-iterate/SKILL.md": "### Termination matrix",
    "tp-run-full-design/SKILL.md": "### Step 2 — Clip + log",
}


def _normalised(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def _section(text: str, heading: str, terminator: str) -> str:
    """`heading` up to the next markdown heading of the same or a higher level.

    Scoping matters because :data:`_SHARED_FACTS` is a phrase search: against the WHOLE
    file, a saboteur can gut the claim and still satisfy every fact from a "historical
    note" pasted anywhere else in the document — an appendix, a changelog, a failure-mode
    list. Requiring the phrase where the claim is MADE removes that.

    A region has THREE ways to stop meaning what it says; each needs its own check.

    1. **Opening heading GONE** (renamed, deleted) — `find` returns -1 and every fact is
       scoped to the whole file again. Asserted directly.
    2. **Opening heading AMBIGUOUS.** `find` is a first-wins PREFIX match, so pasting the
       section above the live one under `### Cold-resume contract (historical —
       superseded)` and gutting the real one satisfies every fact from the dead copy —
       not an exotic attack, just the ordinary "supersede in place, keep the old marked
       historical" edit. Asserted by requiring the heading to occur exactly ONCE.
    3. **End bound MOVED.** The end is COMPUTED from the next heading rather than named,
       which is right for INSERTION (a subsection added between the two shrinks the
       region honestly instead of widening it) and backwards for REMOVAL: a NAMED bound
       fails loudly when its name vanishes, while a computed one silently absorbs the
       following section when the terminator is DEMOTED to bold — enough to pull an
       outside note into scope. So the bound is computed AND checked against the
       terminator it should be. Deliberate cost: legitimately inserting a heading between
       the two fails here too; retarget `_SECTION_TERMINATORS` in that same commit.
    """
    begin = text.find(heading)
    assert begin != -1, (
        f"the section heading {heading!r} is gone. The cold-resume facts are scoped to "
        f"this section; renaming or deleting it un-scopes every fact below, so retarget "
        f"_SECTION_HEADINGS in the same commit that moves the prose."
    )
    assert text.count(heading) == 1, (
        f"the section heading {heading!r} occurs {text.count(heading)} times — it is a "
        f"PREFIX match, so a qualified variant ('… (historical — superseded)') counts. "
        f"The facts below would be satisfied from whichever copy comes FIRST, which is "
        f"how a superseded duplicate keeps this module green while the live claim says "
        f"the opposite. Keep exactly one, or retarget _SECTION_HEADINGS."
    )
    after = text[begin + len(heading):]
    # The lookbehind keeps a level-4 subheading (`#### …`) INSIDE the region: without it
    # the `### ` inside `#### ` matches one character in and the region ends early.
    end = re.search(r"(?<!#)#{1,3} ", after)
    assert end is not None and after[end.start():].startswith(terminator), (
        f"the section after {heading!r} no longer ends at {terminator!r} — it now ends "
        f"at {(after[end.start():end.start() + 60] if end else '<end of file>')!r}. "
        f"The end bound is computed, so DEMOTING the terminator (to bold, say) silently "
        f"widens this region into the next section and lets an outside note satisfy the "
        f"facts. If the move was intentional, retarget _SECTION_TERMINATORS in the same "
        f"commit."
    )
    return after[: end.start()]


def _functions(src: str) -> dict:
    """Map top-level function name -> its body text. Enough for a call-graph scan."""
    bounds = [(m.group(1), m.start()) for m in re.finditer(r"^def (\w+)\(", src, re.M)]
    return {
        name: src[start:(bounds[i + 1][1] if i + 1 < len(bounds) else len(src))]
        for i, (name, start) in enumerate(bounds)
    }


@pytest.fixture(scope="module")
def twins() -> dict:
    """Each twin's cold-resume SECTION — not the whole file. See :func:`_section`."""
    return {
        name: _section(_normalised(path), _SECTION_HEADINGS[name],
                       _SECTION_TERMINATORS[name])
        for name, path in (("tp-pr-iterate/SKILL.md", PR_ITERATE_MD),
                           ("tp-run-full-design/SKILL.md", RUN_FULL_DESIGN_MD))
    }


@pytest.mark.parametrize("fact,pattern", _SHARED_FACTS, ids=[f[0] for f in _SHARED_FACTS])
def test_both_skill_files_state_the_same_cold_resume_fact(fact, pattern, twins):
    """A cold-resume fact stated in one twin must be stated in the other."""
    missing = [name for name, text in twins.items()
               if not re.search(pattern, text)]
    assert not missing, (
        f"cold-resume contract drift: {fact!r} is missing from {missing}.\n"
        f"Both SKILL.md files describe the same seam — correct BOTH twins or neither, "
        f"or a reader of the un-corrected one acts on a claim that is no longer true."
    )


def test_the_persistence_line_states_the_in_worktree_limit(twins):
    """The Tier-7 trailing persistence line, pinned on its own site.

    `tp-run-full-design/SKILL.md` states the resume claim TWICE — once in the
    `run_round.py` stdin bullet and once in the "State is persisted by `run_round.py`
    each round" line that closes the section. The second site is the one a skimming
    reader reaches, and it is the one that went unguarded: silence about the
    in-worktree limit here lets a reader conclude that a fresh clone resumes.
    """
    text = twins["tp-run-full-design/SKILL.md"]
    opening = "State is persisted by `run_round.py` each round"
    assert text.count(opening) == 1, (
        f"expected exactly one persistence line opening with {opening!r}; found "
        f"{text.count(opening)}. Deleting the site from this pin's reach is how the "
        "claim went unguarded in the first place."
    )
    line = text[text.index(opening):][:400]
    for phrase in ("in-worktree", "gitignored"):
        assert phrase in line, (
            f"the persistence line no longer says {phrase!r}: {line[:220]!r}\n"
            "State is resumable only INSIDE a live worktree — the path is gitignored "
            "and no code path commits it. Stating persistence without that limit is "
            "the false claim this pin exists to catch."
        )


# The UNCAPPED pin, INVERTED (Task 4.2): `run_loop` is deleted and `run_round` calls
# `round_budget.tick` every round, so both twins must document the cap (prose: Phase 8).
@pytest.mark.parametrize("name", ["tp-pr-iterate/SKILL.md", "tp-run-full-design/SKILL.md"])
def test_both_twins_document_the_round_budget_cap(name, twins):
    """Each twin's section names the cap (`round_budget.tick` / `budget-exhausted`) and
    no longer claims the shelled path is UNCAPPED or that the caps live in `run_loop`."""
    text = twins[name]
    assert re.search(r"round_budget\.tick|budget-exhausted", text), (
        f"{name}: the cold-resume section must document the round-budget cap")
    stale = [tok for tok in ("UNCAPPED", "run_loop", "_check_guards") if tok in text]
    assert not stale, f"{name}: the section still carries the retired claim {stale}"


def test_the_cap_claim_matches_the_code_it_describes():
    """The cap the twins must document is real: `run_round` calls `round_budget.tick`,
    and the old guard path (`_check_guards` / `_apply_guards` / `run_loop`) is gone, so
    no second, divergent cap implementation can hide behind a helper."""
    src = (Path(__file__).resolve().parent / "loop_driver.py").read_text(encoding="utf-8")
    fns = _functions(src)
    assert ".tick(" in fns["run_round"], "loop_driver.run_round no longer calls tick"
    leftover = sorted({"_check_guards", "_apply_guards", "run_loop"} & set(fns))
    assert not leftover, f"the retired guard path is back: {leftover}"
