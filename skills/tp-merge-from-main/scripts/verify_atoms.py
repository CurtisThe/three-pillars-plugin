#!/usr/bin/env python3
# The module docstring is RAW (r""") only because it quotes regex source containing `\|`;
# nothing in it is an escape sequence.
r"""Atom SCANNER for the zero-drop verifier — the shape half of `verify.py`.

Split out of `verify.py` by responsibility (the file was at the size-guard soft-warn): this
module owns *what a content atom is* and how a line/block becomes a signature; `verify.py` owns
the three-state VERDICT and the CLI. `verify.py` re-exports every public name here, so
`verify.atoms` / `verify.ENTRY` / `verify.ATOM_KINDS` and friends resolve exactly as before.

Knows NOTHING about the resolver. It inventories *content atoms* present in ours ∪ theirs and
asserts each survives into the resolved output. Atom identity is **ID-independent**, so a
legitimate renumber (L4 -> L7) is not mistaken for a drop:

    entry atom  `### L<n>: <title>`         -> signature = normalized <title>
    heading-entry atom
                `### M-new-x: t`, `### M27 (RESOLVED …): t`, `` ### `slug` (date) ``
                                            -> signature = <key>|normalized <title>, status left out
    row atom    `| D<n> | <name> | `        -> signature = normalized <name>
                `` | `slug` | … | ``         -> signature = the raw `` `slug` `` (backticks kept)
    slug-row atom
                `| <slug> | …`, `| **<slug>** | …`  -> signature = <slug> (a plain or bold first
                                               cell; a backticked slug is the row atom above)
    log atom    `- **<date|`slug`>** — …`   -> signature = normalized <key + title>
    decision-entry atom
                `### [<skill>] <title>`     -> signature = <tag>|<title>|sha1(<body>)[:12]
                + its body, to the next `### [tag] title` heading or EOF. NO
                  other heading terminates it — a `#### Sub` and a plain
                  `## Section` are both BODY.

THE ONE INVARIANT THIS MODULE IS FOR — `atoms()` NEVER SUBTRACTS
================================================================
For a drop DETECTOR the two error directions are not symmetric, and every decision below follows
from that asymmetry:

  * **Over-counting** — a line that is only an ILLUSTRATION of an atom shape (a fenced example in
    a doc) is inventoried as a real atom. Editing that example on one side then reports a drop
    that was never content, and the driver DEFERS the file to a human. Noisy. **Safe.**
  * **Under-counting** — a real line is judged "not structure" and never enters the `pre`
    inventory. Its deletion is then undetectable: `pre - post` is empty and the file verifies
    clean. **Silent pass** — the exact defect this module exists to eliminate.

So the atom set may only ever GROW relative to a naive, markdown-blind per-line scan. Three
consecutive attempts to make the scanner markdown-aware (a fence mask, a conflict-marker barrier,
a conflict-ZONE partition of that mask) each shipped a fresh instance of the under-counting class:
in every one of them an ordinary document — a stray unclosed backtick fence followed by an
unrelated code block; a doc merely QUOTING conflict-marker syntax — made a real `### L1:` heading
vanish from the scan. Fence machinery SUBTRACTS from `pre` by construction, and subtraction from
`pre` is precisely how a drop becomes invisible. It has all been deleted.

What replaces it is nothing: the per-line scan sees every line, and a `### [tag] title` heading
always opens a block. A ```` ``` ````-fenced `### L9: Example entry` in a design doc IS an atom
here, deliberately — rewording it can raise `DROPS_DETECTED` and hand the file to a human, which
is the correct, fail-safe outcome for a drop detector and is exactly what `origin/master` has
always done.

SUBTRACTION HAS A SECOND FORM — THE ORPHANED LINE
=================================================
An atom can be present in `pre` and still hide a drop, because a signature only covers the lines it
DIGESTS. Any line belonging to no atom's body and matching no per-line kind is an ORPHAN: delete it
and every signature on both sides is unchanged, so `pre - post` is empty and the file verifies
clean. The superset invariant does not see this — it guards atom EXISTENCE, and an orphan is absent
from the naive scan too, so both sides agree while the drop stays invisible. Existence is necessary,
COVERAGE is the other half.

A heading-level terminator manufactured exactly that. Closing a decision-entry body at any ATX
heading of level <= 3 let a plain `### Section` banner — including one sitting inside a fenced shell
script in an entry's own body — close the block early, and everything from there to the next real
`### [tag] title` became orphan. So the body now runs to the next DECISION-ENTRY-SHAPED heading or
EOF, and nothing else closes it. Bodies get LONGER, which is the safe direction. The honest
consequence: an intervening `## Section` heading is now digested into the PRECEDING entry, so
editing that heading perturbs that entry's signature and can raise `DROPS_DETECTED` on a file where
no entry was lost. That is a deferral to a human, i.e. fail-safe, and it is preferred to a tail of
real content that no signature covers. `test_verify_coverage.py` pins the coverage half directly:
for any document with at least one decision-entry atom, deleting ANY non-blank line at or after the
first `### [tag] title` heading must yield `DROPS_DETECTED`.

SUBTRACTION HAS A THIRD FORM — AND IT IS WHY THE SCANNER NOW STRIPS NOTHING AT ALL
==================================================================================
The last line-removing step was the conflict-marker strip, and it took three rounds to die. It was
argued safe by CONSTRUCTION: no marker-shaped line can also match `ENTRY`, `ROW`, `LOG` or
`DECISION_ENTRY`, so stripping could only cost a DIGEST, never an atom. True — and irrelevant,
because a body digest IS a signature, and a line that leaves the digest is a line whose deletion
nothing reports. That is the coverage defect again, once per costume:

  * **Unconditional strip.** `^={7}$` is also a **setext H1 underline**, `^\|{7}` a **table row of
    empty cells**. Deleting either from a decision entry's body returned VERIFIED while deleting
    an ordinary body line returned DROPS_DETECTED. Silent drop of real content.
  * **Region-narrowed strip** (strip `=======`/`|||||||` only between an OPEN and its matching
    CLOSE). Two more, both measured on the shipped code. (a) The pairing is not entry-scoped, so an
    unterminated `<<<<<<<` plus an unrelated `>>>>>>>` far downstream made every `=======` between
    them decoration — ACROSS an entry boundary, inside a different entry's body. (b) The brackets
    are only SHAPE-matched, so prose that merely ILLUSTRATES conflict syntax (`<<<<<<< see below
    for an example` … `>>>>>>> end example`) opened a region and swallowed a real setext underline
    between them.

There is no fix in that direction. A `git merge-file` region and a doc quoting one are the same
bytes; this repo's `SKILL.md` and `decisions.md` files are full of the latter, and the suite has
carried a `fake-region-in-prose` fixture since round 5 for exactly that reason. So no region rule
can make the strip safe, and a SMARTER rule is what produced each of the last three defects.

The strip is therefore GONE — every line of a body is digested, marker lines included. What that
costs is a PHANTOM: when a deferred blob still carries `<<<<<<< / ======= / >>>>>>>`, those lines
perturb the enclosing entry's digest and `verify()` reports `DROPS_DETECTED` on a file where
nothing was dropped. That is the correct trade, because the two errors are not the same size — a
phantom defers a file to a human who was already required (the blob is still conflicted), while a
silent drop is content lost with a green verdict. Where the phantom's WORDING matters it is fixed
in the consumer, not here: `merge_driver` checks whether the blob it verified still contains
markers and says "could not verify a still-conflicted blob" instead of "content drop". A message
change in the reader is not a subtraction in the scanner.

Two corpus sizes appear in this module and they count DIFFERENT things — stated explicitly because
the discrepancy read as a contradiction:
  * **103** — every `decisions.md` file in the repo, unfiltered.
  * **93** — the subset that parses to at least one `decision-entry` atom, i.e. the population on
    which a *signature-collision* question is even askable. The excluded files carry the bare
    pre-`###` shape (`[slug/phase-N] title — operator, date`) and yield ZERO atoms; ALL of them
    live under `completed-tp-designs/`, which `_DESIGN_DECISIONS_RE` excludes from the mechanical
    lane, so none is reachable by the resolver. Counts are as measured when this was written and
    will drift as the repo grows; `test_verify_corpus.py` pins the INVARIANT (on-lane => >=1 atom,
    and zero-atom => off-lane), not the numbers.

Across those collision-measurable files a title-only signature COLLIDES in 7 files
(`worktree-fleet`: 54 entries -> 49 atoms); `(tag, title)` still collides in 2;
`(tag, title, body-digest)` collides in 0 and is bijective on `worktree-fleet` (54 -> 54). The
colliding titles are the orchestrator's own boilerplate — i.e. a weaker signature would be weakest
on exactly the autonomous-run logs this atom exists to protect. An occurrence ORDINAL was rejected:
ordinals are position-derived and a union merge permutes position, so ours-#1..#3 would collide
with theirs-#1..#3 and a drop of three would still verify clean.

Accepted residual, INHERITED from `LOG`'s existing semantics rather than introduced here: every
signature runs through `_norm`, which folds case, whitespace and `` ` * _ `` emphasis. The true
collision class is therefore NORMALIZATION-identical — a strict superset of byte-identical — so two
entries differing only in case, wrapping or emphasis are ONE atom, and dropping one of such a pair
is invisible here. The resolver's deliberate no-dedupe keep-both is the mitigation.

Prose / preamble lines are intentionally NOT atoms — legitimate prose edits would look like drops.
The verifier guards structured-content drops (entries, rows, log bullets), which is where "silently
lose an entry" actually bites.
"""
from __future__ import annotations

