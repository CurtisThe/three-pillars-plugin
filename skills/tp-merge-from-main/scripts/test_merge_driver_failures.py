"""A NON-conflict `git merge` failure must not read as success.

Split from `test_merge_driver.py` (per-file resolution outcomes, and at the size-guard soft-warn)
by responsibility: everything here is about the merge that never started at all.

The regression: with `start_merge` on, when `git merge --no-commit --no-ff` fails for a reason that
is NOT a content conflict — an unknown base ref, a dirty worktree, a merge already in progress —
`returncode != 0` and stdout/stderr carry no `CONFLICT`, so the clean-merge early return was
skipped, `conflicted_files()` returned `[]`, the per-file loop never ran, `needs_human` stayed
False and `_main` returned **exit 0**, documented as "fully resolved/clean". The only trace was
`merged_clean: false` deep in the JSON body, which the skill prose does not key on.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import merge_driver  # noqa: E402
from merge_driver import merge_back  # noqa: E402
from test_merge_driver import KI, PRE, commit, git, make_repo, write  # noqa: E402


def _design_branch(tmp_path):
    """A repo on `design`, one commit deep, ready for a merge attempt against `master`."""
    repo = make_repo(tmp_path)
    write(repo, KI, PRE.format(date="2026-05-01") + "\n### L1: a\n")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    return repo


def _diverge(repo, ours_tail, theirs_tail):
    write(repo, KI, PRE.format(date="2026-05-01") + "\n### L1: a\n" + ours_tail)
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, KI, PRE.format(date="2026-05-02") + "\n### L1: a\n" + theirs_tail)
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")


def test_unknown_base_ref_is_a_merge_failure_not_a_clean_merge(tmp_path):
    repo = _design_branch(tmp_path)
    report = merge_back(str(repo), "origin/does-not-exist")
    assert report.merge_failed is True, report.to_json()
    assert report.merged_clean is False
    assert report.needs_human is True
    assert report.merge_error, report.to_json()
    # Nothing was attempted — no conflicted files, no per-file outcomes.
    assert report.conflicted == [] and report.outcomes == []


def test_dirty_worktree_merge_refusal_is_a_merge_failure(tmp_path):
    """The second reachable shape: git refuses to start because the worktree carries local changes
    to a file the merge would overwrite."""
    repo = _design_branch(tmp_path)
    _diverge(repo, "### L2: ours\n", "### L3: theirs\n")
    write(repo, KI, PRE.format(date="2026-05-01") + "\n### L1: a\n### L2: ours\nuncommitted\n")
    report = merge_back(str(repo), "master")
    assert report.merge_failed is True, report.to_json()
    assert report.needs_human is True


def test_merge_already_in_progress_is_a_merge_failure(tmp_path):
    """The third: a conflicted merge is already open, so git refuses to start another. The
    `--no-start-merge` flag is the supported way to resolve one of those.

    Also the tightness arm for the E2 state check. Unmerged index entries DO exist here — they
    belong to the previous merge — so a plain "are there any conflicted files?" test would fall
    through and resolve another merge's conflicts while reporting them against the base ref THIS
    caller asked for. The check differences against a pre-merge snapshot instead, so only entries
    this invocation created count, and the refusal stays a `merge_failed`."""
    repo = _design_branch(tmp_path)
    _diverge(repo, "### L2: ours\n", "### L2: theirs\n")
    git(repo, "merge", "--no-commit", "--no-ff", "master", check=False)   # leaves it conflicted
    report = merge_back(str(repo), "master")
    assert report.merge_failed is True, report.to_json()


def test_merge_failure_exits_3_not_0(tmp_path):
    """The exit-status contract: `3` is distinct from `0` (clean) AND from `2` (deferrals remain),
    because nothing was merged and nothing was even attempted. Pre-fix this returned 0."""
    repo = _design_branch(tmp_path)
    assert merge_driver._main([str(repo), "origin/does-not-exist"]) == 3


def test_a_real_conflict_is_still_not_a_merge_failure(tmp_path):
    """Tightness: `git merge` also exits non-zero on a genuine content conflict, which DOES say
    `CONFLICT` and must still fall through to the per-file resolution loop."""
    repo = _design_branch(tmp_path)
    _diverge(repo, "### L2: ours\n", "### L2: theirs\n")
    report = merge_back(str(repo), "master")
    assert report.merge_failed is False, report.to_json()
    assert report.conflicted == [KI]


def test_a_translated_conflict_message_still_reaches_the_resolve_loop(tmp_path, monkeypatch):
    """E2. The failure branch keys on the literal ASCII substring `CONFLICT`, which a git built
    with NLS translates. If that word is absent, a GENUINE content conflict was classified as a
    non-conflict failure: the function returned immediately, `conflicted_files()` and the per-file
    loop never ran, and it reported exit 3 "nothing was attempted" — a regression, because before
    the branch existed that same case fell through and WAS resolved.

    Simulated at the only place it can be: the real merge runs and really conflicts, but git's
    message is replaced with a translated one carrying no `CONFLICT`. The index state must win.
    """
    repo = _design_branch(tmp_path)
    _diverge(repo, "### L2: ours\n", "### L2: theirs\n")
    real_git = merge_driver._git

    def _translated(repo_arg, *args, **kw):
        r = real_git(repo_arg, *args, **kw)
        if args[:1] == ("merge",):
            return type(r)(r.args, r.returncode, "KONFLIKT (Inhalt): Merge-Konflikt in ki.md\n",
                           "Automatischer Merge fehlgeschlagen.\n")
        return r
    monkeypatch.setattr(merge_driver, "_git", _translated)
    report = merge_back(str(repo), "master")
    assert report.merge_failed is False, report.to_json()
    assert report.conflicted == [KI], report.to_json()
    assert report.outcomes, report.to_json()


def test_git_runs_under_a_pinned_c_locale(tmp_path, monkeypatch):
    """The other half of the E2 fix: the substring test is only meaningful if git's messages are
    not translated in the first place, so every `_git` call pins `LC_ALL=C`. Pinned rather than
    merely hoped for — a caller's own `LC_ALL` must not leak in."""
    seen = {}
    real_run = merge_driver.subprocess.run

    def _spy(argv, **kw):
        seen.update(kw.get("env") or {})
        return real_run(argv, **kw)
    monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")
    monkeypatch.setattr(merge_driver.subprocess, "run", _spy)
    repo = _design_branch(tmp_path)
    merge_driver._git(str(repo), "status", "--porcelain", check=False)
    assert seen.get("LC_ALL") == "C", seen.get("LC_ALL")
    assert "PATH" in seen, "the ambient environment must be inherited, not replaced"


