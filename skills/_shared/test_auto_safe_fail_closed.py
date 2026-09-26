"""Fail-closed regressions for the shared AUTO-SAFE resolution path.

Split out of `test_auto_safe_resolution.py` (which pins the module's happy-path contract and was
at the size-guard soft-warn) because these tests pin one specific thing: the paths on which
`resolve_conflict_bytes_detail` must NOT hand `merge_driver` something it will write to disk.

Two failure modes, both of which produced TOTAL CONTENT LOSS reported as a clean zero-drop merge:

  S1  `git merge-file`'s exit status was DISCARDED. On failure it writes nothing to stdout, so
      `resolve_file("")` returned `(RESOLVED, [], [])`, `merged` became `"\\n"`, and
      `any([]) == False` disarmed `UNVERIFIABLE` — so an atom-less living doc verified VERIFIED
      and the driver wrote one newline over the whole file and `git add`ed it.

  S4  the `mechanical_applied` OR is an OR **across the file's hunks**. Both pre-existing cases
      were single-hunk, where `any` and `all` are indistinguishable, so mutating `any` -> `all`
      left the suite green. The multi-hunk fixture below is the mutation detector.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import auto_safe_resolution as asr  # noqa: E402
from auto_safe_resolution import (  # noqa: E402
    MergeFileError,
    RESOLVED,
    resolve_conflict_bytes_detail,
)

_MERGE_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "tp-merge-from-main", "scripts")
)
sys.path.insert(0, _MERGE_SCRIPTS)
import merge_driver  # noqa: E402

VISION = "three-pillars-docs/vision.md"        # IS in AUTO_SAFE_PATHS, and parses to ZERO atoms


def _git(repo, *args, check=True):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=check, env=env)


def _injected(text):
    """A stand-in for `asr._diff3_conflict` that returns `text` as merge-file's output.

    The byte path now parses LABELLED text and checks the region count against merge-file's exit
    status (round 17), so an injected text has to say which labels its markers carry and how many
    regions it holds. The fixtures here use `<<<<<<< ours` / `||||||| base` / `>>>>>>> theirs`."""
    count = text.split("\n").count("<<<<<<< ours")
    return lambda **kw: asr.Diff3(text, ("ours", "base", "theirs"), count)


def _atomless_conflict_repo(tmp_path):
    """A REAL conflicted merge on an allowlisted living doc whose content yields ZERO atoms.

    Prose only — no `### L<n>:`, no `| D<n> |` row, no dated bullet, no `### [tag]` entry — so
    `verify.atoms()` returns `{}` for both sides and the verdict rests entirely on
    `mechanical_applied`. That is precisely the shape on which the silent pass fired.
    """
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    (repo / "three-pillars-docs").mkdir()
    (repo / VISION).write_text("# Vision\n\nshared prose paragraph\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "design")
    (repo / VISION).write_text("# Vision\n\nours rewrote the paragraph\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "ours")
    _git(repo, "checkout", "-q", "master")
    (repo / VISION).write_text("# Vision\n\ntheirs rewrote it differently\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "theirs")
    _git(repo, "checkout", "-q", "design")
    return repo


# ---- S1: a failed `git merge-file` must never look like a clean merge ------------------------

def test_diff3_conflict_text_raises_on_merge_file_failure(monkeypatch):
    """The returncode is CHECKED. `git merge-file` documents status = conflict count (<=127),
    negative (255 through the shell) = error; an error must raise, not return empty stdout."""
    def _boom(argv, **kw):
        return subprocess.CompletedProcess(argv, 255, b"", b"error: could not read file")
    monkeypatch.setattr(asr.subprocess, "run", _boom)
    with pytest.raises(MergeFileError):
        asr._diff3_conflict_text(base="b\n", ours="o\n", theirs="t\n")


def test_merge_file_conflict_count_is_not_treated_as_failure(monkeypatch):
    """Tightness for the arm above: a NON-ZERO status inside `0..127` is a conflict count, which
    is the normal case, and must still return the conflict text."""
    def _conflicts(argv, **kw):
        return subprocess.CompletedProcess(argv, 3, b"<<<<<<< ours\nx\n=======\ny\n>>>>>>> theirs\n", b"")
    monkeypatch.setattr(asr.subprocess, "run", _conflicts)
    assert "<<<<<<<" in asr._diff3_conflict_text(base="b\n", ours="o\n", theirs="t\n")


def test_empty_conflict_text_is_not_reported_as_a_mechanical_no_op(monkeypatch):
    """`any([]) is False` was the whole bug. A hunk-less conflict text means "nothing was
    examined", so the fact handed to `verify()` must be True, not False."""
    monkeypatch.setattr(asr, "_diff3_conflict", _injected(""))
    status, merged, mechanical = resolve_conflict_bytes_detail(base="b\n", ours="o\n", theirs="t\n")
    assert status == RESOLVED and merged == "\n"
    assert mechanical is True