import hashlib
import re

ENTRY = re.compile(r"^### [A-Z]\d+:\s*(.*)$")
# Accepted residual, older than this module (named round 25): on an ID-row-shaped line with no `|`
# after its name cell, a long run of spaces makes `ROW` backtrack quadratically (0.5 s at 20,000).
ROW = re.compile(r"^\|\s*[A-Z]\d+\s*\|\s*([^|]+?)\s*\|")
# Slug-row atom — a table row whose FIRST cell is a bare backticked slug (`` | `ci-settle` | … | ``).
# The signature is the RAW `` `slug` `` (backticks kept), which `_norm` would strip from an ID-row
# name, so a slug row and an ID row of the same name can never collide. It is its own place key, so
# a one-side edit of the other cells needs no excuse and a one-side rename is a pure removal. Checked
# only after `ROW` fails; independent of `classify`'s own slug regex (the observers stay separate).
SLUG_ROW = re.compile(r"^\|\s*`([a-z0-9][a-z0-9-]*)`")
# Slug-row atom — a table row whose first cell is a lowercase kebab slug holding a letter, PLAIN or
# BOLD (`| slug |`, `| **slug** |`; mismatched markup is admitted too, over-counting being the safe
# direction): the Design Inventory's own row shape, which `keyed-row-insertion` keeps both of. The
# signature is the slug alone, as `ROW`'s is its name cell, so a row whose status flips while it
# moves (`Completion PR pending` -> `Done (completion PR)`) is still one atom. A BACKTICKED slug is
# `SLUG_ROW`'s `row` atom above, never this one (the lookahead keeps the two disjoint whatever the
# scan order), so the kinds never double-count a line. Re-derived here, never shared with
# `keyed_rows`: the observers stay independent. Its classes are disjoint, so it is linear.
PLAIN_SLUG_ROW = re.compile(r"^(?!\|\s*`[a-z0-9][a-z0-9-]*`)\|\s*[*`]*([a-z0-9][a-z0-9-]*)[*`]*\s*\|")
# Heading-entry atom — a keyed entry heading other than a plain `### M48: t` (that is `ENTRY`, which
# is checked first): a placeholder `### M-new-<slug>: t`, a status `### M27 (RESOLVED 2026-09-30): t`
# or an archive slug `` ### `slug` (2026-09-29) ``. Group 1/3 is the key, group 2/4 the title text; a
# parenthetical is no part of it, so `### H6 (OPEN): t` and `### H6 (RESOLVED …): t` are ONE atom.
# Re-derived here, never shared with `keyed_classes`: the observers stay independent.
HEADING_ENTRY = re.compile(
    r"^### (?:([A-Z](?:[0-9]+|-new-[a-z0-9]+(?:-[a-z0-9]+)*))(?:[ \t]+\([^)\n]*\))?:[ \t]*(.*)"
    r"|(`[a-z0-9][a-z0-9-]*`)[ \t]+\([0-9]{4}-[0-9]{2}-[0-9]{2}\)[ \t]*(.*))")
