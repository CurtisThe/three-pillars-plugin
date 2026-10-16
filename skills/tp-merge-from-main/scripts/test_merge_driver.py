"""Integration tests for the merge driver against real git repositories."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from merge_driver import merge_back  # noqa: E402

KI = "three-pillars-docs/known_issues.md"
PRE = "*Last updated: {date}*\n\n# Known issues\n"


def git(repo, *args, check=True):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=check, env=env)


def make_repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    (repo / "three-pillars-docs").mkdir()
    return repo


def write(repo, rel, content):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def setup_collision(tmp_path, bump_preamble: bool, ours_extra="", theirs_extra=""):
    """master + a design branch each append dated log entries after the same base entry (a
    `log-entry-insertion`); optionally both bump the preamble too.

    Round 20: both sides used to add a colliding `### L4:` entry, an `id-renumber-collision`. That
    class is GATED now and always defers, so it no longer exercises a mechanical merge."""
    repo = make_repo(tmp_path)
    head = "\n### L1: base issue\nbody\n\n## History\n\n- **2026-05-01** — base entry\n"
    base = PRE.format(date="2026-05-01") + head + ours_extra + theirs_extra
    write(repo, KI, base)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    od = "2026-05-10" if bump_preamble else "2026-05-01"
    under = "A second preamble line.\n" if bump_preamble else ""   # a date-only region is mechanical
    write(repo, KI, PRE.format(date=od).replace("*\n", "*\n" + under, 1) + head
          + ours_extra + "- **2026-05-09** — ours unique entry\n  ours body\n" + theirs_extra)
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    td = "2026-05-12" if bump_preamble else "2026-05-01"
    write(repo, KI, PRE.format(date=td) + head + ours_extra
          + "- **2026-05-11** — theirs entry one\n- **2026-05-12** — theirs entry two\n"
          + theirs_extra)
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    return repo


def test_full_auto_resolve_when_only_mechanical(tmp_path):
    # No preamble bump -> the only conflict is the log-insertion hunk -> fully auto-resolved + staged.
    repo = setup_collision(tmp_path, bump_preamble=False)
    report = merge_back(str(repo), "master")
    assert not report.merged_clean
    assert KI in report.auto_resolved, report.to_json()
    assert KI not in report.deferred
    content = (repo / KI).read_text(encoding="utf-8")
    assert "<<<<<<<" not in content                       # no markers left
    for needle in ["ours unique entry", "theirs entry one", "theirs entry two"]:
        assert needle in content                          # zero-drop
    # staged (index has no remaining unmerged entry for the file)
    unmerged = git(repo, "diff", "--name-only", "--diff-filter=U").stdout
    assert KI not in unmerged


def test_partial_resolution_when_preamble_also_conflicts(tmp_path):
    # Both bump preamble (semantic) AND append log entries (mechanical) -> partially-resolved.
    repo = setup_collision(tmp_path, bump_preamble=True)
    report = merge_back(str(repo), "master")
    assert KI in report.partially_resolved, report.to_json()
    assert report.needs_human
    content = (repo / KI).read_text(encoding="utf-8")
    # mechanical hunk pre-resolved (ours' entries then theirs', no markers between), semantic hunk
    # left as markers
    assert ("- **2026-05-09** — ours unique entry\n  ours body\n- **2026-05-11** — theirs entry one\n"
            "- **2026-05-12** — theirs entry two\n") in content, content
    assert "Last updated" in content and "<<<<<<<" in content
    # NOT staged — markers remain
    unmerged = git(repo, "diff", "--name-only", "--diff-filter=U").stdout
    assert KI in unmerged


def test_non_living_doc_conflict_is_deferred(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, "code.py", "x = 1\n")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, "code.py", "x = 2\n")
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, "code.py", "x = 3\n")
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    report = merge_back(str(repo), "master")
    assert "code.py" in report.deferred
    assert report.needs_human


ARCHIVE = "three-pillars-docs/product_roadmap_archive.md"
ARCH_ARCH = "three-pillars-docs/architecture_archive.md"


def test_archive_living_docs_are_on_the_lane():
    """Step 2 of the seed: `*_archive.md` and `known_issues_resolved.md` are append-only living docs.
    The framework already treats all three this way in its other subsystems (see
    `test_archive_exemptions.py`: same size-exempt / frozen / writable-on-seat governance class); this
    pins that the merge driver's lane agrees — each archive is auto-resolvable, and the frozen
    `completed-tp-designs/` tree (a different thing entirely) stays out of the lane."""
    from auto_safe_resolution import is_auto_safe_path
    for rel in (ARCHIVE, ARCH_ARCH, "three-pillars-docs/known_issues_resolved.md"):
        assert is_auto_safe_path(rel) is True, rel
    assert is_auto_safe_path("three-pillars-docs/completed-tp-designs/some-slug/design.md") is False


def test_product_roadmap_archive_is_a_living_doc_and_auto_resolves(tmp_path):
    """`product_roadmap_archive.md` is an append-only living doc (step 2 of the seed). It is on the
    AUTO-SAFE lane, so a real base-sync shape — both sides inserting keyed slug bullets into the
    `Recent completions` list — is resolved mechanically, verified zero-drop, and staged, rather than
    deferred as a non-living doc. The following bullet is the `_ends_at_boundary` line that makes the
    hunk a `log-entry-insertion` (keep-both) rather than generic prose — the same shape the real
    #191 sync produced, whose two archive hunks the driver now clears to `auto-resolved`."""
    from auto_safe_resolution import is_auto_safe_path
    assert is_auto_safe_path(ARCHIVE) is True   # it is on the mechanical lane
    repo = make_repo(tmp_path)
    head = "## Recent completions\n\n- **`older`** — Done — PR #170\n"
    write(repo, ARCHIVE, head)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, ARCHIVE, head + "- **`design-slug`** — Done — PR #180 (2026-09-30), light class\n")
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, ARCHIVE, head + "- **`base-slug`** — Done — PR #181 (2026-09-30), light class\n")
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    report = merge_back(str(repo), "master")
    assert ARCHIVE in report.auto_resolved, report.to_json()
    assert ARCHIVE not in report.deferred
    assert ARCHIVE not in report.partially_resolved
    content = (repo / ARCHIVE).read_text(encoding="utf-8")
    assert "<<<<<<<" not in content                       # no markers left
    assert "design-slug" in content and "base-slug" in content   # zero-drop: both kept
    unmerged = git(repo, "diff", "--name-only", "--diff-filter=U").stdout
    assert ARCHIVE not in unmerged                        # staged


