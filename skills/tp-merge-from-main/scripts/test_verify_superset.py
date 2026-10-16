"""The GENERAL invariant behind every fence bug rounds 3-6 shipped: `atoms()` NEVER SUBTRACTS.

Three consecutive fixes to the scanner each introduced a fresh silent drop, and the suite caught
none of them, because the suite guarded the two known REPROS rather than the property they were
instances of. Repro tests cannot catch the next instance; this module tests the property.

Two independent formulations here, because they fail on different mistakes (a THIRD — content
COVERAGE, the half neither of these sees — lives in `test_verify_coverage.py`):

  1. **Superset.** For every document, `atoms(text)` must contain everything a deliberately naive,
     markdown-blind scan finds. That scan is `test_verify_floor._naive_atoms`, which lives in its
     own module because its shapes are TYPED OUT rather than imported — a floor that imports the
     regexes of the module it judges moves with them, which is exactly the drift round 7 found
     unimplemented. Any mechanism that lets the scanner conclude "this line is not structure"
     fails here the moment it concludes it about a line that is. All three shipped bugs fail this.

  2. **Deletion detectability.** For every atom-shaped line in a document, removing that line from
     the merged text must produce `DROPS_DETECTED`. This is the property callers actually depend
     on, stated without reference to the implementation: if a line that looks like content is not
     in `pre`, its deletion is invisible. It catches under-counting the superset test would miss —
     e.g. a scan that emits an atom but with a signature insensitive to the line's removal.

Both run over the REAL corpus **plus** `ADVERSARIAL`, and the adversarial half is the point: the
real corpus contains ZERO files with a fenced conflict-marker example, so a corpus-only property
test would have passed on all three broken scanners. Each fixture below is a document some version
of this module mis-read, or a near-miss of one.

`ADVERSARIAL` is the shared fixture set: `test_verify_coverage.py` reads it from here so the three
invariants are all judged on the same documents.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_verify_corpus import _corpus  # noqa: E402
from test_verify_floor import (  # noqa: E402
    _F_DECISION_ENTRY, _F_ENTRY, _F_LOG, _F_ROW, _naive_atoms,
)
from verify import DROPS_DETECTED, atoms, verify  # noqa: E402
# Only `_norm` comes from the module under test — the signature CONVENTION, not a shape. Every
# shape matched here is one of the independent `_F_*` floor literals. `CONFLICT_MARKER` used to be
# imported for a test that pinned the marker strip's safety; there is no strip any more (round 9),
# so both the regex and that test are gone.
from verify_atoms import _norm  # noqa: E402
from pathlib import Path  # noqa: E402

_DEV_ROOT = Path(__file__).resolve().parents[3]
# The real decisions.md corpus lives in the dev repo's three-pillars-docs/ (dev-repo
# only); in a plugin install only the adversarial fixtures run, and the corpus-size
# floors below apply only where the corpus exists.
_HAS_DEV_DOCS = (_DEV_ROOT / "three-pillars-docs").exists()

# ---- The adversarial corpus -------------------------------------------------------------------
# Ordinary markdown that a fence-aware or zone-aware scanner reads wrongly. Named after the defect
# each one triggers; the first three are the reported repros, verbatim.
ADVERSARIAL = {
    # Round 6 (S-C1): a stray unclosed fence, then an unrelated code block. NO conflict markers.
    # `origin/master` caught a deletion of `### L1:` here; the zone-aware scanner returned
    # VERIFIED on it.
    "stray-unclosed-fence": (
        "### L0: before\n\n```\n### L1: real atom ONE\n\n```\nreal code here\n```\n\n"
        "### L2: real atom two\n"
    ),
    # Round 4 (E1): an unclosed opener on ours' side of a conflict, a real row on theirs'.
    "fence-across-a-conflict-seam": (
        "# Doc\n\n<<<<<<< ours\n```python\nsome code\n=======\n| D3 | a real row |\n```\n"
        ">>>>>>> theirs\n"
    ),
    # Round 5 (S-B1): a doc that QUOTES conflict syntax inside a fence, then real entries.
    "fenced-conflict-marker-example": (
        "```\nExample of a conflict:\n<<<<<<< HEAD\nfoo\n=======\nbar\n>>>>>>> branch\n```\n"
        "### L1: Real Entry\nsome text\n```\ncode\n```\n### L2: Another Entry\n"
    ),
    # A conflict-marker SHAPE with no conflict behind it — the "fake region in prose" a
    # marker-shape-matching zone splitter cannot tell from a real one. This repo's own SKILL.md
    # and decisions.md files are full of these.
    "fake-region-in-prose": (
        "<<<<<<< not-a-real-conflict\n### L10: inside the fake region\n=======\n"
        "### L11: other side\n>>>>>>> nope\n"
    ),
    # A setext H1 underline of exactly seven `=`. It matched the old unconditional strip; under
    # the region rule it is content (no `<<<<<<<` opens a region here) and survives into the scan.
    "stray-separator": "Title\n=======\n### L4: after the stray\n| D2 | row after |\n",
    "nested-fences": "````\n```\n### L5: nested\n```\n````\n### L6: outside\n",
    "tilde-vs-backtick": "```\n~~~\n### L7: tilde inside\n```\n### L8: after\n",
    "markers-inside-a-fence": (
        "```\n### [x] fenced entry\n<<<<<<< a\n=======\n>>>>>>> b\n```\n### L9: real\n"
    ),
    "fenced-example-of-every-kind": (
        "### L4: Real entry\n```markdown\n### L9: Example entry\n| D3 | example row |\n"
        "- **2024-01-01** — example log\n```\n"
    ),
    "decision-entries-around-a-fence": (
        "### [tp-plan] first\nbody one\n```\n### [tp-plan] fenced example\nnot really\n```\n"
        "### [tp-plan] second\nbody two\n"
    ),
    "unclosed-fence-then-decision-entries": (
        "### [a] one\nbody\n```\n### [b] two\nmore\n#### Sub\ntail\n"
    ),
    # Round 7 (S-D1): a plain `### Section` banner inside a fenced shell script quoted in an
    # entry's BODY. Under the `#{1,3}` terminator it closed the block, so `REAL_SECRET_LINE` and
    # everything after the fence belonged to no atom — deleting a line there verified clean while
    # the superset invariant still passed, because an orphan is missing from BOTH scans.
    "heading-inside-a-body": (
        "### [tp-plan] a decision\n**Reasoning**: see the script below\n"
        "```bash\n### Section banner\nREAL_SECRET_LINE=keep-me\n```\n"
        "tail content that matters\n### [tp-plan] the next decision\nbody two\n"
    ),
    # Round 8 (S-E1): real body content SHAPED like a conflict marker, with no conflict anywhere.
    # `=======` is a setext H1 underline and `|||||||` a table row of empty cells; the
    # unconditional strip deleted both before `atoms()` saw them, so deleting either from the body
    # returned VERIFIED while deleting an ordinary body line returned DROPS_DETECTED. They are
    # decoration only INSIDE a closed `<<<<<<< ... >>>>>>>` region, and there is none here.
    "setext-underline-as-body-content": (
        "### [tp-plan] a decision\n**Reasoning**: the heading below is setext\n"
        "Section Title\n=======\nreal content under the rule\n"
        "### [tp-plan] the next decision\nbody two\n"
    ),
    "empty-cell-row-as-body-content": (
        "### [tp-plan] a decision\n| head | head |\n| --- | --- |\n|||||||\n"
        "real content after the row\n### [tp-plan] the next decision\nbody two\n"
    ),
    # A conflict region that never closes — malformed. Nothing is stripped anywhere any more, so
    # its `=======` is content and stays covered by the entry's digest, as does every other line.
    "unterminated-conflict-region": (
        "### [tp-plan] a decision\n<<<<<<< ours\nours side content\n=======\n"
        "theirs side content\ntail with no closing marker\n"
    ),
    # Round 9 (S-F1a): CROSS-ENTRY PAIRING. The region rule paired an OPEN with the first CLOSE
    # ANYWHERE later, so the unterminated `<<<<<<<` under `d1` and the unrelated `>>>>>>>` under
    # `d3` bracketed a `=======` that lives in a THIRD entry's body. Deleting that line left
    # `atoms()` byte-identical and returned VERIFIED — a silent drop across an entry boundary.
    "conflict-brackets-spanning-entries": (
        "### [tp-plan] d1\n<<<<<<< ours\nsome ours text\n"
        "### [tp-plan] d2\nbody two\n=======\ntail content\n"
        "### [tp-plan] d3\nbody three\n>>>>>>> theirs\n"
    ),
    # Round 9 (S-F1b): COINCIDENTAL BRACKETS. Prose that merely ILLUSTRATES conflict syntax is
    # byte-identical to a real region, and this repo's SKILL.md / decisions.md are full of it. The
    # region rule therefore called the setext underline between these two lines decoration and
    # deleting it verified clean, while deleting the ordinary line beside it did not.
    "coincidental-conflict-brackets-in-prose": (
        "### [tp-plan] a decision\n<<<<<<< see below for an example\nSome Section\n"
        "=======\n>>>>>>> end example\nreal tail that matters\n"
    ),
    # The same shape without a fence anywhere: a `## Section` between two entries. Its lines are
    # now body of the entry ABOVE it rather than orphans.
    "section-heading-between-entries": (
        "### [a] one\nbody one\n\n## Interlude\nprose that must be covered\n\n"
        "### [b] two\nbody two\n"
    ),
}


def _documents():
    """The adversarial fixtures + every real `decisions.md` in the checkout."""
    docs = [(f"adversarial:{k}", v) for k, v in sorted(ADVERSARIAL.items())]
    docs += [(p, t) for p, t in _corpus()]
    return docs


# ---- 1. the superset invariant ---------------------------------------------------------------

def test_atoms_is_a_superset_of_a_markdown_blind_scan():
    """THE invariant. Not "the E1 document parses correctly" — for EVERY document, no atom the
    naive scan finds may be missing from `atoms()`.

    Fails against rounds 3, 4 and 5: each masked a real `### L<n>:` or `| D<n> |` line out of the
    inventory on at least one fixture below, and an atom absent from `pre` makes its own deletion
    invisible. Extra atoms are fine and expected — that direction only ever reports MORE drops.
    """
    docs = _documents()
    if _HAS_DEV_DOCS:
        assert len(docs) >= len(ADVERSARIAL) + 50, f"corpus did not load ({len(docs)} docs)"
    missing = []
    for name, text in docs:
        lost = _naive_atoms(text) - set(atoms(text))
        if lost:
            missing.append((name, sorted(lost)[:4]))
    assert not missing, (
        "atoms() SUBTRACTED — these atoms are visible to a markdown-blind scan but absent from "
        f"the inventory, so dropping them would verify clean: {missing[:6]}")


def test_the_superset_test_is_not_vacuous():
    """A floor under the floor: `_naive_atoms` must actually find things, or the assertion above
    passes by finding nothing to lose."""
    total = sum(len(_naive_atoms(t)) for _n, t in _documents())
    if _HAS_DEV_DOCS:
        assert total >= 1000, f"the naive scan found only {total} atoms — it has broken, not passed"
    per_fixture = {k: len(_naive_atoms(v)) for k, v in ADVERSARIAL.items()}
    assert all(per_fixture.values()), f"an adversarial fixture yields no atoms: {per_fixture}"


def test_every_adversarial_fixture_is_at_least_as_good_as_origin_master():
    """The A/B stated as a test. `origin/master` had no fence machinery at all and caught the
    round-6 drop this branch passed; nothing here may see less than it does."""
    for name, text in sorted(ADVERSARIAL.items()):
        got = set(atoms(text))
        for kind, sig in _naive_atoms(text):
            if kind != "decision-entry":                    # master's three kinds
                assert (kind, sig) in got, (name, kind, sig, sorted(got))


# ---- 2. deletion detectability ---------------------------------------------------------------

def _atom_shaped_lines(text):
    """Indices of lines that LOOK like content to a reader — the lines whose loss must be
    reportable. Deliberately shape-only: no context, no fence state, nothing the scanner could
    also get wrong in the same way.

    The marker-shape skip that used to head this loop is gone with the strip (round 9). It was
    provably redundant even before — no line of seven `<`/`>`/`=`/`|` can match `### `, `- **` or
    `| <L><n> |` — but "provably redundant" is exactly what every exemption in this suite claimed
    right up until it hid a line, so it is now simply absent.
    """
    hits = []
    for i, line in enumerate(text.splitlines()):
        for rx in (_F_ENTRY, _F_ROW, _F_LOG, _F_DECISION_ENTRY):
            m = rx.match(line)
            if m and _norm(m.group(1)):
                hits.append(i)
                break
    return hits


def _without(text, i):
    lines = text.splitlines(keepends=True)
    return "".join(lines[:i] + lines[i + 1:])


def _undetectable(name, text, limit=None):
    """Every atom-shaped line whose deletion does NOT raise DROPS_DETECTED.

    A normalization-identical duplicate line is exempt and only that: the surviving twin keeps the
    atom alive, which is `verify_atoms.py`'s documented, accepted residual (the resolver's
    no-dedupe keep-both is the mitigation). Nothing else is allowed to be silent.
    """
    raw = text.splitlines()
    counts = {}
    for ln in raw:
        counts[_norm(ln)] = counts.get(_norm(ln), 0) + 1
    bad = []
    for i in _atom_shaped_lines(text)[:limit]:
        if counts[_norm(raw[i])] > 1:
            continue                                        # accepted normalization residual
        r = verify(text, text, _without(text, i), base=None, mechanical_applied=True)
        if r.verdict != DROPS_DETECTED:
            bad.append((name, i, raw[i][:60], r.verdict))
    return bad


def test_deleting_any_atom_shaped_line_is_reported_on_every_adversarial_fixture():
    """The sharp form of the invariant: an atom in `pre` is always drop-detectable. Fails on all
    three shipped bugs — each hid a line here whose deletion then verified clean."""
    bad = []
    for name, text in sorted(ADVERSARIAL.items()):
        bad += _undetectable(f"adversarial:{name}", text)
    assert not bad, f"deleting these lines was NOT reported as a drop: {bad}"


def test_deleting_any_atom_shaped_line_is_reported_across_the_real_corpus():
    """Same property on real bytes. Capped at the first 40 shaped lines per file: the check is
    quadratic in file length and the corpus is large, and a defect of this class is never confined
    to line 41 of one file — the adversarial half above is where the shapes are dense."""
    corpus = _corpus()
    if not corpus:
        pytest.skip("no real decisions.md in this checkout")
    bad = []
    for p, text in corpus:
        bad += _undetectable(p, text, limit=40)
    assert not bad, f"deleting these real lines was NOT reported as a drop: {bad[:6]}"


# ---- There is no remaining subtraction. Pinned as a property over documents -------------------

def test_atoms_removes_no_line_at_all():
    """The round-9 invariant, stated the only way it can no longer be gamed: for EVERY document,
    every non-blank line at or after the first decision entry is inside some body, so deleting any
    one of them moves a signature.

    This replaces `test_no_conflict_marker_shape_can_also_be_an_atom_shape`, which pinned the
    marker strip's safety with a fact about regexes ("a marker line cannot BE an atom"). That fact
    was true and the strip was unsafe anyway, three formulations running, because it protected the
    wrong thing: an atom can survive while the digest that would report its body's mutilation does
    not. Marker lines are the sharpest case and are checked explicitly here; the general form lives
    in `test_verify_coverage.py`, which now runs with no decoration exemption at all.
    """
    markers = ["<<<<<<< ours", "||||||| base", "=======", ">>>>>>> theirs", "|||||||",
               "<<<<<<<", ">>>>>>>"]
    for marker in markers:
        text = f"### [tp-plan] a decision\nbody line\n{marker}\ntail line\n"
        assert atoms(text) != atoms(f"### [tp-plan] a decision\nbody line\ntail line\n"), marker
        without = "".join(ln for ln in text.splitlines(keepends=True)
                          if ln.rstrip("\n") != marker)
        r = verify(text, text, without, base=None, mechanical_applied=True)
        assert r.verdict == DROPS_DETECTED, (marker, r.verdict)