# Log atom — a bold-lead-bullet log entry, dated OR name-keyed. Mirrors classify.LOG_ENTRY's shape,
# re-derived here so the verifier stays independent of the resolver. Group 1 (everything after the
# `- ` marker, i.e. `**<key>** — <title>`) is the signature; the kebab-slug arm excludes file-path
# description bullets, matching what the resolver actually keeps.
# A plain-date bullet (`- 2026-10-16 — …`, no bold lead) is a log atom too; its signature has no `**`.
LOG = re.compile(
    r"^-\s+((?:\*\*(?:`[a-z0-9][a-z0-9-]*`|\d{4}-\d{2}-\d{2})\*\*|\d{4}-\d{2}-\d{2})\s+—.*)$")
# Decision-entry atom — the canonical `### [{skill-name}] <title>` shape prescribed by
# `skills/_shared/auto-mode.md`, and the shape whose drift produced the observed silent pass
# (a 50-entry and a 52-entry `decisions.md` that both parsed to ZERO atoms). Re-derived here
# rather than shared with `classify.py`: the two observers stay independent by design.
DECISION_ENTRY = re.compile(r"^### \[([^\]\s][^\]]*)\]\s+(.+)$")
# There is deliberately NO general-heading regex here any more. A decision-entry body is closed by
# the next DECISION_ENTRY-shaped heading or by EOF, and by nothing else — see the module header's
# orphaned-line section. The two heading rules that preceded it both SHORTENED bodies and both
# manufactured a silent pass: terminating on any ATX truncated `### [a] t` + `#### Sub` + body to an
# EMPTY body (two entries sharing tag+title then collapsed onto one `sha1("")` signature), and
# terminating on ATX level <= 3 let a plain `### Section` banner orphan the whole tail after it.

