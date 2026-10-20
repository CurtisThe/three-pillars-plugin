"""`apply_hard_cap_backstop` — the Low-part arm (design basesync-count-line-and-low-headroom, 2.2).

A Low part has no archive: when the merge pushed an auto-resolved part over `low_doc_parts.CAP`
while NEITHER side was over it, the backstop splits the part's trailing `### L` entries into the
next part, accepts only a split that fits, keeps the heading count and passes the zero-drop
re-verify, and stages both parts. Any other outcome restores both files, runs `git checkout -m` and
defers the part.

Rule: skills/_shared/test-fragility.md — behaviour only. A deferred part keeps git's conflict
markers, which QUOTE both sides' text, so the deferred arms assert the merge DECISIONS (report
buckets, the outcome reason, `git ls-files -u`, the marker count) and never a deferred file's text.
"""
import contextlib
import dataclasses
import io
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
import file_size_guard  # noqa: E402
import living_doc_archive  # noqa: E402
import low_doc_parts  # noqa: E402
import verify as verify_mod  # noqa: E402
from hardcap_backstop import apply_hard_cap_backstop  # noqa: E402
from conflict_fixtures import LIVING_DOC_KIND  # noqa: E402
from merge_driver import FileOutcome, MergeReport  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402  # shipped scrub; git_env is dev-only

CAP = low_doc_parts.CAP
P1, P2, P9 = (low_doc_parts.part_rel(n) for n in (1, 2, 9))
SPLIT_CLASS = "low-part-split"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def entry(n, size=200):
    """One `### L<n>: …` one-line entry, padded to exactly `size` chars."""
    body = "### L%d: low issue %d" % (n, n)
    return "%s %s\n" % (body, "x" * (size - len(body) - 2))


def low_doc(numbers, size=200, part=1):
    return low_doc_parts.part_header(part) + "".join(entry(n, size) for n in numbers)


def headings(text):
    return re.findall(r"^### (L\d+)", text, re.M)


BASE_NUMS = list(range(1, 246))
BASE_P1 = low_doc(BASE_NUMS)                              # 49,000 chars of entries
OURS_NEW, THEIRS_NEW = [900, 901, 902, 903], [950, 951, 952, 953]
OURS_P1 = low_doc(BASE_NUMS + OURS_NEW)                   # about 49,800: under the cap
THEIRS_P1 = low_doc(BASE_NUMS + THEIRS_NEW)               # under the cap
MERGED_NEW = [900, 950, 901, 951, 902, 952, 903, 953]     # interleaved: the moved tail is both sides'
MERGED_P1 = low_doc(BASE_NUMS + MERGED_NEW)               # over the cap: the merge pushed it
BASE_P2 = low_doc_parts.part_header(2) + "".join(entry(n) for n in (1000, 1001))
assert len(OURS_P1) <= CAP and len(THEIRS_P1) <= CAP, "the fixture starts under the cap"
assert len(MERGED_P1) > CAP, "the fixture ends over the cap"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          env=clean_git_env(**IDENTITY))


def write(repo, rel, content):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def unmerged(repo):
    """`git ls-files -u`: the index's own statement of what is still conflicted."""
    out = git(repo, "ls-files", "-u").stdout
    return {ln.split("\t", 1)[1] for ln in out.splitlines() if ln.strip()}


def stage(repo, path, n):
    """Index stage `n` of `path` (0 = resolved), or None when the index holds no such stage."""
    r = git(repo, "show", ":%d:%s" % (n, path))
    return r.stdout if r.returncode == 0 else None


def staged_names(repo):
    return set(git(repo, "diff", "--cached", "--name-only").stdout.split())


