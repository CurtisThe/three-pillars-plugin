"""Block-scan regressions for `verify_atoms.atoms()` + the `VerifyResult` / CLI contracts.

Split from `test_verify.py` (atom inventory) and `test_verify_verdict.py` (three-state verdict) by
responsibility: everything here is about how a `decision-entry` BLOCK is delimited and digested,
plus the two small absorption paths around the result object and the CLI's exit codes.

Every test below fails against the pre-fix scanner:

  S2  an unconditional `ATX` terminator closed a `### [tag] title` block at the first heading of
      ANY level, so `#### Sub` truncated the atom to an EMPTY body (`sha1("")` -> `da39a3ee5e6b`)
      and orphaned the whole tail. Two entries sharing a tag+title whose bodies opened with a
      sub-heading collapsed onto that one signature, so DROPPING ONE VERIFIED CLEAN.
  S3  conflict-marker lines matched no heading regex, so they landed in the body digest and
      produced a PHANTOM `DROPS_DETECTED` for an entry that was present, only marker-wrapped.
      **S3's fix is REVERTED as of round 9 and its three tests now assert the opposite** — see
      the S3 section below. The strip that suppressed the phantom removed real content from
      digests in three successive formulations; the phantom is accepted instead, and worded
      honestly by the consumer (`merge_driver`), which defers such a file either way.

Round 6 REVERSED the polarity of every fence assertion in this module, and round 9 did the same to
S3's. Tests here used to demand that a fenced — then a marker-shaped — line be invisible to the
scanner; that demand is what produced five rounds of invisible drops, so they now assert the
opposite and say so in their docstrings. `atoms()` may over-count (a fenced example is a real atom,
and editing it defers the file to a human) but may never under-count — see `verify_atoms.py`'s
header and `test_verify_superset.py`.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from verify import (  # noqa: E402
    DROPS_DETECTED, UNVERIFIABLE, USAGE_ERROR_EXIT, VERIFIED, VerifyResult, atoms, verify,
)
import verify as _verify  # noqa: E402
from test_verify_superset import ADVERSARIAL  # noqa: E402

VERIFY_PY = os.path.join(os.path.dirname(__file__), "verify.py")


def _de(text):
    return {sig for kind, sig in atoms(text) if kind == "decision-entry"}


# ---- S2: heading LEVEL delimits the block ----------------------------------------------------

def test_sub_heading_is_body_not_a_terminator():
    text = "### [a] t\n#### Sub\ntail line\n"
    sigs = _de(text)
    assert len(sigs) == 1
    sig = next(iter(sigs))
    # `da39a3ee5e6b` is sha1("") — the empty-body digest the truncating scan produced.
    assert not sig.endswith("da39a3ee5e6b"), "block truncated to an empty body"
    # The tail belongs to the atom, so changing it changes the signature.
    assert _de("### [a] t\n#### Sub\nDIFFERENT tail\n") != sigs


def test_no_plain_heading_terminates_the_block_either():
    """POLARITY REVERSED in round 7 (was `test_same_level_heading_still_terminates_the_block`).
    It demanded that a plain `### Some other section` close the block "or a following section's
    prose would be absorbed into the entry's digest" — absorbing prose is the SAFE direction, and
    the rule it protected was the round-7 silent pass: everything from that heading to the next
    real `### [tag] title` belonged to NO atom's body and matched no per-line kind, so deleting
    one of those lines left every signature identical and verified CLEAN.

    A body now ends only at the next DECISION-ENTRY-shaped heading, or EOF. Bodies get longer,
    coverage is total, and the price is stated in `verify_atoms.atoms()`: editing an intervening
    `## Section` heading perturbs the preceding entry's signature and can raise DROPS_DETECTED on
    a file where nothing was lost. That is a deferral to a human, not a missed drop.
    """
    b = _de("### [a] t\nbody\n")
    for tail in ("### Some other section\nforeign prose\n", "## Section\nforeign\n",
                 "# Title\nforeign\n", "#### Sub\nforeign\n"):
        assert _de("### [a] t\nbody\n" + tail) != b, tail
        # ...and the tail is COVERED: changing it changes the enclosing entry's signature.
        assert _de("### [a] t\nbody\n" + tail) != _de("### [a] t\nbody\n" + tail + "extra\n")
    # The next entry heading — and only that — still closes the block.
    assert _de("### [a] t\nbody\n### [b] u\nother\n") >= b


def test_a_heading_inside_a_body_cannot_orphan_the_tail():
    """The round-7 repro, verbatim. A `### Section` banner inside a fenced shell script quoted in
    an entry's body closed the block; `REAL_SECRET_LINE` and the tail after the fence then lay
    outside every signature, and deleting the line was invisible."""
    full = ("### [tp-plan] a decision\n**Reasoning**: see the script below\n"
            "```bash\n### Section banner\nREAL_SECRET_LINE=keep-me\n```\n"
            "tail content that matters\n")
    cut = full.replace("REAL_SECRET_LINE=keep-me\n", "")
    assert _de(full) != _de(cut)
    assert verify(full, full, cut, mechanical_applied=True).verdict == DROPS_DETECTED


def test_collision_pair_with_sub_headings_stays_two_atoms():
    """The drop-verifies-clean case. Two entries sharing tag AND title, each body opening with a
    sub-heading: under the truncating scan both digested to sha1("") and folded into ONE atom, so
    dropping either was invisible."""
    ours = "### [x] clip\n#### Decided\nkept finding 1\n"
    theirs = "### [x] clip\n#### Decided\nkept finding 2\n"
    assert len(_de(ours + theirs)) == 2
    # ...and dropping one is now REPORTED.
    r = verify(ours, theirs, ours, mechanical_applied=True)
    assert r.verdict == DROPS_DETECTED
    assert r.dropped == [("decision-entry", next(iter(_de(theirs))))]


def test_a_fenced_entry_heading_still_opens_a_block():
    """POLARITY REVERSED in round 6, and its second assertion CORRECTED in round 7. Round 6 was
    right that a `###` inside a fence is not literal text: a scanner able to decide "this heading
    is not a heading" was repeatedly made to decide it about a real one, which SUBTRACTS from the
    atom set, and three rounds of that shipped invisible drops.

    But round 6 justified BOTH of its fenced-heading assertions with the same sentence —
    "over-counting, which at worst defers a file to a human" — and that is only true of the first.
    The two cases point in OPPOSITE directions and must be distinguished:

    * a fenced `### [b] fake` OPENS a second atom. More atoms, more reportable drops:
      over-counting, safe.
    * a fenced plain `### not a heading` used to CLOSE the open block, and closing is a
      SHORTENING. `tail` then belonged to no atom, so deleting it verified clean — an
      UNDER-count wearing the over-count's justification. Round 7 removed every heading
      terminator; only the next entry heading closes a body now.
    """
    assert len(_de("### [a] t\n```\n### [b] fake\n```\n")) == 2
    # A fenced NON-decision `###` is BODY. `tail` is inside the atom, so its loss is visible.
    with_tail = _de("### [a] t\n```\n### not a heading\n```\ntail\n")
    assert with_tail != _de("### [a] t\n```\n### not a heading\n```\n")
    assert with_tail != _de("### [a] t\n```\n")
    # Tilde fences are not special either — nothing about a fence is.
    assert len(_de("### [a] t\n~~~\n### [b] y\n~~~\ntail\n")) == 2


def test_an_unclosed_fence_does_not_swallow_the_rest_of_the_file():
    """A running `in_fence` toggle stayed True to EOF on odd fence parity, so every later entry
    became BODY of the one open block: `### [a] one` + a stray fence + `### [b] two` collapsed to
    ONE atom, and dropping `[b]` verified clean. An unmatched opener is not a fence."""
    text = "### [a] one\nbody\n```\n### [b] two\nmore\n"
    assert len(_de(text)) == 2
    # ...and the drop is now REPORTED rather than invisible.
    ours = "### [a] one\nbody\n```\n"
    theirs = "### [b] two\nmore\n"
    r = verify(ours + theirs, theirs, ours, mechanical_applied=True)
    assert r.verdict == DROPS_DETECTED


def test_fence_nesting_no_longer_changes_the_atom_count():
    """POLARITY REVERSED in round 6. This used to pin CommonMark's fence-pairing rules (same
    character, at-least-as-long closer) by asserting that the nested cases collapsed to ONE atom.
    Every one of those assertions is an assertion that a real `### [b] y` heading is INVISIBLE,
    which is the silent-pass shape this design exists to remove. Fence pairing no longer exists,
    so the count is 2 in both cases and no arrangement of delimiters can lower it."""
    assert len(_de("### [a] t\n```\n~~~\n### [b] y\n```\n")) == 2
    assert len(_de("### [a] t\n````\n```\n### [b] y\n````\n")) == 2


# ---- A fence binds NOTHING — the deliberate over-count ----------------------------------------

# A doc's own illustrative example of the entry / row / log shapes, inside a ```markdown fence —
# exactly the shape `completed-tp-designs/living-doc-line-format/detailed-design.md` carries.
_FENCED_EXAMPLES = (
    "### L4: Real entry\n"
    "```markdown\n"
    "### L9: Example entry\n"
    "| D3 | example row |\n"
    "- **2024-01-01** — example log\n"
    "```\n"
)


def test_fenced_entry_row_and_log_lines_ARE_atoms():
    """POLARITY REVERSED in round 6 — this test previously asserted the exact opposite (`set(got)
    == {("entry", "real entry")}`, "the three fenced example lines are literal text").

    That assertion was wrong, and load-bearingly so: it demanded that the scanner be able to erase
    a `### L9:` / `| D3 |` / `- **date**` line from the inventory on the strength of a nearby
    backtick run. Rounds 3-5 built three different mechanisms to satisfy it and all three erased
    REAL atoms on ordinary documents, because a delimiter can be stray, unclosed or itself quoted.
    An atom that never enters `pre` cannot be reported dropped.

    The rule now: the shape decides, the fence has no vote. Fenced or not, these are the same four
    atoms — which is exactly what `origin/master` returns.
    """
    got = atoms(_FENCED_EXAMPLES)
    assert set(got) == {
        ("entry", "real entry"), ("entry", "example entry"), ("row", "example row"),
        ("log", "2024-01-01 — example log"),
    }, got
    unfenced = "### L9: Example entry\n| D3 | example row |\n- **2024-01-01** — example log\n"
    assert set(atoms(unfenced)) <= set(got), "the fence changed something — it must not"


def test_editing_a_fenced_example_IS_reported_as_a_drop():
    """POLARITY REVERSED in round 6 — previously `assert r.verdict == VERIFIED`, on the reasoning
    that the three fenced atoms "were never content".

    The reasoning was right about the symptom and wrong about the remedy. Suppressing this report
    means shrinking `pre`, and a smaller `pre` is a blinder verifier. DROPS_DETECTED here costs a
    human resolution of a file whose fenced example was reworded; the alternative cost is a real
    entry deleted with no signal at all. For a drop detector that is not a close call.
    """
    edited = _FENCED_EXAMPLES.replace("Example entry", "Reworded example") \
                             .replace("example row", "reworded row") \
                             .replace("example log", "reworded log")
    r = verify(_FENCED_EXAMPLES, _FENCED_EXAMPLES, edited, mechanical_applied=True)
    assert r.verdict == DROPS_DETECTED, r.verdict
    assert len(r.dropped) == 3, r.dropped


def test_an_unclosed_fence_still_leaves_per_line_kinds_visible():
    """The pre-existing fail-LOUD residual, now the whole rule rather than a special case: fence
    delimiters are ordinary text, so their contents are always scanned as structure."""
    got = atoms("### L4: Real entry\n```markdown\n| D3 | example row |\n")
    assert ("row", "example row") in got


# ---- Minor: the body digest's non-blank LINE COUNT fold ---------------------------------------

def test_the_body_line_count_fold_distinguishes_identically_normalized_bodies():
    """`_digest` folds the body's NON-BLANK line count in ahead of the normalized text. Without it
    the fold has no observable effect at all: `_norm` joins the body with single spaces, so
    `"a b"` on one line and `"a"` + `"b"` on two normalize to the byte-identical string `a b` and
    the two entries collapse onto ONE signature — dropping either then verifies clean. The count is
    the ONLY thing that tells this pair apart, so reverting the fold fails this test."""
    one_line = "### [a] t\na b\n"
    two_lines = "### [a] t\na\nb\n"
    assert len(_de(one_line)) == len(_de(two_lines)) == 1
    assert _de(one_line) != _de(two_lines)
    assert len(_de(one_line + "\n" + two_lines)) == 2
    # BLANK lines stay excluded — a trailing separator blank line appears/disappears across a merge
    # depending on whether another entry follows, and counting it fired a false DROPS_DETECTED.
    assert _de("### [a] t\nbody\n") == _de("### [a] t\nbody\n\n\n")


# ---- S3, REVERSED in round 9: conflict markers are ordinary body content ----------------------
#
# S3 was round 1's finding and these three tests encoded it: a marker-wrapped entry must verify
# clean, so the markers were stripped before a body was digested. Round 9 deleted the strip, so
# the expectation these tests assert has been INVERTED rather than preserved — keeping the old
# assertion green would have meant keeping the mechanism that produced five silent drops.
#
# Why the inversion is the right trade, in one line: the phantom fires ONLY on a blob that still
# carries conflict markers, i.e. one no human was going to skip anyway, and it changes a REASON
# STRING, not an outcome (`merge_driver` defers either way and touches nothing). A silent drop
# changes the outcome to "green" on lost content. See `verify_atoms.py`'s header.

def test_marker_wrapped_entry_is_now_an_ACCEPTED_phantom_drop():
    """WAS `test_marker_wrapped_entry_is_not_a_phantom_drop` (round 1, S3), asserting VERIFIED.

    Both entries ARE present in the resolved text — the atoms exist — but their bodies now carry
    the marker lines, so the decision-entry digests differ from the clean input sides and the
    verdict is `DROPS_DETECTED`. That is the phantom, asserted deliberately: the strip that
    suppressed it removed real content from digests in three successive formulations (a setext
    underline, a `|||||||` row, then whole spans bracketed across entries or by prose that merely
    quoted conflict syntax). The consumer is where this is made honest — `merge_driver` reports
    "could not verify a still-conflicted blob", not "content drop".
    """
    ours = "### [a] t\nbody ours\n"
    theirs = "### [b] u\nbody theirs\n"
    resolved = ("<<<<<<< ours\n### [a] t\nbody ours\n=======\n### [b] u\nbody theirs\n"
                ">>>>>>> theirs\n")
    r = verify(ours, theirs, resolved, mechanical_applied=True)
    assert r.verdict == DROPS_DETECTED
    assert r.pre_atoms == 2
    # The atoms are not LOST — every dropped key is a decision-entry whose body gained marker
    # lines. Nothing of the `entry`/`row`/`log` kinds is affected, because those are per-line.
    assert all(kind == "decision-entry" for kind, _sig in r.dropped), r.dropped
    # ... and the phantom disappears the moment the blob is marker-free, which is the only state
    # in which the driver ever stages a mechanical resolution.
    clean = "### [a] t\nbody ours\n### [b] u\nbody theirs\n"
    assert verify(ours, theirs, clean, mechanical_applied=True).verdict == VERIFIED


def test_diff3_base_marker_is_ordinary_content_too():
    """WAS `test_diff3_base_marker_is_stripped_too` (round 1, S3), asserting VERIFIED. `|||||||`
    is a table row of empty cells as often as it is a diff3 base marker, and no rule over shapes
    can tell those apart — so it is content, and its presence moves the enclosing digest."""
    ours = "### [a] t\nbody ours\n"
    theirs = "### [b] u\nbody theirs\n"
    resolved = ("<<<<<<< ours\n### [a] t\nbody ours\n||||||| base\n=======\n"
                "### [b] u\nbody theirs\n>>>>>>> theirs\n")
    assert verify(ours, theirs, resolved, mechanical_applied=True).verdict == DROPS_DETECTED
    # And the diff3 base line is COVERED: deleting it alone is reported.
    text = "### [a] t\nbody\n||||||| base\ntail\n"
    assert verify(text, text, _drop_line(text, "||||||| base"),
                  mechanical_applied=True).verdict == DROPS_DETECTED


def test_no_line_is_eaten_before_a_body_is_digested():
    """WAS `test_marker_stripping_does_not_eat_ordinary_table_or_rule_lines` (round 1, S3). The
    tightness claim it made — "only git's exact marker shapes go" — is now vacuous, because
    NOTHING goes. Widened accordingly: a rule, a table row, a near-miss `========` AND git's own
    exact markers all reach the digest, so removing any of them moves the signature."""
    b = _de("### [a] t\n")
    for line in ("| col | col |", "---", "===", "========", "=======", "|||||||",
                 "<<<<<<< ours", ">>>>>>> theirs"):
        assert _de(f"### [a] t\n{line}\n") != b, line


# ---- S-E1 (round 8): the strip removes DECORATION, not content shaped like it -----------------

def _drop_line(text, needle):
    lines = text.splitlines(keepends=True)
    out = [ln for ln in lines if ln.rstrip("\n") != needle]
    assert len(out) == len(lines) - 1, f"{needle!r} is not a unique line of the fixture"
    return "".join(out)


def test_marker_shaped_body_content_is_not_silently_droppable():
    """The round-8 finding. `=======` (a setext H1 underline) and `|||||||` (a row of empty cells)
    are ordinary markdown. The unconditional strip deleted them before `atoms()` saw them, so
    deleting either from a decision entry's body returned VERIFIED — a silent drop of real content
    — while deleting an ordinary body line beside it returned DROPS_DETECTED."""
    setext = ("### [tp-plan] a decision\nSection Title\n=======\nreal content\n"
              "### [tp-plan] next\nbody two\n")
    row = ("### [tp-plan] a decision\n| h | h |\n|||||||\nreal content\n"
           "### [tp-plan] next\nbody two\n")
    for text, needle in ((setext, "======="), (row, "|||||||"), (setext, "real content")):
        r = verify(text, text, _drop_line(text, needle), mechanical_applied=True)
        assert r.verdict == DROPS_DETECTED, (needle, r.verdict)


def test_an_unterminated_conflict_region_keeps_its_content():
    """A `<<<<<<<` with no matching `>>>>>>>`. Under the region rule this was the "err toward
    keeping content" arm; now it is unremarkable, because there is no rule and nothing is
    removed anywhere."""
    text = "### [a] t\n<<<<<<< ours\nours side\n=======\ntheirs side\n"
    assert verify(text, text, _drop_line(text, "======="),
                  mechanical_applied=True).verdict == DROPS_DETECTED


# ---- S-F1 (round 9): the region rule that replaced the unconditional strip, and its two holes --

def test_conflict_brackets_do_not_pair_across_an_entry_boundary():
    """S-F1(a). The region walk paired an OPEN with the FIRST CLOSE anywhere later, with no notion
    of an entry boundary. So an unterminated `<<<<<<<` in `d1` and an unrelated `>>>>>>>` in `d3`
    bracketed a `=======` sitting in `d2`'s body, and deleting that line left `atoms()`
    BYTE-IDENTICAL — verdict VERIFIED, a silent drop out of a different entry than either bracket.
    """
    text = ADVERSARIAL["conflict-brackets-spanning-entries"]
    without = _drop_line(text, "=======")
    assert atoms(text) != atoms(without), "the `=======` left no trace in any signature"
    assert verify(text, text, without, mechanical_applied=True).verdict == DROPS_DETECTED


def test_prose_that_merely_illustrates_a_conflict_is_not_a_region():
    """S-F1(b). A region was matched on SHAPE alone, and a doc quoting conflict syntax is
    byte-identical to a real conflict — this repo's SKILL.md and decisions.md are full of exactly
    this. So `<<<<<<< see below for an example` … `>>>>>>> end example` made the setext underline
    between them "decoration" and deleting it verified clean, while deleting the ordinary line
    below it did not. There is no structural signal that separates the two cases, which is the
    whole reason the strip is gone rather than narrowed a fourth time."""
    text = ADVERSARIAL["coincidental-conflict-brackets-in-prose"]
    for needle in ("=======", "Some Section", "real tail that matters"):
        r = verify(text, text, _drop_line(text, needle), mechanical_applied=True)
        assert r.verdict == DROPS_DETECTED, (needle, r.verdict)


# ---- Minor: an unescaped `|` collided two distinct signatures --------------------------------

def test_pipe_in_tag_or_title_does_not_collide():
    """`### [a|b] c` and `### [a] b|c` produced the SAME `tag|title|digest` string, so one of the
    pair was invisible and dropping it verified clean."""
    one = "### [a|b] c\nbody\n"
    two = "### [a] b|c\nbody\n"
    assert len(_de(one + two)) == 2
    assert verify(one, two, one, mechanical_applied=True).verdict == DROPS_DETECTED


# ---- Minor: VerifyResult must fail closed in a bool context ----------------------------------

def test_verify_result_is_falsy_unless_verified():
    assert bool(VerifyResult(verdict=VERIFIED)) is True
    assert bool(VerifyResult(verdict=DROPS_DETECTED)) is False
    assert bool(VerifyResult(verdict=UNVERIFIABLE)) is False
    # The absorption path this closes: `if not result:` must behave like `if not result.ok:`.
    for verdict in (VERIFIED, DROPS_DETECTED, UNVERIFIABLE):
        r = VerifyResult(verdict=verdict)
        assert bool(r) is r.ok


# ---- Minor: CLI exit codes do not collide with argparse's usage exit --------------------------

def _run(*args):
    return subprocess.run([sys.executable, VERIFY_PY, *args], capture_output=True, text=True)


def test_usage_error_exits_3_not_2(tmp_path):
    """argparse's own usage exit is 2, which collided with this CLI's documented
    `2 = UNVERIFIABLE`. A caller could not tell "unsafe merge" from "bad invocation"."""
    assert USAGE_ERROR_EXIT == 3
    assert _run("only-one-arg").returncode == 3
    assert _run("a", "b", "c", "--no-such-flag").returncode == 3


def test_missing_input_file_exits_3(tmp_path):
    p = tmp_path / "present.md"
    p.write_text("### L4: a\n")
    r = _run(str(p), str(tmp_path / "absent.md"), str(p))
    assert r.returncode == 3
    assert "cannot read input" in r.stderr


def test_normal_verdicts_keep_their_exit_codes(tmp_path):
    ours = tmp_path / "ours.md"
    theirs = tmp_path / "theirs.md"
    resolved = tmp_path / "res.md"
    ours.write_text("### L4: a\n")
    theirs.write_text("### L5: b\n")
    resolved.write_text("### L4: a\n### L5: b\n")
    assert _verify._main([str(ours), str(theirs), str(resolved)]) == 0
    resolved.write_text("### L4: a\n")
    assert _verify._main([str(ours), str(theirs), str(resolved)]) == 1
    for p in (ours, theirs, resolved):
        p.write_text("just prose\n")
    assert _verify._main([str(ours), str(theirs), str(resolved),
                          "--mechanical-applied"]) == 2
