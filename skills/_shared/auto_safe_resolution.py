#!/usr/bin/env python3
"""auto_safe_resolution.py -- the shared AUTO-SAFE **byte-production path** used by the merge-back
producer (`merge_driver.py`) and the base-sync certificate verifier (Phase 2's `base_sync_cert.py`).
Both sides call `resolve_conflict_bytes` on identical inputs and must produce byte-identical output,
or the carry's soundness proof (RME condition 5) does not hold. THAT part is one definition.

ADMISSION -- *which paths* may be mechanically resolved at all -- is deliberately NOT one
definition. The two sides run DIFFERENT predicates, and this module exports both:

  * producer  `merge_driver.merge_back` gates on `is_auto_safe_path(path)`: exact `AUTO_SAFE_PATHS`
    membership **OR** a design's `three-pillars-docs/tp-designs/<slug>/decisions.md`;
  * verifier  `base_sync_cert._cond3_allowlist` gates on `path not in AUTO_SAFE_PATHS`: exact
    membership ONLY -- it does **not** admit `decisions.md`.

This divergence is a design decision (task 1.9), not drift. The mechanical lane was widened for the
producer, while RME condition 3 -- the STRICT certification conjunct -- was left on the narrow
exact-membership set, because widening cond3 changes what the certificate proves. The consequence,
stated plainly: a merge whose conflict set includes a design's `decisions.md` FAILS cond3, so that
link cannot be certified strictly via cond3 and falls through to the RELAXED carry lane instead.
The producer still resolves the file; it just does not earn a strict certificate for it.

Filed as known-issue **M20**. Do NOT "unify" these two predicates as a cleanup -- read M20 first;
it is a design change, not a fix.

Re-exports `RESOLVED`/`DEFER` from `resolve.py` via the `Path(__file__)`-relative sys.path shim
into `tp-merge-from-main/scripts/` (precedent: `proof_predicate.py` -> `tp-pr-iterate/scripts`).

Bytes-explicit policy (ONE policy, genuinely both sides -- unlike admission, above): blob text is
acquired as raw bytes via
subprocess **binary capture, never `text=True`**, then decoded strict UTF-8
(`decode_blob_strict`); a decode failure is the caller's problem to handle (producer defers the
file, verifier fails the link -- neither papers over it). Tempfiles for `git merge-file` are
written as raw UTF-8 bytes, never via a text-mode write.

What that buys, stated exactly (the earlier blanket "CRLF bytes survive verbatim" was FALSE for
the reason below, and is now true for the reason after it):

  * **I/O layer** -- binary capture + binary write means no universal-newline translation at any
    subprocess or file boundary. Necessary, not sufficient.
  * **Line round trip** -- `resolve_conflict_bytes_detail` splits the conflict text (in
    `classify.parse_conflict`) and rejoins it with `"\\n"`, so losslessness depends on the SPLIT.
    `str.splitlines()` -- what it used to use -- breaks on `\\r`, `\\f`, `\\x0b`, `\\x1c`-`\\x1e`,
    U+0085 and U+2028/9 as well, so it silently rewrote every CRLF terminator in the WHOLE FILE to
    LF (well outside the conflicted region, and invisible to the verifier, whose own `_norm` folds
    the difference away) and would cut a prose line carrying any of those characters in two.
    `parse_conflict` now splits on `"\\n"` alone, making `"\\n".join(split("\\n")) == text` an
    exact identity: a CRLF terminator rides through as a trailing `\\r` on the line's own text, and
    the exotic separators are ordinary characters.
  * **NOT preserved, by design** -- a file with NO final newline gains one (the trailing-`"\\n"`
    normalization below), and `git merge-file`'s own output is whatever git chose to emit. Encoding
    is UTF-8 or the caller gets a `UnicodeDecodeError`; nothing is transcoded.
"""
from __future__ import annotations

import re
import secrets
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_MERGE_SCRIPTS = _HERE.parent / "tp-merge-from-main" / "scripts"
if str(_MERGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MERGE_SCRIPTS))

