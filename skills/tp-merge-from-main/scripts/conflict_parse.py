#!/usr/bin/env python3
"""Conflict-region PARSER — the front half of the living-doc merge pipeline.

Split out of `classify.py` (round 11): turning a `merge-file --diff3` blob into clean line blocks
and `Hunk` objects is a different responsibility from *labelling* those hunks, and the zero-drop
argument for the parse is long enough to deserve its own module. `classify` re-exports every name
here, so `from classify import Hunk, parse_conflict` keeps working unchanged.

The one property this module owns: **the parse is LOSSLESS**. Every input line lands in exactly
one segment, and re-emitting the segments verbatim — clean lines, plus each hunk's own marker
lines around its three sides — reconstructs the input byte-for-byte. `test_resolve_invariants.py`
asserts that over a generated corpus, and `resolve._deferred` depends on it to hand a region it
did not understand back to the human unedited.

**Two scans, and only one of them is trusted to write** (round 17). Git's marker grammar is
ordinary markdown, so a scan that recognises markers by PREFIX cannot tell a region git wrote from
a region a document merely QUOTES (a fenced example of a conflict, F1) or from a content line that
happens to begin `>>>>>>>` (F2). `parse_conflict(text, labels=...)` therefore has a LABELLED mode:
the byte path (`auto_safe_resolution`) hands `git merge-file` three labels carrying a per-call nonce
that none of the three inputs contains, and the labelled scan accepts ONLY marker lines equal to
`<<<<<<< {ours}` / `||||||| {base}` / `>>>>>>> {theirs}` (plus the `\r` merge-file appends to a
marker in a CRLF file). No content line can equal one of those, so open, base and close are
unambiguous; the separator is bare `=======` in every conflict style and stays ambiguous by text
alone — see `_scan_labelled` for why that ambiguity can only ever DEFER. Unlabelled callers (the
`resolve.py` CLI over a working-tree file, unit tests on synthetic blobs) keep the prefix scan and
its known blind spots; nothing on the path that writes or certifies bytes uses it.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import chain, islice

# The four conflict-region markers, in the order `git merge-file --diff3` emits them. Always
# matched as line PREFIXES (git appends a label — `<<<<<<< ours.md`), never by equality.
MARK_OPEN, MARK_BASE, MARK_SEP, MARK_CLOSE = "<<<<<<<", "|||||||", "=======", ">>>>>>>"


@dataclass
class Hunk:
    ours: list[str]
    base: list[str]
    theirs: list[str]
    label: str = ""
    pre_context: str = ""   # nearest non-blank clean line before the hunk (disambiguates table type)
    # The region's own four marker lines, VERBATIM as they were read. Held so a deferral can
    # re-emit the region exactly as git wrote it instead of re-synthesising generic labels — see
    # `resolve._deferred`. `base_marker` is None for a 2-way region (no `|||||||` at all); the
    # defaults are the diff3 shape, so hand-built `Hunk(...)`s in tests stay valid.
    open_marker: str = "<<<<<<< ours"
    base_marker: str | None = "||||||| base"
    sep_marker: str = "======="
    close_marker: str = ">>>>>>> theirs"
    # Every CONTENT line of the file OUTSIDE this region: the clean segments plus every other
    # region's ours/base/theirs sections, in file order. Filled by `parse_conflict` with an
    # `_Outside` view (round 25: of one tuple every region shares, not a copy per region); empty
    # on a hand-built `Hunk`, whose "file" is then only its own sides. A resolver that invents a new
    # identifier (`resolve_id_renumber`) needs it to know which identifiers the file already uses.
    context: Sequence = field(default_factory=list, repr=False, compare=False)
    # The first NON-BLANK line after this region: read from the clean segments that follow it, ""
    # when only blank lines (or nothing) follow to EOF, and None when it is NOT KNOWN — another
    # conflict region comes before any non-blank clean line, or nothing filled it in. Filled by
    # `parse_conflict`; None on a hand-built `Hunk` unless the caller passes a value (round 20: the
    # default used to be "", which reads as EOF, the one value that PASSES the boundary check, so a
    # hand-built hunk skipped it). A resolver that emits ours' block and then theirs' makes this
    # line follow THEIRS' last entry, whichever side's entry it continued, so a class that merges
    # that way has to know what it is (round 19: `classify._ends_at_boundary`, which refuses None).
    post_context: str | None = field(default=None, repr=False, compare=False)
    # The line DIRECTLY after this region's close marker, blank or not (round 21): "" when the
    # region ends the text, None when it is NOT KNOWN — another region follows with no clean line
    # between, or nothing filled it in (a hand-built `Hunk`). `post_context` skips blank lines, and
    # a table ends AT a blank line, so the inventory row merge, which appends theirs-only rows after
    # ours' block, reads this instead (`table_run.appended_rows_refusal`).
    line_after: str | None = field(default=None, repr=False, compare=False)


@dataclass
class ParsedFile:
    segments: list = field(default_factory=list)   # entries are `list[str]` (clean) or `Hunk`


def _pre_context(segments: list) -> str:
    """The nearest preceding NON-BLANK **clean** line — the table-type disambiguator
    `classify_hunk` reads for its `focus_ctx` check — looking back PAST any intervening hunks.

    "Nearest non-blank" rather than "literally the previous line": git's diff3 minimization leaves
    a blank line immediately before `<<<<<<<` on essentially every real markdown conflict, so a
    literal previous-line rule would hand `classify_hunk` an empty string almost always and the
    `focus_ctx` arm would be dead. Skipping blanks is also the fail-CLOSED direction — `focus_ctx`
    only ever routes a hunk from a MECHANICAL class to the SEMANTIC
    `current-focus-reprioritization`, i.e. towards a human.

    "Past any intervening hunks" (S-I3) is the same argument one segment further out. The previous
    form returned `""` the moment the preceding segment was a `Hunk`, and two ADJACENT conflict
    regions — the shape a base-sync of a Current-Focus table produces, where consecutive priority
    rows each conflict — are exactly the case where the section heading a reader would call "the
    context" sits above the FIRST region. Losing it flipped a Current-Focus hunk from the semantic
    class to `design-inventory-row-merge`, inverting this function's own fail-closed guarantee. A
    hunk's own lines are never context (they are the conflict), so hunks are SKIPPED, not read.

    `parse_conflict` does not call this per region (round 25): on a file whose regions are
    separated by blank lines only, each call walked back over every earlier region, quadratic in
    the region count. It keeps the same value as it scans, updating it from each clean segment.
    """
    for seg in reversed(segments):
        if not isinstance(seg, list):
            continue                       # a Hunk: not context — keep looking further back
        for line in reversed(seg):
            if line.strip():
                return line
    return ""


def _find(lines: list[str], start: int, prefix: str, stop: int) -> int | None:
    """Index of the first line in `lines[start:stop]` beginning with `prefix`, else None."""
    for i in range(start, stop):
        if lines[i].startswith(prefix):
            return i
    return None


def _scan_region(lines: list[str], start: int) -> tuple[Hunk, int] | None:
    """Read the conflict region opening at `lines[start]` (a `<<<<<<<` line).

    Returns `(Hunk, index_just_past_the_region)`, or **None** when the region is not well formed.
    Three rules, all fixes for a resolver-side content DROP (S-H1, then S-I2):

    * **Close FIRST, then split — the separators are found by LOOKAHEAD.** `git merge-file
      --diff3` always emits its markers in the order `<<<<<<<` → `|||||||` → `=======` →
      `>>>>>>>`, so the region's extent is decided by its close marker and only then is it cut
      into sides. That ordering is what disambiguates a structural separator from a line of
      CONTENT that merely starts with one: if a `|||||||` occurs before the close, the region is
      3-way and `ours` ends THERE — every earlier `=======` is content (a setext underline, a
      quoted example) — and the separator is the first `=======` after the base marker. With no
      `|||||||` the region is 2-way and `ours` ends at the first `=======`. Exactly ONE `=======`
      is structural; the previous scan took the first prefix-match unconditionally and so cut
      `ours` at a content line, deleting it under a RESOLVED verdict (S-I2).
    * **`ours` ends at a terminator, never at EOF.** A 2-way region (no base section at all) must
      not run on past its own `=======`/`>>>>>>>` and swallow everything after it, including a
      later genuine conflict (S-H1). A base section exists ONLY when a `|||||||` was actually
      matched; `base_marker` stays None otherwise, so no section is invented.
    * **An unterminated region is not a region.** `git merge-file` always emits well-formed
      regions, so a `<<<<<<<` that never closes — or that closes with no separator inside it — is
      PROSE, and this repo's own docs quote conflict syntax constantly. Returning None makes
      `parse_conflict` keep the line as content; treating it as a hunk is what deleted the
      content. When the shape is ambiguous, keep the content.
    """
    close = _find(lines, start + 1, MARK_CLOSE, len(lines))
    if close is None:
        return None                                  # region never closed -> content, not a hunk
    base_i = _find(lines, start + 1, MARK_BASE, close)
    if base_i is not None:                           # 3-way: `ours` ends at the base marker
        sep_i = _find(lines, base_i + 1, MARK_SEP, close)
        if sep_i is None:
            return None                              # base section never reached `=======`
        ours, base = lines[start + 1:base_i], lines[base_i + 1:sep_i]
    else:                                            # 2-way: `ours` ends at the first `=======`
        sep_i = _find(lines, start + 1, MARK_SEP, close)
        if sep_i is None:
            return None                              # no separator at all -> not a region
        ours, base = lines[start + 1:sep_i], []
    return Hunk(ours=ours, base=base, theirs=lines[sep_i + 1:close], open_marker=lines[start],
                base_marker=lines[base_i] if base_i is not None else None,
                sep_marker=lines[sep_i], close_marker=lines[close]), close + 1


def _is_exact(line: str, marker: str) -> bool:
    """`line` IS `marker` — byte-equal, or byte-equal plus the `\r` `git merge-file` puts on a marker
    line of a CRLF file (it matches the markers' line ending to the file's)."""
    return line == marker or line == marker + "\r"


def _scan_labelled(lines: list[str], start: int, labels: tuple[str, str, str]):
    """The LABELLED counterpart of `_scan_region`, for text `git merge-file` produced under
    `labels == (ours, base, theirs)`. Returns `(Hunk, index_just_past_the_region)` or None.

    Open, base and close markers are recognised by EQUALITY with the labelled marker line, never by
    prefix, so a quoted example (`<<<<<<< HEAD`) or a content line starting `>>>>>>>` is content
    wherever it sits. A region must be complete and in merge-file's order — open, exactly one base
    marker, a separator, close — with no second open or base marker inside it; anything else
    returns None, and the caller's conflict-count check (`auto_safe_resolution`) turns the resulting
    shortfall into a refusal of the whole file rather than a guess.

    The separator is the one marker that carries no label, so a CONTENT line `=======` inside the
    base or theirs section is indistinguishable from it by text. The first bare `=======` after the
    base marker is taken. Whichever of the candidates is the real one, every other candidate then
    lies inside a side section, where `resolve_totality.embedded_marker` refuses the hunk: an
    ambiguous separator can mis-cut a region only into a hunk that DEFERS, and a deferral re-emits
    the lines verbatim in their original order, so no choice of cut loses a line.
    """
    open_m, base_m, close_m = (f"{MARK_OPEN} {labels[0]}", f"{MARK_BASE} {labels[1]}",
                               f"{MARK_CLOSE} {labels[2]}")
    close = next((i for i in range(start + 1, len(lines)) if _is_exact(lines[i], close_m)), None)
    if close is None:
        return None
    inner = range(start + 1, close)
    if any(_is_exact(lines[i], open_m) for i in inner):
        return None                                  # a second open before this close: malformed
    bases = [i for i in inner if _is_exact(lines[i], base_m)]
    if len(bases) != 1:
        return None                                  # --diff3 always emits exactly one base marker
    base_i = bases[0]
    sep_i = next((i for i in range(base_i + 1, close) if _is_exact(lines[i], MARK_SEP)), None)
    if sep_i is None:
        return None
    return Hunk(ours=lines[start + 1:base_i], base=lines[base_i + 1:sep_i],
                theirs=lines[sep_i + 1:close], open_marker=lines[start],
                base_marker=lines[base_i], sep_marker=lines[sep_i],
                close_marker=lines[close]), close + 1


class _Outside(Sequence):
    """`lines` without `lines[lo:hi]`, in order: a read-only view that does not copy `lines`.

    Round 25: `Hunk.context` used to be a list of every content line outside the region, built
    for each region, so a file of R regions and L lines held R x L references (the parse of a
    300 KB file of 12,500 regions peaked at about 4.9 GB, an out-of-memory kill `merge_back`'s
    `except Exception` cannot catch). Every region of a file now shares ONE tuple of its content
    lines and excludes its own lines by index."""
    __slots__ = ("_lines", "_lo", "_hi")

    def __init__(self, lines: tuple, lo: int, hi: int) -> None:
        self._lines, self._lo, self._hi = lines, lo, hi

    @property
    def whole(self) -> tuple:
        """Every content line of the file, this region's own included: the ONE shared tuple, so a
        per-file computation (`keyed_rows._file_keys`) can be done once and recognised by `is`."""
        return self._lines

    def __len__(self) -> int:
        return len(self._lines) - (self._hi - self._lo)

    def __iter__(self):
        return chain(islice(self._lines, self._lo), islice(self._lines, self._hi, None))

    def __getitem__(self, i):
        if isinstance(i, slice):
            return list(self)[i]
        n = len(self)
        if i < 0:
            i += n
        if not 0 <= i < n:
            raise IndexError(i)
        return self._lines[i if i < self._lo else i + self._hi - self._lo]


def _fill_context(pf: ParsedFile) -> None:
    """Give every hunk the content lines of the file outside it (`Hunk.context`), the first
    non-blank line after it (`Hunk.post_context`) and the line directly after it
    (`Hunk.line_after`).

    Linear in the file (round 25). The file's content lines are gathered once and shared. The
    first non-blank line after a region is found by ONE backward pass: it is the first non-blank
    line of the nearest following clean segment that has one, "" when no such segment follows
    (only blank lines, or nothing, to EOF), and None when a hunk comes first. Unlike `_pre_context`
    it does NOT look past a hunk: a region's own lines are not context, and the line that follows
    it in the merged file depends on how that later region resolves."""
    lines: list[str] = []
    bounds = []
    for seg in pf.segments:
        lo = len(lines)
        lines += [*seg.ours, *seg.base, *seg.theirs] if isinstance(seg, Hunk) else seg
        bounds.append((lo, len(lines)))
    shared = tuple(lines)
    after: str | None = ""                         # what follows the segment being visited
    for n in range(len(pf.segments) - 1, -1, -1):
        seg = pf.segments[n]
        if not isinstance(seg, Hunk):
            after = next((line for line in seg if line.strip()), after)
            continue
        seg.context = _Outside(shared, *bounds[n])
        seg.post_context = after
        nxt = pf.segments[n + 1] if n + 1 < len(pf.segments) else [""]
        seg.line_after = None if isinstance(nxt, Hunk) else nxt[0]
        after = None


def parse_conflict(text: str, labels: tuple[str, str, str] | None = None) -> ParsedFile:
    """Split `git merge-file --diff3` output into clean line-blocks and `Hunk` objects.

    Line splitting is `text.split("\\n")`, NOT `text.splitlines()`, and clean segments are kept as
    `list[str]` rather than joined back into a string. Both are load-bearing losslessness choices:

    * **`split("\\n")`** — `splitlines()` also breaks on `\\r`, `\\f`, `\\x0b`, `\\x1c`-`\\x1e`,
      U+0085 and U+2028/9, so it SPLITS a CRLF line-ending (dropping the `\\r` when the pieces are
      rejoined with `\\n`) and would cut a prose line carrying any of those characters in two.
      `split("\\n")` breaks on exactly the one separator the resolver rejoins with, so
      `"\\n".join(text.split("\\n")) == text` for EVERY string — the round trip is exact, and a
      CRLF terminator rides through as a trailing `\\r` on the line's own text. Every pattern in
      `classify` is prefix-anchored, so a trailing `\\r` cannot change a classification.
    * **`list[str]` clean segments** — the previous `"\\n".join(clean)` / `seg.splitlines()` round
      trip in `resolve.resolve_file` silently DROPPED one blank line per clean segment
      (`"a\\n".splitlines() == ["a"]`), and diff3 minimization puts a blank immediately before
      `<<<<<<<` on essentially every real markdown living-doc conflict. The loss verified clean:
      no atom kind is blank-line-shaped and `_digest` excludes blank lines deliberately. Holding
      the lines never re-derives them, so there is nothing to lose.

    A `<<<<<<<` line only becomes a `Hunk` when `_scan_region` reads a COMPLETE region from it;
    otherwise the line is kept as clean content. See `_scan_region` for why that polarity is the
    zero-drop one.

    `labels=(ours, base, theirs)` selects the LABELLED scan (`_scan_labelled`): only a line EQUAL to
    `<<<<<<< {ours}` can open a region. `labels=None` keeps the prefix scan (module header).

    Discriminate segments with `isinstance(seg, Hunk)` — a clean segment is a `list`, not a `str`.
    """
    pf = ParsedFile()
    lines = text.split("\n")
    i, clean = 0, []
    before = ""                  # `_pre_context(pf.segments)`, kept as the scan goes (linear)
    open_m = f"{MARK_OPEN} {labels[0]}" if labels is not None else None
    while i < len(lines):
        if labels is not None:
            scanned = _scan_labelled(lines, i, labels) if _is_exact(lines[i], open_m) else None
        else:
            scanned = _scan_region(lines, i) if lines[i].startswith(MARK_OPEN) else None
        if scanned is None:
            # Not an opening marker, or an opening marker whose region never closes: either way
            # this is ordinary content. Keeping the `<<<<<<<` line as clean text (rather than
            # opening a hunk that runs to EOF) is what preserves it, and it lets a WELL-FORMED
            # region later in the file still be found and resolved on its own merits.
            clean.append(lines[i]); i += 1
            continue
        hunk, i = scanned
        if clean:
            pf.segments.append(clean)
            before = next((line for line in reversed(clean) if line.strip()), before)
            clean = []
        hunk.pre_context = before
        pf.segments.append(hunk)
    if clean:
        pf.segments.append(clean)
    _fill_context(pf)
    return pf
