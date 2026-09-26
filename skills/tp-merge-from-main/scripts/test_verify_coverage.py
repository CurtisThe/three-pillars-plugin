"""CONTENT COVERAGE — the half of "atoms() never subtracts" that the superset invariant misses.

`test_verify_superset.py` guards atom EXISTENCE: every atom a markdown-blind scan finds must also
be in `atoms()`. Round 7 found a silent drop that satisfied it anyway, because existence is not
coverage. A signature only fixes the lines it DIGESTS; a line belonging to no atom's body and
matching no per-line kind is an ORPHAN. Delete it and every signature on both sides is unchanged,
`pre - post` is empty, and the file verifies CLEAN. The superset test cannot see this: an orphan is
missing from the naive scan too, so both sides agree and the property holds.

The repro (`atoms()` at round 6, verbatim in `ADVERSARIAL["heading-inside-a-body"]`): a decision
entry whose body quotes a shell script containing a plain `### Section` banner. The block scan
terminated a body at any ATX heading of level <= 3, so the banner closed the entry and every line
after it — a real `REAL_SECRET_LINE=...`, the closing fence, the trailing prose — was orphan.
Deleting the secret line returned VERIFIED with `dropped == []`.

THE INVARIANT, stated so it is checkable without reference to the implementation:

    For any document containing at least one decision-entry atom, deleting any NON-BLANK line at
    or after the first `### [tag] title` heading must yield DROPS_DETECTED.

Everything from the first entry heading to EOF is inside some entry's body (a body now ends only
at the next entry heading), and `_digest` folds the body's non-blank line count, so removing any
such line necessarily moves that entry's signature. Blank lines are excluded deliberately and for
the same reason `_digest` excludes them: a trailing separator blank line appears and disappears
across a merge depending on what follows the entry. Lines BEFORE the first entry are preamble,
which is prose and deliberately not atomic (`verify_atoms.py`'s header).

ONE EXEMPTION REMAINS, and the disappearance of the other is the round-9 strengthening:

  * **Merge-DECORATION lines — GONE as an exemption.** There used to be one, because `atoms()`
    stripped those lines and deleting one was invisible by construction. It was written twice and
    was a silent drop both times: first as "every line matching the marker SHAPE" (a setext H1
    underline of seven `=` and a `|||||||` empty-cell row are ordinary body content — round 8),
    then as "the lines inside a closed conflict region", which paired an OPEN with the first CLOSE
    ANYWHERE later (across entry boundaries) and matched prose that merely quoted conflict syntax
    (round 9). The scanner now strips NOTHING, so no line is exempt on shape or on context: a
    marker line inside an entry's body is content, is covered, and its deletion is reported. Every
    ADVERSARIAL fixture carrying markers is therefore checked line-for-line here.
  * **Lines inside a normalization-DUPLICATED entry.** Two entries with identical `(tag, title,
    body)` are ONE atom, so editing one twin leaves the other holding the original signature. This
    is the accepted normalization-identical residual (`verify_atoms.py`'s header; the resolver's
    no-dedupe keep-both is the mitigation). It is narrow, and
    `test_the_duplicate_entry_exemption_is_narrow` keeps it that way: on this corpus it is ONE
    file — the archived `gc-upstream-gone-is-not-unclean` log, whose two tier-1 entries were
    re-logged verbatim after an M17 `core.bare` repair — 28 lines, of which 18 are genuinely
    undetectable. Nothing else is allowed to be silent.

CAPS. The adversarial half is UNCAPPED. The real-corpus half is capped at 40 covered lines per
file, sampled by a deterministic STRIDE over the whole file rather than taking its head, so the
tail of a long log is examined too. The check is quadratic in file length: uncapped it is 11,019
deletions in ~32 s, which is too slow for every run; the strided cap is 3,527 in ~7 s. The uncapped
run was performed once when this was written and reported ZERO undetectable deletions across the
whole corpus.

WHAT THIS MODULE PINS, AND WHAT IT DOES NOT
===========================================
PINNED. The coverage PROPERTY, over a fixed population: every `ADVERSARIAL` fixture (uncapped) and
every real `decisions.md` in the checkout (strided cap). Within that population, deleting a covered
line is always reported.

NOT PINNED. Anything about the scanner's CONTROL FLOW as such. This is a property over documents,
not a proof over implementations: a change to the block scan that mis-reads some document SHAPE
absent from both the fixtures and the corpus passes here silently. Rounds 7, 8 and 9 were all
exactly that — a control-flow / application-site change touching no regex, found only because
someone wrote down the document that broke it. The two drift tests in
`test_verify_floor.py` do not close this either: they pin regex literals as source text and say
nothing about the loops those regexes are used in.

So the assurance here is exactly as broad as the fixture set. Adding the document that exposes a
defect IS the fix to this boundary; there is no argument in this module that substitutes for it.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_verify_corpus import _corpus  # noqa: E402
from test_verify_floor import _F_DECISION_ENTRY  # noqa: E402
from test_verify_superset import ADVERSARIAL  # noqa: E402
from verify import DROPS_DETECTED, verify  # noqa: E402
from verify_atoms import _norm  # noqa: E402

_CORPUS_CAP = 40


def _opens_an_entry(line):
    m = _F_DECISION_ENTRY.match(line)
    return bool(m and _norm(m.group(1)) and _norm(m.group(2)))


def _blocks(text):
    """[(header, first line index, end index exclusive, body lines)] for each decision entry.

    Mirrors the block rule as a READER would state it — a body runs from its heading to the next
    entry heading or EOF — deliberately without consulting `verify_atoms`'s scanner, so a future
    change to the termination rule shows up as a coverage failure rather than travelling into
    this test.
    """
    raw = text.splitlines()
    out, head, start, body = [], None, None, []
    for i, line in enumerate(raw):
        if _opens_an_entry(line):
            if head is not None:
                out.append((head, start, i, body))
            head, start, body = line, i, []
            continue
        if head is not None:
            body.append(line)
    if head is not None:
        out.append((head, start, len(raw), body))
    return out


def _covered_lines(text):
    """Indices of EVERY non-blank line at or after the first entry heading. No other filter.

    There is no decoration exemption any more — that is the round-9 strengthening. Both versions of
    it (marker SHAPE, then "inside a closed region") were themselves silent drops: they described
    lines the scanner removed, and a removed line is a line whose deletion nothing reports. The
    scanner strips nothing now, so a conflict marker sitting in an entry's body is covered exactly
    like the prose beside it.
    """
    blocks = _blocks(text)
    if not blocks:
        return []
    raw = text.splitlines()
    return [i for i in range(blocks[0][1], len(raw)) if raw[i].strip()]


def _duplicated_entry_lines(text):
    """Line indices belonging to an entry that is normalization-identical to another entry."""
    blocks = _blocks(text)

    def key(head, body):
        m = _F_DECISION_ENTRY.match(head)
        return (_norm(m.group(1)), _norm(m.group(2)), _norm(" ".join(body)),
                sum(1 for ln in body if ln.strip()))

    seen = {}
    for head, _s, _e, body in blocks:
        k = key(head, body)
        seen[k] = seen.get(k, 0) + 1
    out = set()
    for head, s, e, body in blocks:
        if seen[key(head, body)] > 1:
            out.update(range(s, e))
    return out


def _without(text, i):
    lines = text.splitlines(keepends=True)
    return "".join(lines[:i] + lines[i + 1:])


def _sample(indices, cap):
    """A deterministic stride over `indices`, so a cap examines the whole file, not just its head."""
    if cap is None or len(indices) <= cap:
        return indices
    step = len(indices) // cap + 1
    return indices[::step][:cap]


def _undetectable(name, text, cap=None):
    """(checked, [failures]) — covered lines whose deletion does NOT raise DROPS_DETECTED."""
    exempt = _duplicated_entry_lines(text)
    raw = text.splitlines()
    checked, bad = 0, []
    for i in _sample(_covered_lines(text), cap):
        if i in exempt:
            continue
        checked += 1
        r = verify(text, text, _without(text, i), mechanical_applied=True)
        if r.verdict != DROPS_DETECTED:
            bad.append((name, i, raw[i][:70], r.verdict))
    return checked, bad


# ---- the invariant ---------------------------------------------------------------------------

def test_every_covered_line_is_drop_detectable_on_every_adversarial_fixture():
    """UNCAPPED, on the documents the scanner has actually been wrong about. Fails against round 6
    on `heading-inside-a-body`: `REAL_SECRET_LINE=keep-me` and the two lines after the fence were
    orphans, so deleting any of them returned VERIFIED."""
    checked, bad = 0, []
    for name, text in sorted(ADVERSARIAL.items()):
        n, b = _undetectable(f"adversarial:{name}", text)
        checked += n
        bad += b
    assert checked >= 20, f"the adversarial half examined only {checked} lines — it has gone empty"
    assert not bad, (
        "these lines belong to NO signature — deleting them verifies clean, which is the orphan "
        f"class the coverage invariant exists to remove: {bad}")


def test_every_covered_line_is_drop_detectable_across_the_real_corpus():
    """Same property on real bytes, strided-capped (see the module docstring for the numbers).

    A failure here is a genuine finding about a real file, not a fixture artefact: report it,
    do not weaken the assertion.
    """
    corpus = _corpus()
    if not corpus:
        pytest.skip("no real decisions.md in this checkout")
    checked, bad = 0, []
    for p, text in corpus:
        n, b = _undetectable(p, text, cap=_CORPUS_CAP)
        checked += n
        bad += b
    assert checked >= 1000, f"only {checked} corpus lines examined — the corpus read has broken"
    assert not bad, f"these real lines are covered by no signature: {bad[:6]}"


def test_the_coverage_check_is_not_vacuous():
    """A file's covered region must be most of its content. Were `_covered_lines` to return [] —
    a mis-typed regex, a corpus that stopped parsing — both assertions above would pass by
    examining nothing."""
    covered_total = sum(len(_covered_lines(t)) for _p, t in _corpus())
    assert covered_total >= 5000, f"only {covered_total} covered lines across the corpus"
    with_entries = {k: len(_covered_lines(v)) for k, v in ADVERSARIAL.items() if _blocks(v)}
    assert len(with_entries) >= 5, with_entries
    assert all(with_entries.values()), with_entries


def test_the_duplicate_entry_exemption_is_narrow():
    """The one exemption that could swallow the invariant, held to its documented size.

    It is not zero — the corpus really does hold a verbatim re-logged pair — but it must stay a
    rounding error. If a change to the signature starts folding distinct entries together, this
    trips long before the coverage assertions go quietly vacuous.
    """
    corpus = _corpus()
    if not corpus:
        pytest.skip("no real decisions.md in this checkout")
    exempt = {p: len(_duplicated_entry_lines(t)) for p, t in corpus if _duplicated_entry_lines(t)}
    covered_total = sum(len(_covered_lines(t)) for _p, t in corpus)
    assert sum(exempt.values()) < covered_total // 100, (
        f"the duplicate-entry exemption now covers {sum(exempt.values())} of {covered_total} "
        f"lines — the signature is folding distinct entries: {exempt}")
    assert len(exempt) <= 3, f"more files carry duplicated entries than expected: {exempt}"