# ---- S-B2: "no conflicts" and "I could not tell" are different answers ------------------------

def _fail_scan_on(monkeypatch, nth):
    """Make the `nth` (1-based) unmerged-index scan fail the way a locked or corrupt index does.

    Injected at the GIT call, not at `conflicted_files()`'s return value: the bug was that a
    non-zero git exit was indistinguishable from an empty result, so a test that stubs the return
    value cannot see it. Every other call runs for real.
    """
    real_git = merge_driver._git
    calls = {"n": 0}

    def _flaky(repo_arg, *args, **kw):
        r = real_git(repo_arg, *args, **kw)
        if args[:1] == ("diff",) and "--diff-filter=U" in args:
            calls["n"] += 1
            if calls["n"] == nth:
                return type(r)(r.args, 128, "", "fatal: unable to read index\n")
        return r
    monkeypatch.setattr(merge_driver, "_git", _flaky)
    return calls


def test_conflicted_files_raises_rather_than_reporting_an_empty_index(tmp_path):
    """The predicate itself. Under `check=False` any failure returned `[]` — the reassuring
    answer — so no caller could tell a clean index from an unreadable one."""
    not_a_repo = tmp_path / "nope"
    not_a_repo.mkdir()
    with pytest.raises(merge_driver.ConflictScanFailed):
        merge_driver.conflicted_files(str(not_a_repo))


def test_a_failed_pre_merge_snapshot_does_not_resolve_a_stale_merge(tmp_path, monkeypatch):
    """S-B2, the reported repro. A previous merge is still open and conflicted. If the PRE-merge
    snapshot silently reads as `[]`, the `merge_failed` guard differences the stale entries against
    an empty baseline, decides THIS invocation created them, and falls through to the resolve loop
    — resolving another merge's conflicts and attributing them to the base ref this caller asked
    for. It must fail closed instead: nothing attempted, nothing written."""
    repo = _design_branch(tmp_path)
    _diverge(repo, "### L2: ours\n", "### L2: theirs\n")
    git(repo, "merge", "--no-commit", "--no-ff", "master", check=False)   # leaves it conflicted
    stale = (repo / KI).read_text(encoding="utf-8")
    assert "<<<<<<<" in stale, "the leftover merge must really be conflicted"

    _fail_scan_on(monkeypatch, 1)
    report = merge_back(str(repo), "master")
    assert report.merge_failed is True, report.to_json()
    assert report.needs_human is True
    assert report.outcomes == [] and report.conflicted == [], report.to_json()
    assert (repo / KI).read_text(encoding="utf-8") == stale, "the stale merge's file was rewritten"


def test_a_failed_post_merge_state_check_fails_closed(tmp_path, monkeypatch):
    """The other side of the differencing. Git's message says this was not a content conflict; the
    state check is the only thing that could overrule it, so when the state check cannot run the
    answer is DENY, not "fall through and resolve whatever is lying around"."""
    repo = _design_branch(tmp_path)
    _fail_scan_on(monkeypatch, 2)
    report = merge_back(str(repo), "origin/does-not-exist")
    assert report.merge_failed is True, report.to_json()
    assert "unmerged-index state unavailable" in report.merge_error, report.merge_error
    # ...and it survives the 500-char truncation. `merge_error` is `out.strip()[:500]`, so a note
    # APPENDED to git's own merge message is the first thing cut whenever that message is already
    # near the cap — deleting the only trace of WHY the merge was denied. Position, not presence,
    # is what makes it durable, so position is what is pinned. (M-C1: observability only; the
    # fail-closed decision above is unaffected either way.)
    assert report.merge_error.startswith("[unmerged-index state unavailable"), report.merge_error


def test_a_failed_file_list_scan_is_not_a_clean_report(tmp_path, monkeypatch):
    """The third call site, reached on the `--no-start-merge` path. `[]` there produced a total
    report with `needs_human` False over a merge nobody ever inspected — exit 0."""
    repo = _design_branch(tmp_path)
    _diverge(repo, "### L2: ours\n", "### L2: theirs\n")
    git(repo, "merge", "--no-commit", "--no-ff", "master", check=False)
    _fail_scan_on(monkeypatch, 1)
    report = merge_back(str(repo), "master", start_merge=False)
    assert report.merge_failed is True, report.to_json()
    assert report.needs_human is True and report.outcomes == []


def test_a_clean_merge_is_still_exit_zero(tmp_path):
    """The other tightness arm: returncode 0 with no CONFLICT keeps the clean-merge early return
    and exit 0, untouched by the new branch."""
    repo = _design_branch(tmp_path)
    write(repo, "other.md", "design-only change\n")
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, "unrelated.md", "master-only change\n")
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    assert merge_driver._main([str(repo), "master"]) == 0