from decisions_union import union_decisions  # noqa: E402
from resolve import resolve_file, RESOLVED, DEFER  # noqa: E402,F401

# The exact-membership AUTO-SAFE set -- exactly merge_driver.DEFAULT_LIVING_DOCS. This is
# the set `base_sync_cert._cond3_allowlist` tests directly; the producer tests the WIDER
# `is_auto_safe_path` instead. See the header + M20 -- the asymmetry is deliberate.
#
# `product_roadmap_archive.md` is an append-only living doc (its rows and `Recent completions`
# bullets are the DONE rows rolled out of `product_roadmap.md`, and base-syncs keep inserting
# keyed log-entry / slug bullets into it), so it earns the same AUTO-SAFE treatment as the
# live roadmap. It is deliberately NOT a `decisions.md`-style extension of the lane: the lane
# is an exact path list, and widening it here is a documented design choice (the seed's step 2:
# `*_archive.md` / `known_issues_resolved.md` are append-only living docs too).
# merge_driver imports THIS as DEFAULT_LIVING_DOCS once it refactors onto this module; a
# single-definition-guard test pins the equality regardless of which side owns the literal.
AUTO_SAFE_PATHS = frozenset({
    "three-pillars-docs/known_issues.md",
    "three-pillars-docs/known_issues_resolved.md",
    "three-pillars-docs/known_issues_low.md",      # live Low issues (skill-context-diet D5b)
    "three-pillars-docs/known_issues_archive.md",  # cold open-issue bodies (append-only)
    "three-pillars-docs/product_roadmap.md",
    "three-pillars-docs/product_roadmap_archive.md",
    "three-pillars-docs/architecture.md",
    "three-pillars-docs/architecture_archive.md",
    "three-pillars-docs/vision.md",
})


# A design's autonomous-run decision log. Admitted to the MECHANICAL lane (not to
# `AUTO_SAFE_PATHS`, which stays an exact-membership set) because every `/tp-run-full-design` fold
# conflicts on it BY CONSTRUCTION -- the orchestrator appends on `tp/{slug}` while workers append
# on `candidate/{slug}/single` -- so it was a guaranteed hand-resolve on every autonomous run.
# `[^/\n]+` is exactly ONE path segment and the pattern is matched with `fullmatch`, so a nested
# `a/b/decisions.md`, a sibling `design.md`/`lock.json`, a `completed-tp-designs/...` archive path
# and any `..`-bearing path are all rejected. `\n` is excluded from the segment class and
# `fullmatch` (not `$`, which also matches BEFORE a trailing newline) is used deliberately: with
# `^...$` + `[^/]+` a trailing-newline path like `".../slug/decisions.md\n"` slipped through, which
# contradicted the "fully anchored" claim this comment makes. The slug segment is additionally
# rejected when it is `.` or `..` -- `[^/\n]+` alone admits `tp-designs/../decisions.md`, which
# normalizes OUT of the designs tree. This is the one KNOWN drifted shape, moved onto the lane
# where the verifier's `UNVERIFIABLE` verdict can actually fire.
_DESIGN_DECISIONS_RE = re.compile(r"three-pillars-docs/tp-designs/([^/\n]+)/decisions\.md")


def is_auto_safe_path(path) -> bool:
    """True iff `path` may be mechanically resolved: exact `AUTO_SAFE_PATHS` membership OR a
    design's `decisions.md`. Total -- any exception (non-str input included) fails closed."""
    try:
        if path in AUTO_SAFE_PATHS:
            return True
        m = _DESIGN_DECISIONS_RE.fullmatch(path)
        return bool(m) and m.group(1) not in (".", "..")
    except Exception:
        return False


def decode_blob_strict(raw: bytes) -> str:
    """Strict-UTF-8 decode of raw git blob bytes acquired via binary subprocess capture.

    No newline translation ever happens on this path -- the caller captured `raw` without
    `text=True`. Raises `UnicodeDecodeError` on undecodable content; that is deliberate: the
    caller catches it and defers (producer) / fails (verifier), never silently substitutes.
    """
    return raw.decode("utf-8")