def test_architecture_archive_history_is_a_living_doc_and_auto_resolves(tmp_path):
    """`architecture_archive.md` is likewise an append-only living doc: its `## History` bullets use
    the same dated log-entry shape as the live `architecture.md`, so a both-added dated-bullet
    conflict resolves as `log-entry-insertion` (keep-both) instead of deferring as a non-living doc.
    The following dated bullet is the `_ends_at_boundary` line that makes it a log insertion rather
    than generic prose."""
    repo = make_repo(tmp_path)
    head = "## History\n\n- **2026-06-01** — `older-entry` implemented (light class)\n"
    write(repo, ARCH_ARCH, head)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, ARCH_ARCH, head + "- **2026-06-05** — `design-entry` implemented (light class)\n")
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, ARCH_ARCH, head + "- **2026-06-06** — `base-entry` implemented (light class)\n")
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    report = merge_back(str(repo), "master")
    assert ARCH_ARCH in report.auto_resolved, report.to_json()
    content = (repo / ARCH_ARCH).read_text(encoding="utf-8")
    assert "<<<<<<<" not in content
    assert "design-entry" in content and "base-entry" in content


def test_empty_but_present_file_is_not_misreported_as_add_delete(tmp_path):
    # Regression (Copilot #7): an empty-but-present living doc on both sides that conflicts must
    # NOT be deferred as an add/delete "missing side" — _stage_blob distinguishes "" from absent.
    from merge_driver import resolve_living_doc, _stage_blob
    repo = make_repo(tmp_path)
    write(repo, KI, "")                        # present but empty
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, KI, "### L1: ours only\n")
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, KI, "### L1: theirs only\n")
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    git(repo, "merge", "--no-commit", "--no-ff", "master", check=False)
    # base stage is the empty file: present, content "" — must be "" not None.
    assert _stage_blob(str(repo), 1, KI) == ""
    outcome = resolve_living_doc(str(repo), KI)
    assert "add/delete" not in outcome.reason   # not misreported as a missing-side conflict
    # ...nor as add/add: the base guard is `base is None`, and a `not base` there would read the
    # empty-but-present base as "no common base" and defer it. Pins that distinction too.
    assert "add/add" not in outcome.reason, outcome.reason


