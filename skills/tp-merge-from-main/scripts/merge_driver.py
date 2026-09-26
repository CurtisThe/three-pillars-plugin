#!/usr/bin/env python3
"""Merge driver for `/tp-merge` — merge a base ref into the current worktree branch and
auto-resolve the AUTO-SAFE living-doc conflict classes behind the zero-drop verifier, deferring
everything else to a human.

Flow (design.md §Behavior):
  1. `git merge --no-commit --no-ff <base_ref>` inside `repo` (a worktree on the design branch).
  2. For each conflicted file:
       - living doc  -> reconstruct (base, ours, theirs) from index stages, build a diff3 block,
                        classify -> resolve -> verify.
       - everything else (code/prose files) -> DEFER unconditionally.
  3. Staging policy (load-bearing safety): a file is staged ONLY when
       file_status == RESOLVED  AND  verifier reports zero drops  AND  no conflict marker remains.
     Otherwise the conflict markers are left in the worktree for a human, and the file is reported
     as deferred with a reason. The driver NEVER commits and NEVER pushes — those are the skill's
     human-gated steps after tests pass.

The driver returns a structured report; it does not decide whether to commit. `--abort` cleans up.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage_oracle import index_disagreement  # noqa: E402
from verify import UNVERIFIABLE, verify  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
from auto_safe_resolution import (  # noqa: E402
    AUTO_SAFE_PATHS as DEFAULT_LIVING_DOCS,
    MergeFileError,
    RESOLVED,
    decode_blob_strict,
    deferred_hunk_reasons,
    is_auto_safe_path,
    resolve_conflict_bytes_detail,
)

CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


def _still_conflicted(text: str) -> bool:
    """Does `text` still carry git's own conflict BRACKETS (`<<<<<<<` / `>>>>>>>`) at line start?

    Used ONLY to word an outcome, never to decide one — a false positive changes a sentence. The
    brackets alone, not `=======`/`|||||||`: those two are ordinary markdown (a setext underline,
    a row of empty cells) and matching them would call an unconflicted file conflicted.

    The verifier deliberately strips NOTHING (`verify_atoms.py`'s header), so a blob that still
    carries markers digests differently from its clean input sides and `verify()` reports
    `DROPS_DETECTED` on it even when every atom is present. Naming that "content drop" sent the
    operator hunting for lost text; the honest reading is "this blob is still conflicted, so it
    could not be verified". The OUTCOME is identical either way — defer, touch nothing — which is
    why fixing the wording here rather than teaching the scanner to ignore markers is the whole
    trade: a phantom costs a sentence, a strip cost real content.

    Round 10: this predicate is shape-only and cannot tell quoted syntax from a real region, so it
    no longer SUPPRESSES the drop report — the caller states both facts and the missing-atom count
    survives a True answer. See the reason-wording block in `resolve_living_doc`.
    """
    return any(ln.startswith(("<<<<<<<", ">>>>>>>")) for ln in text.splitlines())


@dataclass
class FileOutcome:
    path: str
    kind: str            # "living-doc" | "other"
    action: str          # "auto-resolved" | "partially-resolved" | "deferred"
    reason: str = ""
    classes: list = field(default_factory=list)
    resolved_classes: list = field(default_factory=list)   # mechanical hunks resolved in place
    deferred_classes: list = field(default_factory=list)   # semantic hunks left for the human
    dropped: list = field(default_factory=list)
    renumbered: dict = field(default_factory=dict)


@dataclass
class MergeReport:
    base_ref: str
    merged_clean: bool                       # True if `git merge` had no conflicts at all
    conflicted: list = field(default_factory=list)
    auto_resolved: list = field(default_factory=list)        # fully resolved + staged
    partially_resolved: list = field(default_factory=list)   # mechanical done, semantic markers remain
    deferred: list = field(default_factory=list)             # untouched, human owns it
    outcomes: list = field(default_factory=list)             # [FileOutcome as dict]
    needs_human: bool = False                # True if anything is not fully auto-resolved
    merge_failed: bool = False               # `git merge` failed for a NON-conflict reason
    merge_error: str = ""                    # git's own stderr/stdout when `merge_failed`

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, indent=2)


def _git(repo: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """`LC_ALL=C` is load-bearing, not tidiness. `merge_back` classifies a failed `git merge` by
    looking for the literal ASCII substring `CONFLICT` in git's own output; under a git built with
    NLS and a non-English locale that word is TRANSLATED, so the substring test silently answers
    the wrong question. Pinning the locale makes the only message this module reads deterministic.
    It is pinned for EVERY call rather than just the merge so no later parse inherits the bug."""
    env = {**os.environ, "LC_ALL": "C"}
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=check,
                          env=env)


class ConflictScanFailed(RuntimeError):
    """`git diff --diff-filter=U` itself failed, so the unmerged-index set is UNKNOWN.

    Raised rather than swallowed because "no conflicts" and "I could not tell" are different
    answers and every caller here treats them differently. Under `check=False` any failure — a
    corrupt or locked index, a transient I/O error, `repo` not being a work tree at all — returned
    `[]`, i.e. the *reassuring* answer. The `merge_failed` guard differences a PRE-merge snapshot
    against a POST-merge call, so a failed PRE call reading as "clean" made a stale, unrelated
    merge's leftover unmerged entries look like entries THIS invocation created: the guard fell
    through to the per-file resolve loop and resolved another merge's conflicts while attributing
    them to the base ref this caller asked for — the exact misattribution the differencing exists
    to prevent. An exception makes the unknown answer impossible to mistake for the empty one.
    """


def conflicted_files(repo: str) -> list[str]:
    r = _git(repo, "diff", "--name-only", "--diff-filter=U", check=False)
    if r.returncode != 0:
        # `git diff --name-only` does not use the exit code to report findings (no `--exit-code`),
        # so non-zero is unambiguously a failure and never "there were conflicts".
        raise ConflictScanFailed(
            f"git diff --diff-filter=U failed in {repo} (exit {r.returncode}): "
            f"{(r.stderr or r.stdout).strip()[:200]}")
    return [p for p in r.stdout.splitlines() if p.strip()]


def _stage_blob(repo: str, stage: int, path: str) -> str | None:
    """Return the blob content for a merge stage, or None if that stage is absent.

    Distinguishing absent (stage missing → add/add or add/delete) from present-but-empty
    (a legitimately empty file) matters: the former must defer, the latter is a normal merge.
    Binary subprocess capture (never `text=True` — no universal-newline translation) then
    strict-UTF-8 decode via the shared `auto_safe_resolution` policy; undecodable (non-UTF-8)
    content raises `UnicodeDecodeError` — the caller defers the file.
    """
    r = subprocess.run(["git", "-C", repo, "show", f":{stage}:{path}"], capture_output=True)
    if r.returncode != 0:
        return None
    return decode_blob_strict(r.stdout)


def resolve_living_doc(repo: str, path: str) -> FileOutcome:
    try:
        base = _stage_blob(repo, 1, path)
        ours = _stage_blob(repo, 2, path)
        theirs = _stage_blob(repo, 3, path)
    except UnicodeDecodeError:
        return FileOutcome(path, "living-doc", "deferred",
                           reason="undecodable (non-UTF-8) content — needs human")
    if ours is None or theirs is None:   # add/delete or rename — a content side is absent
        return FileOutcome(path, "living-doc", "deferred",
                           reason="add/delete conflict (a side is absent) — needs human")
    if base is None:                     # add/add — both sides created the file, no common ancestor
        return FileOutcome(path, "living-doc", "deferred",
                           reason="add/add conflict (no common base) — needs human")

    # ONE shared byte-production path — the same function the Phase-2 verifier re-runs.
    try:
        status, merged, mechanical_applied = resolve_conflict_bytes_detail(
            base=base, ours=ours, theirs=theirs)
    except (MergeFileError, OSError, UnicodeDecodeError) as e:
        # `MergeFileError`: `git merge-file` itself failed. Its stdout is EMPTY on failure, which
        # used to resolve to a RESOLVED, marker-free one-newline "merge" — total content loss
        # reported as clean.
        # `OSError`: tempfile creation/write or the `subprocess.run` spawn failed (ENOSPC, EMFILE,
        # a read-only TMPDIR, git missing from PATH). `UnicodeDecodeError`: `merge-file` emitted
        # non-UTF-8 bytes. Both are caught HERE rather than allowed to escape mid-loop: an escape
        # from `merge_back`'s per-file loop would abort AFTER earlier files were already written and
        # staged, leaving a half-staged merge with no `MergeReport` at all. Deferring this one file
        # keeps the report total and every other file's outcome recorded.
        return FileOutcome(path, "living-doc", "deferred",
                           reason=f"conflict reconstruction failed — needs human "
                                  f"({type(e).__name__}: {e})")

    # Total-content-loss guard, BEFORE the verifier and independent of it: never write a
    # whitespace-only result over a file that had content on either side. The verifier's atom
    # inventory cannot catch this on an atom-less living doc (0 atoms in, 0 atoms out, no drop to
    # report), so this is a separate, shape-independent backstop on the same failure class.
    #
    # Reachability, stated precisely because it was overclaimed before: the `MergeFileError` guard
    # above now intercepts the *failed*-merge-file route into this shape, so on the ordinary
    # conflict paths this guard is defence-in-depth. It is NOT unreachable, though — it also fires
    # when `merge-file` SUCCEEDS (exit 0) and legitimately resolves to empty, e.g. stage 2 is an
    # emptied file while stage 3 still carries the base content. `test_merge_driver.py::
    # test_whitespace_only_resolution_over_a_nonempty_side_is_deferred` drives exactly that arm.
    if not merged.strip() and (ours.strip() or theirs.strip()):
        return FileOutcome(path, "living-doc", "deferred",
                           reason="resolver produced empty output for a non-empty file "
                                  "— left untouched for human")

    # THE INDEX IS THE ORACLE FOR THE TEXT PARSE. Every mechanical result this driver is about to
    # accept was cut out of the conflict text by shape-matching git's marker grammar inside content
    # that can legitimately contain it, and this is the one place in the pipeline where the
    # unambiguous source of the same structure is in hand: the three index stages, already read
    # above. If the parse put a line on a side the stages say it did not come from, the region was
    # cut in the wrong place — S-J1's misrouted `ours` content sitting in `h.base`, invisible to
    # every text-shape enforcement layer — and NOTHING mechanical about this file is trustworthy.
    # Deferring untouched is the whole response. Placed BEFORE the verifier because a mis-cut hunk
    # is not a drop the atom inventory can be asked about; see `stage_oracle`.
    try:
        mis_parse = index_disagreement(base=base, ours=ours, theirs=theirs)
    except (MergeFileError, OSError, UnicodeDecodeError) as e:
        mis_parse = f"the parse could not be cross-checked against the index ({type(e).__name__}: {e})"
    if mis_parse is not None:
        return FileOutcome(path, "living-doc", "deferred",
                           reason=f"the conflict parse disagrees with the git index — {mis_parse} "
                                  f"— left untouched for human")

    # Zero-drop is the hard gate — checked on whatever we are about to write to the worktree.
    r = verify(ours, theirs, merged, mechanical_applied=mechanical_applied)
    if r.verdict == UNVERIFIABLE:
        # The resolver DID mechanically resolve at least one hunk here, but the verifier parsed
        # zero atoms — this file's shape is unknown to it, so "no drops" would only mean "nothing
        # examined". Treat it like a semantic hunk: never certify byte-safe, never count as
        # RESOLVED, leave git's original markers and defer to the human.
        return FileOutcome(path, "living-doc", "deferred",
                           reason="verifier could not parse any atoms from this file's shape "
                                  "— left untouched for human")
    if not r.ok:
        # Refuse to touch the file; leave git's original markers for the human. Only the WORDING
        # is decided here, and it reports BOTH facts rather than choosing between them.
        #
        # Round 10 (m-G1): choosing was the bug. `_still_conflicted` is shape-only — prose that
        # merely QUOTES conflict syntax is byte-identical to a real region — so a blob that is not
        # conflicted at all, but IS genuinely missing an atom, used to be labelled the low-stakes
        # accepted phantom ("merge markers remain") and the operator was never told content looked
        # lost. The reverse cure (drop always wins) is no better: on this branch the verdict can
        # only be `DROPS_DETECTED`, so `r.dropped` is ALWAYS non-empty and "content drop" would
        # become unconditional, re-breaking round 9's phantom for every genuinely-conflicted file.
        #
        # So: when brackets are present the message says markers remain AND names the missing-atom
        # count, with the hedge that the markers may account for some or all of it — the operator
        # is pointed at both possibilities and `FileOutcome.dropped` carries the atoms either way.
        # When there are no brackets the drop is unhedged. See `_still_conflicted`.
        n = len(r.dropped)
        reason = (f"verifier could not verify a still-conflicted blob (merge markers remain) "
                  f"AND {n} atom(s) appear missing from it — the markers may account for some or "
                  f"all, so check for lost content — left untouched for human"
                  if _still_conflicted(merged) else
                  "verifier flagged content drop — left untouched for human")
        return FileOutcome(path, "living-doc", "deferred", reason=reason,
                           dropped=[f"{k}:{s}" for k, s in r.dropped])

    if status == RESOLVED and not any(m in merged for m in CONFLICT_MARKERS):
        # Every hunk mechanical and clean -> fully auto-resolve and stage.
        # BYTES, not text: `write_text` would encode with the ambient locale (`UnicodeEncodeError`
        # under a non-UTF-8 LANG) and translate `\n` -> `os.linesep`. `_cond5_resolve` re-derives
        # the expected oid from `merged.encode("utf-8")`, so a text-mode write makes the on-disk
        # bytes stop matching what the verifier recomputes. Every other step on this path is
        # bytes-explicit; this one now is too.
        Path(repo_path(repo, path)).write_bytes(merged.encode("utf-8"))
        _git(repo, "add", "--", path)
        return FileOutcome(path, "living-doc", "auto-resolved")

    # Not stageable, written for the human. Two ways here, and the reason names which:
    #   * status DEFER — mechanical hunks (if any) pre-resolved, every other region left as markers
    #     by the shared resolver; the reason names why each of those regions deferred;
    #   * status RESOLVED yet marker text remains — every region the parse found was resolved, so
    #     the remaining marker-shaped text is either syntax the DOCUMENT quotes (a fenced example
    #     of a conflict, which the labelled parse correctly leaves as content) or a region the
    #     parse did not read. This guard cannot tell those apart, so it never stages either.
    # Written to the worktree (shrinks the human's job) but NOT staged. Bytes-explicit for the
    # same reason as the auto-resolved write above.
    Path(repo_path(repo, path)).write_bytes(merged.encode("utf-8"))
    reason = ("every conflict region was resolved, but the result still contains conflict-marker "
              "text (quoted marker syntax in the document, or a region the parse did not read) — "
              "written, NOT staged; a human must confirm it"
              if status == RESOLVED else
              ("mechanical hunks pre-resolved; human must finish the remaining conflict"
               if mechanical_applied else
               "no conflict region could be resolved mechanically; human must resolve them")
              + _deferred_reasons(base, ours, theirs))
    return FileOutcome(path, "living-doc", "partially-resolved", reason=reason)


def _deferred_reasons(base: str, ours: str, theirs: str) -> str:
    """` — deferred: <class>: <reason>; ...` naming why each remaining region was left, or "" when
    they cannot be re-derived. Wording only: a failure here never changes an outcome."""
    try:
        why = deferred_hunk_reasons(base=base, ours=ours, theirs=theirs)
    except (MergeFileError, OSError, UnicodeDecodeError):
        return ""
    return f" — deferred: {'; '.join(why)}" if why else ""


def repo_path(repo: str, path: str) -> str:
    return str(Path(repo) / path)


def merge_back(repo: str, base_ref: str, living_docs=None,
               start_merge: bool = True) -> MergeReport:
    """`living_docs=None` means "use `is_auto_safe_path`" — the exact `AUTO_SAFE_PATHS` allowlist
    PLUS a design's `tp-designs/{slug}/decisions.md`. An explicitly-passed iterable keeps the old
    exact-membership behaviour, so the parameter stays a test seam."""
    if start_merge:
        # Snapshot the unmerged index entries BEFORE the merge: the state check below asks whether
        # THIS invocation created any, which is not the same question as whether any exist.
        # Fail CLOSED if the snapshot cannot be taken — without a baseline the state check below
        # degenerates into "are there any?", which is the very question that misattributes a stale
        # merge's conflicts. Refuse before starting a merge rather than start one we cannot judge.
        try:
            pre_unmerged = set(conflicted_files(repo))
        except ConflictScanFailed as e:
            return MergeReport(base_ref=base_ref, merged_clean=False, needs_human=True,
                               merge_failed=True,
                               merge_error=f"could not read the pre-merge index state, so a "
                                           f"merge would not be judgeable; nothing attempted "
                                           f"({e})"[:500])
        mr = _git(repo, "merge", "--no-commit", "--no-ff", base_ref, check=False)
        out = mr.stdout + mr.stderr
        if mr.returncode == 0 and "CONFLICT" not in out:
            return MergeReport(base_ref=base_ref, merged_clean=True)
        looks_like_a_non_conflict_failure = mr.returncode != 0 and "CONFLICT" not in out
        made_fresh_conflicts = True     # not consulted unless the message test fires
        if looks_like_a_non_conflict_failure:
            try:
                made_fresh_conflicts = bool(set(conflicted_files(repo)) - pre_unmerged)
            except ConflictScanFailed as e:
                # Same fail-closed rule on the POST side: git already said this was NOT a content
                # conflict, and the one check that could overrule it is unavailable. Deny rather
                # than let an unknown state fall through to the resolve loop, which would then
                # resolve whatever unmerged entries happen to be lying around.
                made_fresh_conflicts = False
                # PREPENDED, not appended. `merge_error` truncates to 500 chars, and git's own
                # merge output is routinely longer than that — appending put the only trace of
                # WHY the merge was denied in the part that gets cut, so the operator saw git's
                # message and no hint that the state check had failed. The decision is unaffected
                # either way; this is observability, and the diagnostic is the half worth keeping.
                out = f"[unmerged-index state unavailable: {e}]\n{out}"
        if looks_like_a_non_conflict_failure and not made_fresh_conflicts:
            # `git merge` FAILED for a reason that is not a content conflict: an unknown base ref,
            # a dirty worktree, an already-in-progress merge, a refusal to fast-forward. No merge
            # was started, so `conflicted_files()` returns [] and the per-file loop never runs —
            # which used to leave `needs_human` False and `_main` returning **exit 0**, i.e. the
            # same status as a clean merge. The only trace was `merged_clean: false` deep in the
            # JSON, which the skill prose does not key on. It gets its own outcome and its own
            # non-zero exit (3) instead: nothing was resolved, and nothing was even attempted.
            #
            # TWO independent checks, because the message test alone cannot bear the weight. The
            # substring is a *message* test on git's porcelain output; `LC_ALL=C` (see `_git`)
            # makes it deterministic, but a future rewording — or a git this module does not
            # anticipate — would still slip past it and turn a GENUINE content conflict into
            # "nothing was attempted". That is a behaviour REGRESSION: before this branch existed
            # the ambiguous case fell through to `conflicted_files()` and was resolved.
            #
            # The second check is a *state* test on the index (`--diff-filter=U`), and it asks the
            # narrower question that actually discriminates: did THIS invocation create unmerged
            # entries? A plain "are there any?" would be wrong — the merge-already-in-progress
            # refusal leaves the PREVIOUS merge's unmerged entries lying around, and resolving
            # those while reporting them against the base ref the caller asked for would attribute
            # another merge's conflicts to this one. Differencing against the pre-merge snapshot
            # keeps that case a `merge_failed` while letting a real, freshly-created conflict
            # through. When message and state disagree on a fresh conflict the STATE wins:
            # attempting a real conflict is strictly safer than denying one, and the resolve loop's
            # staging policy still gates every write behind the zero-drop verifier. When the state
            # test cannot be run AT ALL, however, there is nothing to disagree with and the answer
            # is DENY: `ConflictScanFailed` above sets `made_fresh_conflicts` False.
            return MergeReport(base_ref=base_ref, merged_clean=False, needs_human=True,
                               merge_failed=True, merge_error=out.strip()[:500])

    # Third and last scan. Fail closed here too: an unreadable index is not an empty one, and
    # `files = []` would report a total, needs_human-False success over a merge nobody inspected.
    try:
        files = conflicted_files(repo)
    except ConflictScanFailed as e:
        return MergeReport(base_ref=base_ref, merged_clean=False, needs_human=True,
                           merge_failed=True,
                           merge_error=f"could not list conflicted files; nothing resolved "
                                       f"({e})"[:500])
    report = MergeReport(base_ref=base_ref, merged_clean=False, conflicted=files)
    if living_docs is None:
        _is_living = is_auto_safe_path
    else:
        living = set(living_docs)
        _is_living = living.__contains__
    for path in files:
        if _is_living(path):
            # Outer backstop to the in-function guard: NOTHING may escape this loop. An escape
            # after earlier files were written and staged leaves a half-staged merge with no
            # `MergeReport` for the caller to act on — strictly worse than deferring one file.
            # `resolve_living_doc` already catches the known raisers; this catches the unknown
            # ones (a `write_bytes`/`_git` OSError after the guards, say) and still produces a
            # total report.
            try:
                outcome = resolve_living_doc(repo, path)
            except Exception as e:                     # noqa: BLE001 — deliberate totality
                outcome = FileOutcome(path, "living-doc", "deferred",
                                      reason=f"resolver raised — needs human "
                                             f"({type(e).__name__}: {e})")
        else:
            outcome = FileOutcome(path, "other", "deferred",
                                  reason="non-living-doc conflict — always human")
        report.outcomes.append(asdict(outcome))
        bucket = {"auto-resolved": report.auto_resolved,
                  "partially-resolved": report.partially_resolved,
                  "deferred": report.deferred}[outcome.action]
        bucket.append(path)
    report.needs_human = bool(report.partially_resolved or report.deferred)
    return report


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Merge a base ref and auto-resolve living-doc conflicts.")
    ap.add_argument("repo")
    ap.add_argument("base_ref")
    ap.add_argument("--no-start-merge", action="store_true",
                    help="assume a conflicted merge is already in progress; just resolve")
    ap.add_argument("--abort", action="store_true", help="git merge --abort and exit")
    args = ap.parse_args(argv)
    if args.abort:
        _git(args.repo, "merge", "--abort", check=False)
        print("merge aborted")
        return 0
    report = merge_back(args.repo, args.base_ref, start_merge=not args.no_start_merge)
    print(report.to_json())
    # exit 0 = fully resolved/clean; 2 = needs human (deferrals remain);
    #      3 = `git merge` itself failed for a non-conflict reason (nothing was attempted)
    if report.merge_failed:
        print(f"merge_driver: git merge failed: {report.merge_error}", file=sys.stderr)
        return 3
    return 2 if report.needs_human else 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