def test_driver_never_writes_an_empty_merge_over_a_nonempty_atomless_doc(tmp_path, monkeypatch):
    """THE S1 regression. Before the fix this file was overwritten with `"\\n"`, `git add`ed and
    reported `auto-resolved` — total content loss presented as a clean zero-drop merge."""
    repo = _atomless_conflict_repo(tmp_path)
    monkeypatch.setattr(asr, "_diff3_conflict", _injected(""))   # simulate a failed merge-file

    report = merge_driver.merge_back(str(repo), "master")

    assert VISION in report.deferred, report.to_json()
    assert VISION not in report.auto_resolved, report.to_json()
    written = (repo / VISION).read_text(encoding="utf-8")
    assert "ours rewrote the paragraph" in written        # git's own conflicted worktree content
    assert written.strip() != ""                          # never clobbered to one newline
    # Still UNMERGED in the index — i.e. never `git add`ed. (`git diff --cached --name-only` is
    # the wrong probe here: mid-merge it reports unmerged paths too.)
    assert _git(repo, "ls-files", "-u", "--", VISION, check=False).stdout.strip() != ""


def test_driver_defers_when_merge_file_itself_fails(tmp_path, monkeypatch):
    """The `MergeFileError` arm end to end: the driver defers the file untouched rather than
    letting the exception escape or resolving on empty output."""
    repo = _atomless_conflict_repo(tmp_path)

    def _boom(**kw):
        raise MergeFileError("git merge-file failed (exit 255)")
    monkeypatch.setattr(asr, "_diff3_conflict", _boom)

    report = merge_driver.merge_back(str(repo), "master")
    assert VISION in report.deferred, report.to_json()
    outcome = [o for o in report.outcomes if o["path"] == VISION][0]
    assert "conflict reconstruction failed" in outcome["reason"]


# ---- S4: the OR is across HUNKS — `all` must not pass ----------------------------------------

# One MECHANICAL hunk (`append-only-log`: non-empty in-hunk base that both sides extend) and one
# DEFERRING hunk (`generic-prose`). Neither carries an atom shape, so ours∪theirs parses to zero
# atoms and the verdict is decided purely by `mechanical_applied`:
#   any -> True  -> UNVERIFIABLE -> driver DEFERS, writes nothing
#   all -> False -> VERIFIED     -> driver writes the file as "partially-resolved"
# Every side line is drawn from the fixture's real stage blobs, deliberately: the driver now
# cross-checks the PARSE against the index stages (`stage_oracle`), so an injected conflict text
# whose lines no stage contains is rejected as a mis-parse before this arm is ever reached. The
# fiction has to be a CONSISTENT one to test what it is aimed at.
# The two tails are IDENTICAL (one blank line each): since round 19 (P2) two DIFFERING tails must
# each be whole log entries, which carry atoms, and an identical tail is emitted once, so it is the
# append shape that still resolves with no atom in it.
_MECHANICAL_HUNK = ("<<<<<<< ours\n# Vision\n\n||||||| base\n# Vision\n"
                    "=======\n# Vision\n\n>>>>>>> theirs")
_DEFERRING_HUNK = ("<<<<<<< ours\nours rewrote the paragraph\n||||||| base\nshared prose paragraph\n"
                   "=======\ntheirs rewrote it differently\n>>>>>>> theirs")
MULTI_HUNK = "# Vision\n" + _MECHANICAL_HUNK + "\nmiddle\n" + _DEFERRING_HUNK + "\n"


def test_mechanical_applied_is_an_or_across_hunks_not_an_all(monkeypatch):
    """Mutation detector: with `all(...)` in place of `any(...)` this returns False and fails."""
    monkeypatch.setattr(asr, "_diff3_conflict", _injected(MULTI_HUNK))
    status, merged, mechanical = resolve_conflict_bytes_detail(base="b\n", ours="o\n", theirs="t\n")
    assert mechanical is True                       # one hunk resolved mechanically
    assert status != RESOLVED                       # ...and one deferred, so the FILE defers
    assert merged.startswith("# Vision\n# Vision\n\nmiddle\n")   # the mechanical hunk was applied
    assert "<<<<<<<" in merged                                 # the semantic hunk kept its markers


def test_multi_hunk_atomless_file_is_deferred_not_written(tmp_path, monkeypatch):
    """The same fact at the driver boundary. Under `all` this file is written to the worktree as
    `partially-resolved`; under `any` it is UNVERIFIABLE and left exactly as git left it."""
    repo = _atomless_conflict_repo(tmp_path)
    monkeypatch.setattr(asr, "_diff3_conflict", _injected(MULTI_HUNK))

    report = merge_driver.merge_back(str(repo), "master")

    assert VISION in report.deferred, report.to_json()
    assert VISION not in report.partially_resolved, report.to_json()
    outcome = [o for o in report.outcomes if o["path"] == VISION][0]
    assert "could not parse any atoms" in outcome["reason"]
    # Untouched: still exactly git's own conflicted worktree content, none of MULTI_HUNK's text.
    written = (repo / VISION).read_text(encoding="utf-8")
    assert "<<<<<<< HEAD" in written and "ours rewrote the paragraph" in written
    assert "middle" not in written          # `middle` occurs ONLY in the injected MULTI_HUNK