def test_add_add_conflict_is_deferred_no_common_base(tmp_path):
    # Regression (Copilot round-2 #3): both branches CREATE the same living doc (no merge base for
    # it) -> must defer (no common base to anchor a structured merge), not auto-resolve.
    repo = make_repo(tmp_path)
    write(repo, "seed.md", "x\n")
    commit(repo, "base")                       # KI does not exist yet on the common base
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, KI, PRE.format(date="2026-05-10") + "\n### L1: ours\n")
    commit(repo, "ours adds KI")
    git(repo, "checkout", "-q", "master")
    write(repo, KI, PRE.format(date="2026-05-12") + "\n### L1: theirs\n")
    commit(repo, "theirs adds KI")
    git(repo, "checkout", "-q", "design")
    report = merge_back(str(repo), "master")
    assert KI in report.deferred, report.to_json()
    assert any("add/add" in o["reason"] for o in report.outcomes if o["path"] == KI)
    # nothing staged; markers remain for the human
    assert "<<<<<<<" in (repo / KI).read_text(encoding="utf-8")


def test_clean_merge_reports_no_conflict(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, KI, PRE.format(date="2026-05-01") + "\n### L1: a\n")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, "other.md", "design-only change\n")
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, "unrelated.md", "master-only change\n")
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    report = merge_back(str(repo), "master")
    assert report.merged_clean
    assert not report.needs_human


# ---- Round 9: the phantom is worded honestly by the CONSUMER ---------------------------------

DEC = "three-pillars-docs/tp-designs/some-design/decisions.md"


def test_a_still_conflicted_blob_is_not_reported_as_a_content_drop(tmp_path):
    """The verifier strips NOTHING now, so a blob that still carries conflict markers digests
    differently from its clean input sides and returns DROPS_DETECTED with every atom present —
    the accepted phantom (`verify_atoms.py`'s header). Calling that "content drop" sent the
    operator hunting for text that was never lost, so the driver splits the reason on whether the
    blob it verified is still conflicted. The OUTCOME is unchanged either way: defer, touch
    nothing, stage nothing — which is exactly why a phantom is affordable and a silent drop is not.
    """
    repo = make_repo(tmp_path)
    base = "# Decisions\n\n### [tp-plan] a decision\n**Reasoning**: base wording\n"
    write(repo, DEC, base)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, DEC, base.replace("base wording", "OURS wording"))
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, DEC, base.replace("base wording", "THEIRS wording"))
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")

    report = merge_back(str(repo), "master")

    assert DEC in report.deferred, report.to_json()
    assert DEC not in report.auto_resolved
    reason = next(o["reason"] for o in report.outcomes if o["path"] == DEC)
    assert "still-conflicted blob" in reason, reason
    assert "content drop" not in reason, reason
    # Untouched: git's own markers are what the human opens, and BOTH sides' wording is there.
    content = (repo / DEC).read_text(encoding="utf-8")
    assert "<<<<<<<" in content and "OURS wording" in content and "THEIRS wording" in content