class MergeFileError(RuntimeError):
    """`git merge-file` failed (exit status outside its documented conflict-count range).

    Raised -- never swallowed -- because the failure mode it guards is TOTAL CONTENT LOSS: a
    failed `merge-file` writes NOTHING to stdout, and an empty conflict text resolves to a
    RESOLVED, marker-free, one-newline "merge" that the verifier cannot distinguish from a clean
    zero-drop result on an atom-less living doc. Both consumers fail closed on it: the producer
    (`merge_driver.resolve_living_doc`) defers the file untouched, and the Phase-2 certificate
    verifier fails the link.
    """


class ConflictCountMismatch(MergeFileError):
    """The conflict PARSE found a different number of regions than `git merge-file` reported.

    `merge-file`'s exit status is its own count of the conflicts it wrote (when below the 127 cap).
    The labelled parse (`conflict_parse._scan_labelled`) can only fall SHORT of it -- no content
    line can equal a nonce-labelled marker, and a region it could not read whole stays clean
    text -- so a mismatch means some region was not parsed, and nothing downstream of the parse
    can be trusted for this file. A `MergeFileError` subclass on
    purpose: both consumers already fail closed on that type (the producer defers the file, the
    certifier's catch-all fails the link).
    """


@dataclass(frozen=True)
class Diff3:
    """One `git merge-file -p --diff3` run: its output, the marker labels it was given, and its
    exit status read as a conflict count (`None` when unknown, i.e. at or above the 127 cap)."""
    text: str
    labels: tuple
    conflicts: int | None


def _fresh_labels(*texts: str) -> tuple[str, str, str]:
    """`(ours, base, theirs)` marker labels carrying a random nonce that NONE of `texts` contains.

    Checked, not merely improbable: a nonce found in any input is redrawn, so no content line of
    the three inputs can equal a labelled marker line. The nonce is lowercase hex, so it cannot
    spell an uppercase ID token (`L4`) either."""
    while True:
        nonce = secrets.token_hex(16)
        if not any(nonce in t for t in texts):
            return (f"ours-{nonce}", f"base-{nonce}", f"theirs-{nonce}")


def _diff3_conflict(*, base: str, ours: str, theirs: str) -> Diff3:
    """Build a `git merge-file --diff3` conflict block from the three versions.

    Lifted from `merge_driver.diff3_text` (parameter order corrected -- see
    `resolve_conflict_bytes`). Bytes-explicit: tempfiles are written as raw UTF-8 bytes (never a
    text-mode write) and the subprocess output is captured binary (never `text=True`), then
    strict-UTF-8 decoded -- so CRLF bytes and encoding survive this step byte-for-byte.

    The markers are LABELLED (`-L`) with a per-call nonce (`_fresh_labels`), so the parse can bind
    each structural marker to the exact line merge-file wrote instead of to a prefix any quoted
    example also has (round 17, F1/F2). The labels appear only on marker lines, i.e. only in the
    text of a DEFERRED region; a RESOLVED result is built from content lines alone.

    The exit status is CHECKED, not discarded. `git merge-file` documents its status as the number
    of conflicts left (capped at 127), with a NEGATIVE value (surfacing as 255 through the shell)
    meaning "error". Anything outside `0..127` is therefore an error and raises `MergeFileError`
    rather than returning the empty stdout that an error produces.
    """
    labels = _fresh_labels(base, ours, theirs)
    with tempfile.TemporaryDirectory() as d:
        p_ours, p_base, p_theirs = Path(d) / "ours", Path(d) / "base", Path(d) / "theirs"
        p_ours.write_bytes(ours.encode("utf-8"))
        p_base.write_bytes(base.encode("utf-8"))
        p_theirs.write_bytes(theirs.encode("utf-8"))
        r = subprocess.run(
            ["git", "merge-file", "-p", "--diff3", "-L", labels[0], "-L", labels[1],
             "-L", labels[2], str(p_ours), str(p_base), str(p_theirs)],
            capture_output=True,
        )
        if not 0 <= r.returncode <= 127:
            raise MergeFileError(
                f"git merge-file failed (exit {r.returncode}): "
                f"{r.stderr.decode('utf-8', 'replace').strip()[:200]}")
        return Diff3(decode_blob_strict(r.stdout), labels,
                     r.returncode if r.returncode < 127 else None)