# ---- M1: the fail-closed arm is BLANK INPUT, not "the resolver found no hunks" ----------------

# A three-way merge git resolves CLEANLY: base has two paragraphs, ours edits the first, theirs
# edits the second. `git merge-file` exits 0 and emits real, correct, hunk-free content.
_CLEAN_BASE = "# Vision\n\nfirst paragraph\n\nsecond paragraph\n"
_CLEAN_OURS = "# Vision\n\nfirst paragraph, ours edited\n\nsecond paragraph\n"
_CLEAN_THEIRS = "# Vision\n\nfirst paragraph\n\nsecond paragraph, theirs edited\n"


def test_a_clean_no_hunk_merge_is_not_reported_as_mechanically_applied():
    """`results == []` is ALSO the shape of a clean three-way merge with real content: nothing was
    mechanically resolved, so `mechanical_applied` must be False.

    The arm used to read `not results` ("no hunks"), which claimed a mechanical resolution had been
    applied here and made `verify()` return `UNVERIFIABLE` on every atom-less allowlisted doc that
    merged cleanly. `three-pillars-docs/vision.md` parses to ZERO atoms today, so the driver
    deferred it permanently and the strict RME `_cond5_resolve` link failed — silently retiring it
    from the AUTO-SAFE set `SKILL.md` advertises.
    """
    status, merged, mechanical = resolve_conflict_bytes_detail(
        base=_CLEAN_BASE, ours=_CLEAN_OURS, theirs=_CLEAN_THEIRS)
    assert status == RESOLVED
    assert mechanical is False
    # ...and the merge really is clean and lossless — both sides' edits present, no markers.
    assert merged == "# Vision\n\nfirst paragraph, ours edited\n\nsecond paragraph, theirs edited\n"


def test_a_clean_no_hunk_merge_verifies_rather_than_blocking():
    """The consequence at the verifier boundary, for the atom-less doc the arm actually bit."""
    from verify import UNVERIFIABLE, VERIFIED, verify

    _status, merged, mechanical = resolve_conflict_bytes_detail(
        base=_CLEAN_BASE, ours=_CLEAN_OURS, theirs=_CLEAN_THEIRS)
    r = verify(_CLEAN_OURS, _CLEAN_THEIRS, merged, mechanical_applied=mechanical)
    assert r.verdict != UNVERIFIABLE
    assert r.verdict == VERIFIED and r.pre_atoms == 0


def test_driver_stages_a_hunk_free_resolution_of_an_atomless_living_doc(tmp_path, monkeypatch):
    """End to end at the driver, on the file the over-broad arm actually retired.

    `vision.md` is in `AUTO_SAFE_PATHS` and parses to ZERO atoms, so its verdict rests entirely on
    `mechanical_applied`. Real index stages, with `_diff3_conflict` returning hunk-free
    content — the shape `git merge-file` emits when it exits 0 and merges all three sides cleanly
    (git's own merge and `merge-file` over the reconstructed stages need not agree on what
    conflicts). Under the old `not results` arm this was `UNVERIFIABLE`, the file was deferred
    forever, and `_cond5_resolve` could never earn the strict RME link for it.
    """
    repo = _atomless_conflict_repo(tmp_path)
    clean = "# Vision\n\nfirst paragraph, ours edited\n\nsecond paragraph, theirs edited\n"
    monkeypatch.setattr(asr, "_diff3_conflict", _injected(clean))

    report = merge_driver.merge_back(str(repo), "master")

    assert VISION in report.auto_resolved, report.to_json()
    assert VISION not in report.deferred, report.to_json()
    assert (repo / VISION).read_text(encoding="utf-8") == clean
    # Staged — i.e. no longer unmerged in the index.
    assert _git(repo, "ls-files", "-u", "--", VISION, check=False).stdout.strip() == ""


def test_blank_conflict_text_still_fails_closed(monkeypatch):
    """The other direction, unweakened: BLANK input means "nothing was examined", so the fact must
    still be True and `verify()` must still block. Whitespace-only stdout — which the old
    `not results` arm covered only incidentally — is now covered explicitly."""
    for blank in ("", "\n", "   \n\t\n"):
        monkeypatch.setattr(asr, "_diff3_conflict", _injected(blank))
        _status, _merged, mechanical = resolve_conflict_bytes_detail(
            base="b\n", ours="o\n", theirs="t\n")
        assert mechanical is True, repr(blank)


def test_driver_still_defers_a_whitespace_only_merge_file_result(tmp_path, monkeypatch):
    """The S1 driver-level regression, re-pinned against the NARROWED arm: an atom-less living doc
    must not be clobbered when `merge-file` yields whitespace-only output."""
    repo = _atomless_conflict_repo(tmp_path)
    monkeypatch.setattr(asr, "_diff3_conflict", _injected("\n\n"))

    report = merge_driver.merge_back(str(repo), "master")

    assert VISION in report.deferred, report.to_json()
    assert VISION not in report.auto_resolved, report.to_json()
    assert "ours rewrote the paragraph" in (repo / VISION).read_text(encoding="utf-8")