def test_prose_brackets_plus_a_genuine_drop_still_names_the_drop(tmp_path):
    """Round 10 (m-G1) — the COMBINATION `_still_conflicted` could not see.

    The blob is NOT conflicted: the only conflicting hunk (both branches append a dated log entry,
    a `log-entry-insertion`) resolves mechanically, so no marker git ever wrote survives into
    `merged`. What survives is PROSE that quotes conflict syntax — the
    `coincidental-conflict-brackets-in-prose` shape, byte-identical to a real region and all over
    this repo's own living docs. Meanwhile `theirs` deleted an unrelated entry that `ours` still
    has, so an atom is GENUINELY missing.

    Before the fix the shape-only predicate answered True on the prose and the file was reported
    as the low-stakes accepted phantom ("merge markers remain"), saying nothing about the missing
    entry — the verifier's whole reason for existing, labelled as the thing it tolerates. Now the
    reason carries the missing-atom count too.

    (Until round 21 the conflicting hunk was an `### L4:` collision, a class GATED since round 20:
    it deferred, left git's own markers in the blob, and so no longer tested what this says.)
    """
    prose = ("### L2: a decision\n<<<<<<< see below for an example\nSome Section\n"
             "=======\n>>>>>>> end example\nreal tail that matters\n")
    q = "### L9: entry Q\nq body that must not vanish quietly\n"
    # Enough unchanged context that theirs' deletion of Q and its log entry are SEPARATE diff
    # hunks — the deletion then applies cleanly (nothing to conflict with) while only the two
    # appended entries reach the resolver.
    pad = "### L8: padding\n" + "".join(f"pad line {i}\n" for i in range(8))
    repo = make_repo(tmp_path)
    base = PRE.format(date="2026-05-01") + "\n### L1: base issue\nbody\n" + prose + q + pad
    ours = base + "- **2026-05-02** — ours unique entry\n"
    # theirs appends its own entry (mechanical) AND deletes entry Q (a real, unrelated content loss).
    theirs = base.replace(q, "") + "- **2026-05-03** — theirs entry one\n"
    write(repo, KI, base)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, KI, ours)
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, KI, theirs)
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")

    # The premise, asserted: every region resolves, and the only brackets left are the prose's.
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_shared"))
    from auto_safe_resolution import RESOLVED, resolve_conflict_bytes
    status, merged = resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)
    assert status == RESOLVED, merged
    brackets = [ln for ln in merged.split("\n") if ln.startswith(("<<<<<<<", ">>>>>>>"))]
    assert brackets == ["<<<<<<< see below for an example", ">>>>>>> end example"], brackets

    report = merge_back(str(repo), "master")

    assert KI in report.deferred, report.to_json()
    assert KI not in report.auto_resolved
    outcome = next(o for o in report.outcomes if o["path"] == KI)
    # git wrote no marker that survived — the brackets in the blob are prose, and the predicate
    # cannot tell. The reason must therefore NOT rest on them alone.
    assert outcome["dropped"] == ["entry:entry q"], outcome   # exactly one, and it is real
    assert "atom(s) appear missing" in outcome["reason"], outcome["reason"]
    assert "check for lost content" in outcome["reason"], outcome["reason"]


def test_still_conflicted_keys_on_the_brackets_only():
    """`=======` and `|||||||` are ordinary markdown — a setext underline and a row of empty
    cells — so matching them here would call an unconflicted file conflicted and mislabel a REAL
    drop as a phantom. Only git's brackets count."""
    from merge_driver import _still_conflicted
    assert _still_conflicted("a\n<<<<<<< ours\nb\n")
    assert _still_conflicted("a\n>>>>>>> theirs\n")
    assert not _still_conflicted("Title\n=======\nbody\n")
    assert not _still_conflicted("| h | h |\n|||||||\nbody\n")
    assert not _still_conflicted("plain prose\n")
    # Not at line start -> not a marker.
    assert not _still_conflicted("see the `<<<<<<<` marker\n")


# ---- Task 1.3: an UNVERIFIABLE shape is deferred, never staged ------------------------------

def test_unverifiable_file_is_deferred_not_staged(tmp_path):
    """A living doc the resolver mechanically resolves but the verifier cannot parse a single
    atom from must be DEFERRED — never written, never staged, never counted auto-resolved.
    'I examined nothing' is not 'nothing was lost'.

    The fixture is a table whose Name cell is empty on every row. `classify.INV_ROW` still fires
    (it keys on the ID cell alone), so `design-inventory-row-merge` resolves mechanically and
    really does keep both new rows, while `verify.ROW` signs the EMPTY Name cell and yields zero
    atoms. Before the three-state verdict this shape merged, staged, and reported ZERO-DROP.
    (Until round 20 the fixture was an entry whose title had moved off its `### L<n>:` heading, an
    `id-renumber-collision`; that class is now gated and defers before the verifier runs.)
    """
    repo = make_repo(tmp_path)
    base = (PRE.format(date="2026-05-01") + "\n| ID | Name | Severity |\n| --- | --- | --- |\n"
            "| L1 |  | high |\n")
    write(repo, KI, base)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, KI, base + "| L4 |  | low |\n")
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, KI, base + "| L5 |  | med |\n")
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")

    report = merge_back(str(repo), "master")

    assert KI not in report.auto_resolved, report.to_json()
    assert KI in report.deferred, report.to_json()
    assert report.needs_human is True
    reason = next(o["reason"] for o in report.outcomes if o["path"] == KI)
    assert "could not parse any atom" in reason, reason

    # NOT staged. `git diff --cached --name-only` cannot answer this mid-merge — it reports every
    # UNMERGED path too — so ask the index directly: a path with surviving stage-1/2/3 entries is
    # by definition unmerged, i.e. `git add` was never called on it.
    unmerged = git(repo, "ls-files", "-u", "--", KI).stdout.strip()
    assert unmerged, "path must still be unmerged in the index (never `git add`ed)"
    # Untouched: git's original markers stay in the worktree for the human.
    assert "<<<<<<<" in (repo / KI).read_text(encoding="utf-8")