def _diff3_conflict_text(*, base: str, ours: str, theirs: str) -> str:
    """The conflict TEXT of `_diff3_conflict` alone (labelled markers included)."""
    return _diff3_conflict(base=base, ours=ours, theirs=theirs).text


def diff3_conflict(*, base: str, ours: str, theirs: str) -> Diff3:
    """The diff3 step ALONE, exported for the index-stage validation gate
    (`tp-merge-from-main/scripts/stage_oracle.py`), which re-derives the conflict it cross-checks
    against the stages. A pure alias -- same function, same keyword-only signature, no behaviour of
    its own -- so the RME-certified byte path below is untouched by its existence. Each call draws
    its own nonce, so the gate's text differs from the byte path's on marker lines only.
    """
    return _diff3_conflict(base=base, ours=ours, theirs=theirs)


def check_conflict_count(d: Diff3, parsed_hunks: int) -> None:
    """Raise `ConflictCountMismatch` unless the parse found exactly the regions merge-file wrote.
    At the 127 cap the count is unknown and only `parsed_hunks >= 127` is consistent with it."""
    if d.conflicts is None:
        if parsed_hunks < 127:
            raise ConflictCountMismatch(
                f"git merge-file reported 127+ conflicts but the parse found {parsed_hunks}")
    elif parsed_hunks != d.conflicts:
        raise ConflictCountMismatch(
            f"git merge-file reported {d.conflicts} conflict(s) but the parse found "
            f"{parsed_hunks} -- a region was not read whole, so the file is not trusted")


def resolve_conflict_bytes(*, base: str, ours: str, theirs: str, path=None) -> tuple[str, str]:
    """The byte-production path BOTH producer (`merge_driver`) and verifier (`base_sync_cert`,
    Phase 2) execute -- the single shared definition RME condition 5 certifies against. Scope note:
    what is shared here is the BYTES, not the admission predicate. Condition 3 decides *whether a
    path is eligible* with `path not in AUTO_SAFE_PATHS`, which is strictly narrower than the
    producer's `is_auto_safe_path`; see this module's header and known-issue M20.

    `git merge-file -p --diff3` over tempfiles (nonce-labelled markers) -> `resolve.resolve_file`
    (labelled parse) -> conflict-count check -> `"\\n".join(lines)` + trailing-`"\\n"`
    normalization -> `(file_status, merged_text)`. RESOLVED output never carries a LABELLED marker
    line (every region was replaced by content lines), so it is independent of the nonce and
    byte-identical across runs; DEFER output carries the per-call labels and is not (it never
    was: the labels used to be random tempfile paths).

    Keyword-only (`*`): this function's parameter order (`base, ours, theirs`) deliberately
    differs from `merge_driver.diff3_text`'s legacy `(ours, base, theirs)`, so ANY positional
    call -- and hence any positional swap -- raises `TypeError` immediately at the call site
    rather than silently miscomputing.

    A pure delegate to `resolve_conflict_bytes_detail`, forwarding `path` (its docstring names the
    one lane `path` opens); with `path=None` the certified byte path is UNCHANGED.
    """
    status, merged, _mechanical = resolve_conflict_bytes_detail(
        base=base, ours=ours, theirs=theirs, path=path)
    return status, merged