def merge_repo(tmp_path, base, ours, theirs, merged):
    """A real tmp git repo with an OPEN `git merge --no-commit`: each `{rel: text}` dict is one
    commit (base, then ours on `feat`, then theirs on `master`); the merged texts are written and
    staged as the driver's auto-resolution, with `MERGE_HEAD` present so the backstop reads both
    sides off the commits. This is the state the driver is in when the backstop runs."""
    if shutil.which("git") is None:
        pytest.skip("git unavailable")
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    for rel, text in base.items():
        write(repo, rel, text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    for branch, files in (("feat", ours), ("master", theirs)):
        git(repo, "checkout", "-q", *(["-b", "feat"] if branch == "feat" else ["master"]))
        for rel, text in files.items():
            write(repo, rel, text)
        git(repo, "add", "-A")
        assert git(repo, "commit", "-q", "-m", branch).returncode == 0
    git(repo, "checkout", "-q", "feat")
    git(repo, "merge", "--no-commit", "--no-ff", "master")
    for rel, text in merged.items():
        write(repo, rel, text)
        git(repo, "add", "--", rel)
    return repo


def low_repo(tmp_path, p2_present=True, ours=OURS_P1, theirs=THEIRS_P1, merged=MERGED_P1):
    """Part 1 merged over the cap by the merge; part 2 on base (or absent) and untouched by it."""
    base = {P1: BASE_P1, **({P2: BASE_P2} if p2_present else {})}
    return merge_repo(tmp_path, base, {P1: ours}, {P1: theirs}, {P1: merged})


def report(auto=(), conflicted=(), deferred=()):
    """The driver's `MergeReport` after its resolve loop: one outcome dict per auto-resolved path."""
    out = [dataclasses.asdict(FileOutcome(p, LIVING_DOC_KIND, "auto-resolved",
                                          resolved_classes=["log-entry-insertion"])) for p in auto]
    return MergeReport(base_ref="master", merged_clean=False, conflicted=list(conflicted),
                       auto_resolved=list(auto), deferred=list(deferred), outcomes=out)


def outcome_of(rep, path):
    return next(o for o in rep.outcomes if o["path"] == path)


def pair(repo, first=P1):
    """`first` and part 2 as bytes (part 2 is None when the file is absent)."""
    p2 = repo / P2
    return (repo / first).read_bytes(), (p2.read_bytes() if p2.is_file() else None)


def call(rep, repo):
    """One backstop call, stdout captured: the driver's JSON must stay clean."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        apply_hard_cap_backstop(str(repo), rep)
    return buf.getvalue()


def spy_on_split(monkeypatch):
    """Record every `split_part` call and delegate to the real one."""
    calls, real = [], low_doc_parts.split_part

    def spy(root, rel, *args, **kwargs):
        calls.append(rel)
        return real(root, rel, *args, **kwargs)

    monkeypatch.setattr(low_doc_parts, "split_part", spy)
    return calls


def assert_handed_back(rep, repo, before, rel=P1, ours=OURS_P1, theirs=THEIRS_P1, size=None):
    """What every deferral shares: out of `auto_resolved`, into `deferred` with a reason naming the
    char count and the cap, part 2 as it was, git's markers and unmerged stages back."""
    assert rep.deferred == [rel] and rep.auto_resolved == [], rep.to_json()
    o = outcome_of(rep, rel)
    assert o["action"] == "deferred", rep.to_json()
    assert str(size or len(MERGED_P1)) in o["reason"] and str(CAP) in o["reason"], o["reason"]
    assert pair(repo, rel)[1] == before[1]                       # part 2 restored (deleted if it was absent)
    assert P2 not in staged_names(repo)
    assert (repo / rel).read_text(encoding="utf-8").count("<<<<<<<") == 1
    assert unmerged(repo) == {rel} and stage(repo, rel, 0) is None
    assert stage(repo, rel, 2) == ours and stage(repo, rel, 3) == theirs


# --- in scope: the merge pushed the part over the cap ------------------------------------------


def assert_split(repo, rep, p2_before_text, expected_count):
    p1 = (repo / P1).read_text(encoding="utf-8")
    p2 = (repo / P2).read_text(encoding="utf-8")
    assert len(p1) <= CAP and len(p2) <= CAP
    assert low_doc_parts.count_lows(p1 + p2) == expected_count
    assert not set(headings(p1)) & set(headings(p2))
    assert sorted(headings(p1) + headings(p2)) == sorted(headings(MERGED_P1 + p2_before_text))
    assert {P1, P2} <= staged_names(repo)                    # both staged; P1 differs from ours
    assert stage(repo, P1, 0) == p1 and stage(repo, P2, 0) == p2
    assert unmerged(repo) == set()
    assert rep.auto_resolved == [P1] and rep.deferred == []
    assert SPLIT_CLASS in outcome_of(rep, P1)["resolved_classes"]
    return p1, p2


def test_split_moves_the_trailing_entries_into_the_existing_next_part(tmp_path):
    repo = low_repo(tmp_path)
    rep = report(auto=[P1], conflicted=[P1])
    assert call(rep, repo) == ""
    p1, p2 = assert_split(repo, rep, BASE_P2, low_doc_parts.count_lows(MERGED_P1 + BASE_P2))
    assert p1 != OURS_P1 and p2.startswith(low_doc_parts.part_header(2))
    assert "L953" in p2 + p1 and "L1000" in p2                # both sides' entries and part 2's own


def test_split_creates_a_missing_next_part_and_stages_it(tmp_path):
    repo = low_repo(tmp_path, p2_present=False)
    rep = report(auto=[P1], conflicted=[P1])
    assert call(rep, repo) == ""
    assert_split(repo, rep, "", low_doc_parts.count_lows(MERGED_P1))


def test_a_second_pass_over_the_split_pair_changes_nothing(tmp_path):
    repo = low_repo(tmp_path)
    rep = report(auto=[P1], conflicted=[P1])
    call(rep, repo)
    before = pair(repo)
    call(rep, repo)
    assert pair(repo) == before and rep.auto_resolved == [P1]
    assert outcome_of(rep, P1)["resolved_classes"].count(SPLIT_CLASS) == 1


def test_a_conflicted_next_part_that_is_also_auto_resolved_still_splits(tmp_path):
    repo = low_repo(tmp_path)
    rep = report(auto=[P1, P2], conflicted=[P1, P2])
    call(rep, repo)
    assert SPLIT_CLASS in outcome_of(rep, P1)["resolved_classes"] and rep.deferred == []
    assert P2 in rep.auto_resolved and {P1, P2} <= staged_names(repo)


@pytest.mark.parametrize("seed", range(6))
def test_split_keeps_every_heading_exactly_once_for_random_entry_sizes(tmp_path, seed):
    rng = random.Random(seed)
    head = low_doc_parts.part_header(1)
    sizes, nums, total = {}, [], len(head)
    while total < 48_900:
        nums.append(len(nums) + 1)
        sizes[nums[-1]] = rng.randint(100, 400)
        total += sizes[nums[-1]]
    for n in (900, 901, 902, 950, 951, 952):
        sizes[n] = 200

    def sized(ns):
        return "".join(entry(n, sizes[n]) for n in ns)

    ours = head + sized(nums + [900, 901, 902])
    theirs = head + sized(nums + [950, 951, 952])
    merged = head + sized(nums + [900, 950, 901, 951, 902, 952])
    assert len(ours) <= CAP and len(theirs) <= CAP and len(merged) > CAP
    p2_present = seed % 2 == 0
    base = {P1: head + sized(nums), **({P2: BASE_P2} if p2_present else {})}
    repo = merge_repo(tmp_path, base, {P1: ours}, {P1: theirs}, {P1: merged})
    rep = report(auto=[P1], conflicted=[P1])
    assert call(rep, repo) == ""
    p1, p2 = (repo / P1).read_text(encoding="utf-8"), (repo / P2).read_text(encoding="utf-8")
    assert len(p1) <= CAP and len(p2) <= CAP
    expected = headings(merged) + (headings(BASE_P2) if p2_present else [])
    assert sorted(headings(p1) + headings(p2)) == sorted(expected)
    assert {P1, P2} <= staged_names(repo) and rep.auto_resolved == [P1]
    assert SPLIT_CLASS in outcome_of(rep, P1)["resolved_classes"]


# --- out of scope: today's outcome ------------------------------------------------------------


@pytest.mark.parametrize("over_side", ["ours", "theirs"])
def test_a_side_already_over_the_cap_leaves_the_files_alone(tmp_path, monkeypatch, over_side):
    calls = spy_on_split(monkeypatch)
    repo = low_repo(tmp_path, **{over_side: MERGED_P1})
    before = pair(repo)
    rep = report(auto=[P1], conflicted=[P1])
    assert call(rep, repo) == ""
    assert pair(repo) == before and calls == []
    assert rep.auto_resolved == [P1] and rep.deferred == []
    assert SPLIT_CLASS not in outcome_of(rep, P1)["resolved_classes"]
    assert unmerged(repo) == set() and stage(repo, P1, 0) is not None


def test_a_part_at_or_under_the_cap_is_left_alone(tmp_path, monkeypatch):
    calls = spy_on_split(monkeypatch)
    repo = low_repo(tmp_path, merged=OURS_P1)
    before = pair(repo)
    rep = report(auto=[P1], conflicted=[P1])
    call(rep, repo)
    assert pair(repo) == before and calls == [] and rep.auto_resolved == [P1]


# --- in scope but cannot be made to fit: restore both files, markers back, defer ---------------


def split_raises(root, rel, *args, **kwargs):
    raise low_doc_parts.LowSplitError("boom")


def split_half_written_then_raises(root, rel, *args, **kwargs):
    for r in (rel, low_doc_parts.next_part_rel(rel)):
        (Path(root) / r).write_text("half-written", encoding="utf-8")
    raise low_doc_parts.LowSplitError("boom")


def split_does_nothing(root, rel, *args, **kwargs):
    return 0                                                # part 1 is still over the cap


def split_drops_the_tail(root, rel, *args, **kwargs):
    path = Path(root) / rel                                 # fits, but loses entries
    path.write_text(path.read_text(encoding="utf-8")[:49_000], encoding="utf-8")
    return 1


FAILING_SPLITS = {"raises": split_raises, "half-written": split_half_written_then_raises,
                  "does-nothing": split_does_nothing, "drops-the-tail": split_drops_the_tail}


@pytest.mark.parametrize("p2_present", [True, False])
@pytest.mark.parametrize("name", sorted(FAILING_SPLITS))
def test_a_failed_split_restores_both_files_puts_the_markers_back_and_defers(
        tmp_path, monkeypatch, name, p2_present):
    repo = low_repo(tmp_path, p2_present=p2_present)
    before = pair(repo)
    monkeypatch.setattr(low_doc_parts, "split_part", FAILING_SPLITS[name])
    rep = report(auto=[P1], conflicted=[P1])
    assert call(rep, repo) == ""
    assert_handed_back(rep, repo, before)
    assert "half-written" not in (repo / P1).read_text(encoding="utf-8")


@pytest.mark.parametrize("p2_present", [True, False])
def test_a_split_that_fails_the_zero_drop_reverify_is_undone_and_deferred(
        tmp_path, monkeypatch, p2_present):
    def finds_a_drop(ours, theirs, resolved, *, base, mechanical_applied):
        return verify_mod.VerifyResult(verdict=verify_mod.DROPS_DETECTED,
                                       dropped=[("log", entry(2).strip())])

    repo = low_repo(tmp_path, p2_present=p2_present)
    before = pair(repo)
    monkeypatch.setattr(verify_mod, "verify", finds_a_drop)
    rep = report(auto=[P1], conflicted=[P1])
    assert call(rep, repo) == ""
    assert_handed_back(rep, repo, before)


def test_a_conflicted_next_part_defers_without_a_split(tmp_path, monkeypatch):
    calls = spy_on_split(monkeypatch)
    repo = low_repo(tmp_path)
    before = pair(repo)
    rep = report(auto=[P1], conflicted=[P1, P2])
    assert call(rep, repo) == ""
    assert calls == []
    assert_handed_back(rep, repo, before)


def test_the_last_part_has_no_next_part_and_defers_without_a_split(tmp_path, monkeypatch):
    calls = spy_on_split(monkeypatch)
    base, ours = low_doc(BASE_NUMS, part=9), low_doc(BASE_NUMS + OURS_NEW, part=9)
    theirs = low_doc(BASE_NUMS + THEIRS_NEW, part=9)
    merged = low_doc(BASE_NUMS + MERGED_NEW, part=9)
    repo = merge_repo(tmp_path, {P9: base}, {P9: ours}, {P9: theirs}, {P9: merged})
    before = pair(repo, P9)
    rep = report(auto=[P9], conflicted=[P9])
    assert call(rep, repo) == ""
    assert calls == []
    assert_handed_back(rep, repo, before, rel=P9, ours=ours, theirs=theirs, size=len(merged))


# --- a non-Low living doc keeps the existing roll path -----------------------------------------

ROADMAP = "three-pillars-docs/product_roadmap.md"
ROADMAP_ARCH = living_doc_archive.ARCHIVES[ROADMAP]
ROADMAP_HARD = file_size_guard.char_caps(ROADMAP, False)[1]
ROADMAP_HEAD = "# Product Roadmap\n\n## History\n\n"
ROADMAP_ARCH_BASE = "# Product Roadmap — Archive\n\n## History\n\n- 2026-09-01 — ancient entry\n"


def roadmap_doc(numbers):
    def row(n):
        body = "- 2026-%02d-%02d — entry %d" % (n // 28 + 1, n % 28 + 1, n)
        return "%s %s\n" % (body, "x" * (700 - len(body) - 1))
    return ROADMAP_HEAD + "".join(row(n) for n in numbers)


def test_a_non_low_doc_still_rolls_to_its_archive_and_never_splits(tmp_path, monkeypatch):
    calls = spy_on_split(monkeypatch)
    ours = roadmap_doc(list(range(2, 22)) + [1])
    theirs = roadmap_doc([30, 29, 28, 1])
    merged = roadmap_doc(list(range(2, 22)) + [30, 29, 28, 1])
    assert len(ours) < ROADMAP_HARD and len(theirs) < ROADMAP_HARD < len(merged)
    repo = merge_repo(tmp_path, {ROADMAP: roadmap_doc([1]), ROADMAP_ARCH: ROADMAP_ARCH_BASE},
                      {ROADMAP: ours}, {ROADMAP: theirs}, {ROADMAP: merged})
    rep = report(auto=[ROADMAP], conflicted=[ROADMAP])
    assert call(rep, repo) == ""
    assert calls == [] and rep.auto_resolved == [ROADMAP] and rep.deferred == []
    classes = outcome_of(rep, ROADMAP)["resolved_classes"]
    assert "hard-cap-rollover" in classes and SPLIT_CLASS not in classes
    assert len((repo / ROADMAP).read_text(encoding="utf-8")) <= ROADMAP_HARD
    assert {ROADMAP, ROADMAP_ARCH} <= staged_names(repo)
