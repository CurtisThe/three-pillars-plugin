"""Corpus regression: the REAL `decisions.md` files in this repo, not synthetic fixtures.

`conflict_fixtures.py` covers every `AUTO_RESOLVE` class with hand-written shapes, but nothing
exercised an on-disk `decisions.md`. That gap mattered, because the corpus is NOT uniform: 10 of
the repo's 102 real files carry the bare pre-`###` shape (`[slug/phase-N] title — operator, date`)
and parse to ZERO `decision-entry` atoms. All 10 live under `completed-tp-designs/`, which
`_DESIGN_DECISIONS_RE` excludes from the mechanical lane, so live exposure is nil — but that was
an unpinned coincidence, and it is exactly the coincidence the whole design rests on.

The assertions here are complementary and none pins a COUNT (the corpus grows):

  1. every corpus file RE-PATHED onto the mechanical lane yields >= 1 atom if it parses, and the
     bare-shape minority verdicts `UNVERIFIABLE` — so an in-flight design whose log drifts to an
     unparseable shape fails HERE, at commit time, rather than silently at merge time;
  2. every zero-atom file is OFF the mechanical lane — so the drifted shape cannot migrate onto
     the lane without a failing test;
  3. the decision-entry signature is INJECTIVE on the corpus — entries with distinct CONTENT
     get distinct atoms (normalization-identical duplicates are ONE entry, per the design's
     accepted residual).

Assertion 1 used to filter the corpus by `is_auto_safe_path` and skip when the result was empty.
That made it vacuous BY CONSTRUCTION, not just on an unlucky checkout: a design's `decisions.md`
is archived to `completed-tp-designs/` at completion, and the lane pattern excludes that directory,
so a clean checkout has ZERO on-lane files FOREVER (measured: 0 of 102). It now re-paths the real
corpus onto the lane instead, so both `is_auto_safe_path` and `atoms()` run on real bytes every
time, under non-vacuity floors.

Assertion 3 is the load-bearing one for the whole design: a signature COLLISION folds two entries
onto one atom, so dropping one of the pair leaves the inventory unchanged and verifies clean —
precisely the silent pass this design removed. It was previously stated only as a measured fact in
`verify_atoms.py`'s header, asserted nowhere.

`test_corpus_is_actually_present` pins that the corpus is actually being read, so a glob that
silently matches nothing cannot make the whole module pass by default.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "_shared")))
from auto_safe_resolution import is_auto_safe_path  # noqa: E402
from verify import UNVERIFIABLE, atoms, verify  # noqa: E402
from verify_atoms import DECISION_ENTRY, _norm  # noqa: E402

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_DOCS = os.path.join(_REPO_ROOT, "three-pillars-docs")


def _corpus():
    """[(repo-relative path, text)] for every real `decisions.md` under `three-pillars-docs/`."""
    out = []
    for dirpath, _dirnames, filenames in os.walk(_DOCS):
        if "decisions.md" not in filenames:
            continue
        abs_p = os.path.join(dirpath, "decisions.md")
        rel = os.path.relpath(abs_p, _REPO_ROOT).replace(os.sep, "/")
        with open(abs_p, encoding="utf-8") as fh:
            out.append((rel, fh.read()))
    return sorted(out)


def _decision_atoms(text):
    return [k for k in atoms(text) if k[0] == "decision-entry"]


def _admissible_entries(text):
    """The normalized CONTENT of every `### [tag] title` block `atoms()` will admit, as
    `(tag, title, non-blank body lines, body text)` — the numerator of the injectivity check below.

    Deliberately stops at CONTENT: it re-walks the scanner's block scan — a body runs to the next
    `### [tag] title` heading or EOF and NOTHING else closes it, which is not what injectivity is
    about — and reproduces the three fields the signature is built FROM, but performs no field
    escaping and no hashing.
    Those two steps — `_esc` and `_digest` — are the map under test, so what is asserted is that
    THEY are injective on the corpus, not that the block scan is correct.

    There is no fence handling here, and no marker strip either, because there is neither in
    `atoms()`: both were SUBTRACTIONS from what a signature covers and both are gone (see
    `verify_atoms.py`'s header). A fenced `### [tag] title` example is an admissible entry on BOTH
    sides of this equality, and a conflict marker is an ordinary body line on both.

    The caller compares these as a SET: normalization-identical entries are one element. That
    exclusion is the design's accepted residual, not an oversight — see the docstring below.
    """
    lines = text.splitlines()
    entries = []
    open_block, body = None, []

    def _close():
        if open_block is not None:
            tag, title = open_block
            entries.append(
                (tag, title, sum(1 for ln in body if ln.strip()), _norm(" ".join(body))))

    for line in lines:
        m = DECISION_ENTRY.match(line)
        if m and _norm(m.group(1)) and _norm(m.group(2)):
            _close()
            open_block, body = (_norm(m.group(1)), _norm(m.group(2))), []
            continue
        # No heading terminator of any level: `#### Sub` AND a plain `### Section` are both body.
        if open_block is not None:
            body.append(line)
    _close()
    return entries


def test_corpus_is_actually_present():
    """Guard against a vacuous module: if the glob stops finding files, say so loudly."""
    corpus = _corpus()
    if not corpus:
        pytest.skip("no real decisions.md in this checkout")
    assert len(corpus) >= 50, f"corpus unexpectedly small ({len(corpus)}) — glob may have drifted"


def _lane_path(rel):
    """Re-path a corpus file onto the mechanical lane, content untouched.

    `is_auto_safe_path` admits exactly `three-pillars-docs/tp-designs/<slug>/decisions.md`, and a
    design's `decisions.md` is ARCHIVED to `completed-tp-designs/` at completion — so a clean
    checkout has ZERO on-lane files, permanently. Filtering the corpus by `is_auto_safe_path` and
    skipping when empty was therefore vacuous BY CONSTRUCTION, not merely on this checkout.

    `/` -> `~` gives exactly ONE path segment (the regex's `[^/\\n]+`) that is never `.` or `..`,
    so the whole corpus lands on the lane and the assertions below run on real bytes every time.
    """
    return "three-pillars-docs/tp-designs/{}/decisions.md".format(rel.replace("/", "~"))


# Non-vacuity floors. The corpus only grows (archived designs are never deleted), so these can
# never be met by an empty read; a scanner regression that stops producing atoms trips them.
_FLOOR_FILES = 50
_FLOOR_ATOMS = 1000


def test_every_mechanical_lane_decisions_log_yields_at_least_one_atom():
    """A file `is_auto_safe_path` admits WILL be mechanically resolved. Zero atoms there means the
    verifier examines nothing on a file it is the only guard for.

    Run against the REAL corpus re-pathed onto the lane (see `_lane_path`), so this exercises both
    `is_auto_safe_path` and `atoms()` on real bytes on every run instead of skipping forever.
    """
    corpus = _corpus()
    if not corpus:
        pytest.skip("no real decisions.md in this checkout")
    lane = [(p, _lane_path(p), t) for p, t in corpus]

    # 1. the lane pattern admits every one of them — `is_auto_safe_path` on repo-derived slugs.
    rejected = [lp for _p, lp, _t in lane if not is_auto_safe_path(lp)]
    assert not rejected, f"lane pattern rejected a re-pathed corpus file: {rejected[:3]}"

    # 2. the parsing majority yields atoms ON THE LANE, above a floor no empty read can reach.
    parsing = [(p, t) for p, _lp, t in lane if _decision_atoms(t)]
    assert len(parsing) >= _FLOOR_FILES, (
        f"only {len(parsing)} corpus files parse to >= 1 atom — scanner or glob has regressed")
    total = sum(len(_decision_atoms(t)) for _p, t in parsing)
    assert total >= _FLOOR_ATOMS, f"only {total} decision-entry atoms across the corpus"

    # 3. the bare pre-`###` minority still yields ZERO on the lane — and that is exactly the shape
    #    `UNVERIFIABLE` exists to catch. Asserted end-to-end, not just as an atom count: were one
    #    of these to reach the lane for real, the verifier must refuse to certify it rather than
    #    read "no drops" off an empty inventory.
    bare = [(p, t) for p, _lp, t in lane if not _decision_atoms(t)]
    assert bare, "no bare-shape file left — the 92/10 split this test partitions has collapsed"
    for p, t in bare:
        assert verify(t, t, t, base=None, mechanical_applied=True).verdict == UNVERIFIABLE, (
            f"{p} parses to zero atoms yet does NOT verdict UNVERIFIABLE — silent pass is back")


def test_the_decision_entry_signature_is_injective_on_the_real_corpus():
    """The load-bearing property, and the one S2's fix restored: entries with DISTINCT CONTENT must
    produce DISTINCT signatures. A collision folds two such entries onto one atom, so dropping one
    of the pair leaves the inventory unchanged and VERIFIES CLEAN — the exact silent pass this
    design removed.

    `verify_atoms.py`'s header states bijectivity as a MEASURED fact (`worktree-fleet`: 54 -> 54);
    nothing asserted it. Here it is asserted per file: the number of DISTINCT admissible entry
    CONTENTS — the normalized `(tag, title, non-blank body lines, body text)` tuples of
    `_admissible_entries`, i.e. exactly the fields `_esc` and `_digest` consume — must equal that
    file's decision-entry atom count. Fewer atoms than contents is a real collision and fails here:
    weakening the signature to title-only, or to `(tag, title)`, folds materially different entries
    and trips this on the 7 files `verify_atoms.py` measures (`worktree-fleet` 54 -> 49).

    What this deliberately does NOT assert, and why. Entries whose contents are
    NORMALIZATION-identical are ONE element of the set, so a verbatim-duplicated entry is not
    counted twice. That is the design's ACCEPTED residual, not a gap to paper over: `design.md`
    records that the true collision class is normalization-identical, that two entries differing
    only in case, wrapping or emphasis are one atom and dropping one of such a pair is invisible to
    the verifier, and that the resolver's deliberate no-dedupe keep-both is the mitigation — the
    verifier cannot distinguish a duplicate from two identical decisions. The corpus holds such a
    pair for real: the archived `gc-upstream-gone-is-not-unclean` log carries two tier-1 entries
    re-logged verbatim after an M17 `core.bare` repair, so counting raw HEADINGS would demand 29
    atoms from 27 distinct contents and fail on settled behaviour. An occurrence ORDINAL was
    rejected as the discriminator for the same reason `verify_atoms.py` rejects it: ordinals are
    position-derived and a union merge permutes position.

    Numbers are not pinned; the equality is.
    """
    corpus = _corpus()
    if not corpus:
        pytest.skip("no real decisions.md in this checkout")
    parsing = [(p, t) for p, t in corpus if _decision_atoms(t)]
    assert len(parsing) >= _FLOOR_FILES, f"only {len(parsing)} parsing files — corpus read failed"

    collisions = []
    distinct = 0
    for p, t in parsing:
        n = len(set(_admissible_entries(t)))
        distinct += n
        if n != len(_decision_atoms(t)):
            collisions.append((p, n, len(_decision_atoms(t))))
    assert distinct >= _FLOOR_ATOMS, f"only {distinct} entries counted — the scan found nothing"
    assert not collisions, (
        "signature COLLISION — entries with distinct content folded onto one atom, so dropping one "
        f"verifies clean: {[(p, f'{n} distinct entries -> {a} atoms') for p, n, a in collisions]}")


def test_every_zero_atom_decisions_log_is_off_the_mechanical_lane():
    """The load-bearing half. The 10 known bare-`[slug]`-shaped logs are archive-only; if one ever
    appears on the lane, the silent-pass this design removed is back."""
    corpus = _corpus()
    if not corpus:
        pytest.skip("no real decisions.md in this checkout")
    zero = [p for p, t in corpus if not _decision_atoms(t)]
    on_lane = [p for p in zero if is_auto_safe_path(p)]
    assert not on_lane, f"zero-atom decisions.md ON the mechanical lane: {on_lane}"
    # ...and the known population is archive-only. Stated as a location claim, not a count.
    stray = [p for p in zero if "/completed-tp-designs/" not in p]
    assert not stray, f"zero-atom decisions.md outside completed-tp-designs/: {stray}"


def test_archived_decisions_logs_are_excluded_from_the_lane():
    """The exclusion the assertion above depends on. `completed-tp-designs/` is a FROZEN archive:
    it must never be auto-resolvable, regardless of whether its files parse."""
    archived = [p for p, _t in _corpus() if "/completed-tp-designs/" in p]
    if not archived:
        pytest.skip("no archived designs in this checkout")
    assert not [p for p in archived if is_auto_safe_path(p)]


def test_the_92_of_102_split_is_the_shape_split_not_a_filter_artifact():
    """Reconciles the two corpus figures quoted in `verify_atoms.py`: 102 = every real file,
    92 = the subset with >= 1 atom (the population a signature-collision question applies to).
    Pinned as a partition, not as literal numbers."""
    corpus = _corpus()
    if not corpus:
        pytest.skip("no real decisions.md in this checkout")
    parsed = [p for p, t in corpus if _decision_atoms(t)]
    unparsed = [p for p, t in corpus if not _decision_atoms(t)]
    assert len(parsed) + len(unparsed) == len(corpus)
    assert parsed, "no real file parses — the DECISION_ENTRY shape has drifted"