def resolve_conflict_bytes_detail(
        *, base: str, ours: str, theirs: str, path=None) -> tuple[str, str, bool]:
    """`resolve_conflict_bytes` plus the per-file fact "the verifier must NOT read zero atoms as a
    pass on this file".

    `path` opens ONE lane: a design-dir `decisions.md` (`_DESIGN_DECISIONS_RE`, slug not `.`/`..`)
    first tries `union_decisions`; text back is `(RESOLVED, text, True)` before diff3, None falls
    through. Every other path, and `path=None`, takes the diff3 route unchanged.

    The third element is `any(r.status == RESOLVED for r in results) or not conflict.strip()` --
    a per-file **OR across the file's hunks**, not per-hunk, plus one narrow blank-input arm:

    * `any(...)` -- a file carrying one mechanical hunk and one deferred hunk counts as
      mechanically-applied. Relative to a per-hunk `all(...)`, the OR makes `UNVERIFIABLE` fire
      MORE often, never less, so no per-hunk threading is needed.
    * `not conflict.strip()` -- BLANK conflict text is "the resolver was handed nothing to
      examine". `resolve_file("")` returns `(RESOLVED, [], [])` and normalizes to a one-newline
      "merge"; on an atom-less living doc that verified VERIFIED and the whole file was
      overwritten. `MergeFileError` now intercepts the failed-`merge-file` route into that shape,
      so this arm is defence in depth against any OTHER way an in-range exit status yields empty
      stdout -- and it covers whitespace-only stdout too, which the earlier arm did not.

    The arm used to read `not results` -- "the resolver found no hunks" -- which is STRICTLY
    BROADER and wrong at the edge. `results == []` is also the shape when `git merge-file` exits 0
    and merges all three sides cleanly with real content and no conflict hunks: nothing was
    mechanically resolved, `resolve_file` passed git's own output through verbatim (the
    `parse_conflict`/`resolve_file` clean-region round trip is exact), and there is nothing for a
    zero-drop verifier to certify -- exactly the status of any non-conflicted file in the merge.
    Reporting `mechanical_applied=True` there made `verify()` return `UNVERIFIABLE` on every
    atom-less allowlisted doc that merged cleanly. `three-pillars-docs/vision.md` parses to ZERO
    atoms today, so the driver deferred it permanently and `_cond5_resolve` failed the strict RME
    link -- silently retiring `vision.md` from the AUTO-SAFE set `SKILL.md` advertises. Narrowing
    to blank input restores it without weakening the fail-closed arm.

    NOTE the direction claim above is about the `any`-vs-`all` choice ONLY. It is NOT true that
    widening the fact can only help: `mechanical_applied=False` DISARMS `UNVERIFIABLE`, so the
    blank-input case has to be stated explicitly rather than inferred from the OR -- and,
    symmetrically, an over-broad arm is not free either.

    `verify.verify(..., mechanical_applied=<this fact>)` needs it to tell "I examined atoms and
    none were lost" from "I examined nothing".
    """
    m = _DESIGN_DECISIONS_RE.fullmatch(path) if isinstance(path, str) else None
    if m and m.group(1) not in (".", ".."):
        union = union_decisions(base, ours, theirs)
        if union is not None:
            return RESOLVED, union, True
    d = _diff3_conflict(base=base, ours=ours, theirs=theirs)
    conflict = d.text
    status, lines, results = resolve_file(conflict, labels=d.labels)
    check_conflict_count(d, len(results))
    merged = "\n".join(lines)
    if not merged.endswith("\n"):
        merged += "\n"
    return status, merged, (any(r.status == RESOLVED for r in results) or not conflict.strip())


def deferred_hunk_reasons(*, base: str, ours: str, theirs: str) -> list[str]:
    """Why each region the byte path left for the human was deferred: `"<class>: <reason>"` per
    DEFER hunk, in file order (round 19, M-e). A REPORTING helper: it re-derives the conflict from
    the same three blobs (merge-file is deterministic on identical inputs; only the marker nonce
    differs) and never feeds the bytes `resolve_conflict_bytes` returns, so the producer/certifier
    byte identity does not depend on it. It raises what `_diff3_conflict` raises.
    """
    d = _diff3_conflict(base=base, ours=ours, theirs=theirs)
    return [f"{r.label}: {r.reason}"
            for r in resolve_file(d.text, labels=d.labels)[2] if r.status != RESOLVED]