# ---- Total-content-loss guard: a SUCCESSFUL merge-file that legitimately resolves to empty ----

def git_in(repo, stdin, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True,
                          text=True, check=True, env=env)


def _stage_oid(repo, content):
    return git_in(repo, content, "hash-object", "-w", "--stdin").stdout.strip()


def test_whitespace_only_resolution_over_a_nonempty_side_is_deferred(tmp_path):
    """The total-content-loss guard, driven on a path where `git merge-file` SUCCEEDS.

    The guard was previously reachable only via a FAILED `git merge-file` — and the `MergeFileError`
    raise now intercepts that route first, so nothing in the suite reached it and deleting the guard
    left the suite green. This is the arm that survives: stage 2 empties the file while stage 3
    still carries the base content, so `merge-file` exits 0 and legitimately produces EMPTY output.
    `resolve_file("")` then yields `(RESOLVED, [], [])` -> a one-newline "merge", which on an
    atom-less doc the verifier cannot distinguish from a clean zero-drop result. The guard must
    catch it BEFORE the verifier and leave the human's file untouched.

    Index stages are built directly with `update-index --index-info` because git's own merge would
    not flag this exact shape as a conflict — the point is to exercise `resolve_living_doc` against
    the stage triple, whatever produced it.
    """
    from merge_driver import resolve_living_doc
    content = "### L1: a\nbody\n"
    repo = make_repo(tmp_path)
    write(repo, KI, content)
    commit(repo, "base")

    base_oid, ours_oid, theirs_oid = (_stage_oid(repo, content), _stage_oid(repo, ""),
                                      _stage_oid(repo, content))
    git(repo, "rm", "-q", "--cached", "--", KI)
    git_in(repo, "".join(f"100644 {oid} {stage}\t{KI}\n" for oid, stage in
                         ((base_oid, 1), (ours_oid, 2), (theirs_oid, 3))),
           "update-index", "--index-info")

    before = (repo / KI).read_bytes()
    outcome = resolve_living_doc(str(repo), KI)
    assert outcome.action == "deferred", outcome
    assert "empty output for a non-empty file" in outcome.reason, outcome.reason
    assert (repo / KI).read_bytes() == before, "guard must not write over the human's file"
    assert git(repo, "ls-files", "-u", "--", KI).stdout.strip(), "must stay unmerged"


def test_worktree_writes_are_bytes_explicit():
    """`Path.write_text` encodes with the AMBIENT LOCALE (a non-UTF-8 `LANG` raises
    `UnicodeEncodeError`) and writes in text mode, translating `\\n` -> `os.linesep`.
    `base_sync_cert._cond5_resolve` re-derives the expected blob oid from `merged.encode("utf-8")`,
    so either behaviour makes the on-disk bytes stop matching what the verifier recomputes. Every
    other step on this path is bytes-explicit; the two worktree writes must be too.

    Asserted on the SOURCE because the failure needs a non-UTF-8 locale or a CRLF platform to
    reproduce — neither is available in CI, and an invariant left untested because it is awkward to
    reproduce is exactly how this one regressed."""
    import merge_driver
    src = Path(merge_driver.__file__).read_text(encoding="utf-8")
    assert "write_text(" not in src, "a worktree write regressed to text mode"
    assert src.count('write_bytes(merged.encode("utf-8"))') == 2


def test_a_resolver_exception_defers_the_file_instead_of_aborting_the_merge(monkeypatch):
    """Nothing may escape `merge_back`'s per-file loop. An escape AFTER earlier files were written
    and staged leaves a half-staged merge with no `MergeReport` for the caller to act on — strictly
    worse than deferring one file. `OSError` from tempfile/`subprocess.run` used to do exactly
    that."""
    import merge_driver
    monkeypatch.setattr(merge_driver, "conflicted_files", lambda _repo: [KI])
    monkeypatch.setattr(merge_driver, "resolve_living_doc",
                        lambda _repo, _path: (_ for _ in ()).throw(OSError("ENOSPC")))
    report = merge_driver.merge_back("/nonexistent", "master", start_merge=False)
    assert report.deferred == [KI]
    assert report.needs_human is True
    assert "OSError" in next(o["reason"] for o in report.outcomes if o["path"] == KI)