# There is deliberately NO conflict-marker regex here any more, and no strip that would use one.
# `<<<<<<<`, `=======`, `|||||||` and `>>>>>>>` are ordinary lines to this scanner: they are
# digested into whatever body encloses them, exactly like any other text. Three successive
# formulations of a strip (unconditional; region-narrowed; region-narrowed with a matching-close
# requirement) each shipped a silent drop of real content — see the module header. The shape family
# is not "could this line be decoration?" but "does this line look like decoration?", and no
# predicate over shapes can answer the first question, because a doc QUOTING a conflict and a real
# conflict are byte-identical.
#
# `merge_driver` keeps its own `CONFLICT_MARKERS` tuple for a different job: deciding whether the
# blob it is about to write is still conflicted (a WRITE gate and a message, not an inventory).
# That one is allowed to be shape-only — being wrong there defers a file, it does not hide a line.

# verify's SELF-DESCRIPTION of the kinds it emits, consumed only by the cross-module coverage
# test (Behavior 5b). It names kinds, never shapes: `classify.py` must NOT import it, or the two
# modules' regexes would stop being independently written and drift would become a common-mode
# failure with no signal.
ATOM_KINDS = ("entry", "row", "log", "decision-entry", "heading-entry", "slug-row")


def _norm(s: str) -> str:
    """Signature normalization, INHERITED from `LOG`'s pre-existing semantics.

    Residual, stated precisely rather than glossed: the `[`*_]` class is stripped GLOBALLY, not
    only where it is markdown emphasis, so `_` inside an identifier goes too — `max_retries` and
    `maxretries` normalize alike, as do `` `x` `` and `x`. Whitespace then collapses to single
    spaces, so line structure does not survive either. Two atoms differing ONLY in those respects
    are therefore ONE atom here and dropping one of such a pair is invisible. Narrowing the class
    to emphasis-only would change every existing signature (`log` atoms included) for a
    vanishingly rare gain, so the residual is accepted and documented; the resolver's deliberate
    no-dedupe keep-both is the mitigation. The body digest folds in the body's NON-BLANK LINE
    COUNT to claw back the part of this that hurt most (see `_digest`).
    """
    s = re.sub(r"[`*_]", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _digest(body: list[str]) -> str:
    """A short content fingerprint of a decision entry's body, NOT a security primitive: it only
    distinguishes two entries that share a tag and title, and an adversary who can rewrite the
    merged text can drop the whole entry outright. `usedforsecurity=False` says so explicitly.

    The body's NON-BLANK line count is folded in ahead of the normalized text. `_norm` joins the
    body with single spaces, so line structure is otherwise erased; the count restores a cheap,
    order-free discriminator between two entries whose bodies normalize alike but are structurally
    different — including the degenerate empty-body case a truncating block scan used to
    manufacture. BLANK lines are excluded DELIBERATELY: whether a block is trailed by a separator
    blank line depends on whether another entry follows it, and that changes across a merge, so a
    raw line count fires a false `DROPS_DETECTED` on every last-entry-in-file atom (observed —
    `test_auto_safe_logs.py::test_decisions_log_both_sides_append_auto_resolves`).
    """
    nonblank = sum(1 for ln in body if ln.strip())
    normalized = f"{nonblank}\x00{_norm(' '.join(body))}".encode("utf-8")
    return hashlib.sha1(normalized, usedforsecurity=False).hexdigest()[:12]


def _esc(s: str) -> str:
    """Escape a signature FIELD so the `|`-joined decision-entry signature is unambiguous.

    Without this, `### [a|b] c` and `### [a] b|c` produce the SAME `tag|title|digest` string and
    collide into one atom — so dropping one of the pair verifies clean. `%` is escaped first, so
    the mapping is injective and reversible.
    """
    return s.replace("%", "%25").replace("|", "%7C")


def atoms(text: str) -> dict[tuple[str, str], str]:
    """Return {(kind, signature): kind} for every structured atom in `text`.

    TWO scans run over the SAME lines, writing into ONE dict:

    1. the per-line `ENTRY` / `HEADING_ENTRY` / `ROW` / `SLUG_ROW` / `PLAIN_SLUG_ROW` / `LOG` kind scan, and
    2. a `decision-entry` BLOCK scan (a `### [tag] title` heading plus its body, closed by the
       next `### [tag] title` heading or EOF — and by NOTHING else).

    **Neither scan is fence-aware, and that is the contract, not an omission.** The result is a
    SUPERSET of what any markdown-aware scan would return: every line the naive scan sees, this
    one sees. See the module header for why the asymmetry between over- and under-counting makes
    that the only safe direction — an atom missing from `pre` makes its own deletion invisible,
    while a spurious atom at worst defers the file to a human.

    The consequence, stated plainly because it IS a behaviour and not an accident: a doc's own
    fenced illustrative example of an atom shape — ```` ```markdown ```` around `### L9: Example
    entry`, `| D3 | example row |`, `- **2024-01-01** — example log` — is counted as a REAL atom.
    Reword that example on one side of a merge and this verifier reports `DROPS_DETECTED`, the
    driver refuses the mechanical resolution, and a human resolves the file. That is the correct
    outcome for a drop detector, and it is what `origin/master` did before any fence machinery
    existed. Three attempts to suppress that noise each reintroduced the silent pass instead; the
    noise is the price of the guarantee.

    The block scan is not markdown-aware in ANY way, headings included:

    * **No heading terminates a body except the next entry's own.** A `#### Sub-heading` is BODY;
      so is a plain `### Section` or `## Foo`. Both earlier rules SHORTENED bodies and both shipped
      a silent pass. Closing on any ATX truncated the atom to an empty body (two entries onto one
      `sha1("")` signature). Closing on ATX level <= 3 — whose docstring claimed it "only ever
      LENGTHENS a body, so it cannot hide a block", which was FALSE — let a plain `### Section`
      banner, e.g. one inside a fenced shell script quoted in an entry's body, close the block
      early and ORPHAN every line from there to the next real entry: covered by no signature, so
      deleting one of those lines verified clean (module header, orphaned-line section).

      Longer bodies have a real cost, stated rather than glossed: an intervening `## Section`
      heading is now digested into the PRECEDING entry, so editing that heading moves that entry's
      signature and can raise `DROPS_DETECTED` on a file where nothing was dropped. That is a
      deferral to a human — the same fail-safe direction as the fenced-example over-count — and it
      is strictly preferable to real content no signature covers.

    NOTHING IS STRIPPED. `text.splitlines()` is the whole preprocessing step. Merge markers are
    body content like any other line, so an entry that survives a merge wrapped in
    `<<<<<<< / ======= / >>>>>>>` digests DIFFERENTLY from the same entry on its input side and
    `verify()` reports a drop for it. That is the accepted phantom, and it is the deliberate price
    of the guarantee: three strips that tried to suppress it each removed real content from a
    digest instead, and a line outside every digest is a line whose deletion verifies clean. The
    phantom only ever arises on a blob that still carries markers — i.e. one a human must open
    anyway — and `merge_driver` words that outcome as "could not verify a still-conflicted blob".

    The block scan deliberately does **NOT** skip lines the per-line scan already consumed, so a
    decision-entry body line that is itself `LOG`-shaped yields BOTH a standalone `log` atom and
    a contribution to the enclosing block's digest. That double-capture is intended, not an
    oversight: 3 of 11,702 entry-body lines across this repo's real `decisions.md` files already
    match `LOG`, so skipping consumed lines would DELETE atoms `atoms()` emits today — weakening
    the verifier on real files. Keys never collide because the key is `(kind, sig)` and the kinds
    differ. Double-capture is monotone in the safe direction: it can only add atoms, hence only
    report more drops, and because the resolver keeps decision entries VERBATIM a surviving entry
    carries its nested bullet with it, so it raises no false drop.

    Measured on the real corpus at the commit that removed fence-awareness: 103 `decisions.md`,
    93 parsing, 1718 `decision-entry` atoms — UNCHANGED, because no `decisions.md` fences an atom
    shape. Repo-wide across all 831 `.md` files, `entry` (170) and `row` (516) are unchanged,
    `log` rises 333 -> 336 and `decision-entry` 1730 -> 1738. Every one of the 11 reappearing
    atoms is a doc's own fenced worked EXAMPLE of the shape — 4 in `skills/_shared/auto-mode.md`
    (the prescribed `### [{skill-name}] <title>` template itself), 3 in
    `completed-tp-designs/living-doc-line-format/detailed-design.md` (the migrated `## History`
    bullet format), 4 more scattered across skill docs — and none is on the mechanical lane. The
    check that matters is the other direction: ZERO atoms were lost on any of the 831 files, and
    no existing signature changed.

    Re-measured when the heading terminator was removed: every COUNT is unchanged — 103
    `decisions.md`, 93 parsing, 1718 corpus atoms; repo-wide across 837 `.md` files `entry` 170,
    `row` 516, `log` 336, `decision-entry` 1738 — and no file lost an atom or saw its atom count
    fall. What moved is DIGESTS: on 31 files a `##`/`###` section heading that used to close a
    block is now body, so the preceding entry's signature changed. That is the expected shape of
    the change (longer bodies, same atoms). The A/B against `origin/master` still holds on all 837
    files: 0 lost, 100 grew, 737 identical.
    """
    out: dict[tuple[str, str], str] = {}
    lines = text.splitlines()               # the ONLY preprocessing — no line is ever removed

    for line in lines:
        m = ENTRY.match(line)
        if m and _norm(m.group(1)):
            out[("entry", _norm(m.group(1)))] = "entry"
            continue
        m = HEADING_ENTRY.match(line)
        if m:
            sig = f"{m.group(1) or m.group(3)}|{_norm(m.group(2) or m.group(4) or '')}"
            out[("heading-entry", sig)] = "heading-entry"
            continue
        m = ROW.match(line)
        if m and _norm(m.group(1)):
            out[("row", _norm(m.group(1)))] = "row"
            continue
        m = SLUG_ROW.match(line)
        if m:
            out[("row", f"`{m.group(1)}`")] = "row"
            continue
        m = PLAIN_SLUG_ROW.match(line)
        if m and re.search("[a-z]", m.group(1)):
            out[("slug-row", m.group(1))] = "slug-row"
            continue
        m = LOG.match(line)
        if m and _norm(m.group(1)):
            out[("log", _norm(m.group(1)))] = "log"

    open_block: tuple[str, str] | None = None      # (normalized tag, normalized title)
    body: list[str] = []

    def _close() -> None:
        if open_block is not None:
            tag, title = open_block
            sig = f"{_esc(tag)}|{_esc(title)}|{_digest(body)}"
            out[("decision-entry", sig)] = "decision-entry"

    for line in lines:
        m = DECISION_ENTRY.match(line)
        if m and _norm(m.group(1)) and _norm(m.group(2)):
            _close()
            open_block, body = (_norm(m.group(1)), _norm(m.group(2))), []
            continue
        # NOTHING ELSE closes the block. Every line from an entry's heading to the next entry's
        # heading (or EOF) is digested into that entry's body, headings of any level included, so
        # no line after the first entry can be orphaned out of every signature.
        if open_block is not None:
            body.append(line)
    _close()
    return out


def _nonblank(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())
