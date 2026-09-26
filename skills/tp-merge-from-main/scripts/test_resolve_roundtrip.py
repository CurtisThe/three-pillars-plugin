"""Losslessness regressions for the `parse_conflict` -> `resolve_file` clean-region round trip.

Every test here fails against the pre-fix pipeline, which round-tripped each clean (non-conflicted)
segment through `"\\n".join(clean)` in `classify.parse_conflict` and `seg.splitlines()` in
`resolve.resolve_file`:

  S1  `"a\\n".splitlines() == ["a"]`, so a clean segment ending in a BLANK line lost exactly one
      blank line per segment — and git's diff3 minimization leaves a blank immediately before
      `<<<<<<<` on essentially every real markdown living-doc conflict. The loss VERIFIED CLEAN:
      `ENTRY`/`ROW`/`LOG` are line-shaped and `verify_atoms._digest` excludes blank lines
      deliberately, so no atom kind is blank-line-shaped and `decision-entry` is blind too. In
      CommonMark the lost blank is not always cosmetic — a paragraph followed by a list becomes a
      lazy continuation.
  M2  `str.splitlines()` also breaks on `\\r`, `\\f`, `\\x0b`, `\\x1c`-`\\x1e`, U+0085 and
      U+2028/9, so the outer split normalized every CRLF terminator in the WHOLE FILE to LF —
      well outside the conflicted region, and invisible to the verifier, whose `_norm` folds
      whitespace away.

The fix is one property, asserted directly below: `parse_conflict` splits on `"\\n"` alone and
hands clean segments to `resolve_file` as `list[str]`, never re-derived — so with `"\\n".join(...)`
reassembly the clean regions come out byte-for-byte.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "_shared"))
from classify import Hunk, parse_conflict  # noqa: E402
from resolve import RESOLVED, resolve_file  # noqa: E402
from verify import VERIFIED, verify  # noqa: E402

from auto_safe_resolution import resolve_conflict_bytes_detail  # noqa: E402

# A REALISTIC git-diff3-minimized `## History` conflict: the shared header factors out as the
# common prefix and the prior entry as the common suffix, leaving an EMPTY base — and the leading
# clean segment ENDS IN A BLANK LINE, the shape the drop fired on.
MINIMIZED = (
    "# Architecture\n"
    "\n"
    "## History\n"
    "\n"
    "<<<<<<< ours\n"
    "- **2026-02-01** — ours\n"
    "||||||| base\n"
    "=======\n"
    "- **2026-02-02** — theirs\n"
    ">>>>>>> theirs\n"
    "- **2026-01-01** — old\n"
)


def _reassemble(text):
    status, lines, _results = resolve_file(text)
    return status, "\n".join(lines)


def test_clean_segment_keeps_its_trailing_blank_line():
    """THE S1 regression. Pre-fix the blank after `## History` was silently deleted."""
    status, merged = _reassemble(MINIMIZED)
    assert status == RESOLVED
    assert "## History\n\n- **2026-02-01**" in merged, repr(merged)
    assert merged.startswith("# Architecture\n\n## History\n\n"), repr(merged)


def test_the_blank_line_drop_verified_clean_so_only_a_byte_check_catches_it():
    """Why a byte-level assertion is required: the verifier CANNOT see this. No atom kind is
    blank-line-shaped, so the pre-fix output was VERIFIED and written to disk."""
    _status, merged = _reassemble(MINIMIZED)
    stripped = merged.replace("## History\n\n", "## History\n")
    ours = "## History\n\n- **2026-02-01** — ours\n- **2026-01-01** — old\n"
    theirs = "## History\n\n- **2026-02-02** — theirs\n- **2026-01-01** — old\n"
    assert verify(ours, theirs, stripped, mechanical_applied=True).verdict == VERIFIED


def test_every_blank_line_survives_across_multiple_clean_segments():
    """The loss was ONE blank PER SEGMENT, so a two-hunk file lost two. Counting pins that."""
    text = MINIMIZED + "\n## Notes\n\n" + (
        "<<<<<<< ours\n- **2026-03-01** — ours two\n||||||| base\n"
        "=======\n- **2026-03-02** — theirs two\n>>>>>>> theirs\n")
    _status, merged = _reassemble(text)
    assert merged.count("\n\n") == text.count("\n\n")


def test_parse_and_reassemble_is_exact_on_a_conflict_free_file():
    """The strongest statement of the property: with no hunk at all, in == out, byte for byte —
    including a trailing blank line at EOF, which `splitlines()` also ate."""
    for text in ("# Doc\n\n## Section\n\nbody\n",
                 "# Doc\n\n## Section\n\nbody\n\n",       # trailing blank at EOF
                 "no final newline",
                 "\n\n\n",
                 ""):
        status, merged = _reassemble(text)
        assert status == RESOLVED, repr(text)
        assert merged == text, (repr(text), repr(merged))


def test_clean_segments_are_line_lists_not_rejoined_strings():
    """The mechanism, pinned so the lossy round trip cannot be reintroduced as a refactor: a clean
    segment is a `list[str]` handed straight through, so there is nothing to re-derive."""
    segs = parse_conflict(MINIMIZED).segments
    clean = [s for s in segs if not isinstance(s, Hunk)]
    assert clean and all(isinstance(s, list) for s in clean), segs
    assert clean[0] == ["# Architecture", "", "## History", ""], clean[0]


def test_pre_context_is_the_nearest_non_blank_clean_line():
    """`_pre_context` skips the blank diff3 minimization leaves before `<<<<<<<`. A literal
    previous-line rule would hand `classify_hunk` `""` on essentially every real conflict and its
    `focus_ctx` disambiguator would be dead."""
    hunk = [s for s in parse_conflict(MINIMIZED).segments if isinstance(s, Hunk)][0]
    assert hunk.pre_context == "## History"


# ---- M2: line TERMINATORS survive the round trip ---------------------------------------------

def _crlf(text):
    return text.replace("\n", "\r\n")


def test_crlf_terminators_survive_the_resolver_verbatim():
    """M2. The module header claimed CRLF bytes survive verbatim; `splitlines()` made that FALSE,
    rewriting the whole file's line endings outside the conflicted region."""
    status, merged = _reassemble(_crlf(MINIMIZED))
    assert status == RESOLVED
    assert "\r\n" in merged
    assert "\n" not in merged.replace("\r\n", ""), repr(merged)   # no bare LF anywhere


def test_crlf_survives_the_full_shared_byte_production_path():
    """End to end through `resolve_conflict_bytes_detail` — the function BOTH the producer and the
    Phase-2 certificate verifier run, i.e. what actually reaches the worktree."""
    base = _crlf("# H\n\n## History\n\n- **2026-01-01** — old\n")
    ours = _crlf("# H\n\n## History\n\n- **2026-02-01** — ours\n- **2026-01-01** — old\n")
    theirs = _crlf("# H\n\n## History\n\n- **2026-02-02** — theirs\n- **2026-01-01** — old\n")
    status, merged, mechanical = resolve_conflict_bytes_detail(base=base, ours=ours, theirs=theirs)
    assert status == RESOLVED and mechanical is True
    assert "\r\n" in merged and "\n" not in merged.replace("\r\n", ""), repr(merged)
    assert "- **2026-02-01** — ours\r\n- **2026-02-02** — theirs\r\n" in merged
    assert verify(ours, theirs, merged, mechanical_applied=mechanical).verdict == VERIFIED


def test_exotic_unicode_separators_do_not_split_a_prose_line():
    """`splitlines()` breaks on U+2028, U+0085, `\\x0b` and `\\x0c` as well; each would have cut a
    prose line in two and rejoined the halves with a plain `\\n` — a silent content rewrite the
    verifier's whitespace-folding `_norm` cannot see."""
    for sep in (" ", " ", "\x85", "\x0b", "\x0c", "\x1c"):
        text = f"# Doc\n\nprose{sep}continues here\n"
        status, merged = _reassemble(text)
        assert status == RESOLVED
        assert merged == text, (repr(sep), repr(merged))
