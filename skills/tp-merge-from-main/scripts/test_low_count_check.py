"""`apply_low_count_check` / `apply_post_merge_passes` — the post-merge count check (Task 2.4).

`known_issues.md`'s count line is the one line in the Low-doc pair that BOTH sides rewrite: the
`low-count-line` class computes it as `ours + theirs - base`, so an auto-resolved merge can stage a
count line NEITHER side wrote. This check re-derives it from the merged Low parts: the number must
equal the `### L` headings across them. A mismatch, or a Low part that never resolved, restores
git's conflict markers (`git checkout -m`) and defers the doc - the merge's own drop guard.

The merged state is hand-built here rather than driven through Task 2.3's resolver wiring, so this
module tests the check alone: the fixture is the state the driver is in when the post-merge passes
run (an open `git merge --no-commit`, the two docs resolved and staged).

Rule: skills/_shared/test-fragility.md - behaviour only. A deferred doc keeps git's conflict
markers, which QUOTE both sides' text, so the deferred arms assert the merge DECISIONS (report
buckets, the outcome reason, `git ls-files -u`), never the doc's text.
"""
import contextlib
import dataclasses
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
import low_doc_parts  # noqa: E402
from low_count_check import apply_low_count_check  # noqa: E402
from conflict_fixtures import LIVING_DOC_KIND  # noqa: E402
from merge_driver import FileOutcome, MergeReport  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402  # shipped scrub; git_env is dev-only

KI = "three-pillars-docs/known_issues.md"
LOW = low_doc_parts.FIRST_REL
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def count(n):
    """One count line: the number `n` and the same arrow target on every side."""
    return f"{n} Low issues → [known_issues_low.md](known_issues_low.md)"


def ki(n):
    """`known_issues.md` whose count line reads `n`, followed by the `## History` section."""
    return ("*Last updated: 2026-05-01*\n\n# Known issues\n\n" + count(n) +
            "\n\n## History\n\n- 2026-05-01 - base entry\n")


def low(numbers):
    """A Low part holding one `### L<n>: ...` entry per number."""
    return low_doc_parts.part_header(1) + "".join(f"### L{n}: low {n}\n" for n in numbers)


BASE_KI, BASE_LOW = ki(1), low([1])
OURS_KI, OURS_LOW = ki(2), low([1, 2])
THEIRS_KI, THEIRS_LOW = ki(3), low([1, 3, 4])
MERGED_LOW = low([1, 2, 3, 4])                      # four headings: the merge added three
assert low_doc_parts.count_lows(MERGED_LOW) == 4, "the merged Low doc has four headings"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          env=clean_git_env(**IDENTITY))


def write(repo, rel, content):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def unmerged(repo, path=None):
    """`git ls-files -u`: the index's own statement of what is still conflicted."""
    args = ["ls-files", "-u"] + (["--", path] if path else [])
    out = git(repo, *args).stdout
    return {ln.split("\t", 1)[1] for ln in out.splitlines() if ln.strip()}


def stage(repo, path, n):
    """Index stage `n` of `path` (0 = resolved), or None when the index holds no such stage."""
    r = git(repo, "show", ":%d:%s" % (n, path))
    return r.stdout if r.returncode == 0 else None


def report(auto=(), conflicted=(), deferred=()):
    """The driver's `MergeReport` after its resolve loop: one outcome dict per auto-resolved path."""
    out = [dataclasses.asdict(FileOutcome(p, LIVING_DOC_KIND, "auto-resolved",
                                          resolved_classes=["low-count-line"])) for p in auto]
    return MergeReport(base_ref="x", merged_clean=False, conflicted=list(conflicted),
                       auto_resolved=list(auto), deferred=list(deferred), outcomes=out)


def outcome_of(rep, path):
    return next(o for o in rep.outcomes if o["path"] == path)


def merge_repo(tmp_path, merged_ki):
    """A real tmp git repo with an OPEN `git merge --no-commit` whose two docs are resolved to
    `merged_ki` / `MERGED_LOW` and staged. Both sides rewrote the count line, so `known_issues.md`
    really conflicted; `MERGE_HEAD` is present so the check can read both sides off the commits."""
    if shutil.which("git") is None:
        pytest.skip("git unavailable")
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    write(repo, KI, BASE_KI)
    write(repo, LOW, BASE_LOW)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    for branch, ki_doc, low_doc in (("feat", OURS_KI, OURS_LOW), ("master", THEIRS_KI, THEIRS_LOW)):
        git(repo, "checkout", "-q", *(["-b", "feat"] if branch == "feat" else ["master"]))
        write(repo, KI, ki_doc)
        write(repo, LOW, low_doc)
        git(repo, "add", "-A")
        assert git(repo, "commit", "-q", "-m", branch).returncode == 0
    git(repo, "checkout", "-q", "feat")
    git(repo, "merge", "--no-commit", "--no-ff", "master")
    # both docs really conflict: the count lines differ AND both sides append Lows at the same spot
    assert unmerged(repo) == {KI, LOW}, unmerged(repo)
    write(repo, KI, merged_ki)
    write(repo, LOW, MERGED_LOW)
    git(repo, "add", "--", KI, LOW)
    return repo


def call(rep, repo):
    """One check call, stdout captured: the driver's JSON must stay clean."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        apply_low_count_check(str(repo), rep)
    return buf.getvalue()


def resolved_report(tmp_path, value):
    """The resolved-and-staged state with count line `value`, plus the report that matches it."""
    repo = merge_repo(tmp_path, ki(value))
    return repo, report(auto=[KI, LOW], conflicted=[KI, LOW])


# --- the count line the merge computed is checked against the merged Low doc --------------------

def test_a_count_line_that_matches_the_headings_is_left_auto_resolved(tmp_path):
    """2 + 3 - 1 = 4 and the merged Low doc holds four headings, so the auto-resolution stands: the
    doc is byte-identical, still staged, still in `auto_resolved`, nothing printed."""
    repo, rep = resolved_report(tmp_path, 4)
    before = (repo / KI).read_bytes()
    assert call(rep, repo) == ""
    assert (repo / KI).read_bytes() == before
    assert rep.auto_resolved == [KI, LOW] and rep.deferred == [], rep.to_json()
    assert unmerged(repo) == set() and stage(repo, KI, 0) is not None


def test_a_count_line_that_does_not_match_defers_the_doc(tmp_path):
    """The merged line says 5, the merged Low doc holds 4 headings: the count is the merge's own
    arithmetic, so the doc is handed back - markers and unmerged stages restored, out of
    `auto_resolved`, into `deferred` with a reason naming the class and both numbers."""
    repo, rep = resolved_report(tmp_path, 5)
    assert call(rep, repo) == ""
    assert rep.deferred == [KI] and rep.auto_resolved == [LOW], rep.to_json()
    reason = outcome_of(rep, KI)["reason"]
    assert "low-count-line" in reason and "5" in reason and "4" in reason, reason
    assert outcome_of(rep, KI)["action"] == "deferred", rep.to_json()
    assert unmerged(repo, KI) == {KI} and stage(repo, KI, 0) is None
    assert stage(repo, KI, 2) == OURS_KI and stage(repo, KI, 3) == THEIRS_KI


def test_an_unresolved_low_part_defers_the_doc_without_counting(tmp_path):
    """A Low part still conflicted means the count cannot be checked at all: the doc defers with a
    reason naming the part, and no comparison of numbers is claimed."""
    repo = merge_repo(tmp_path, ki(4))
    rep = report(auto=[KI], conflicted=[KI, LOW], deferred=[LOW])
    assert call(rep, repo) == ""
    assert rep.deferred == [LOW, KI] and rep.auto_resolved == [], rep.to_json()
    reason = outcome_of(rep, KI)["reason"]
    assert "low-count-line" in reason and LOW in reason, reason
    assert unmerged(repo, KI) == {KI} and stage(repo, KI, 0) is None


# --- out of scope: today's outcome, nothing changes ---------------------------------------------

def test_a_count_line_one_side_wrote_is_left_alone(tmp_path):
    """The merged line is byte-identical to ours' `C(2)`: this is not the class's recomputed line,
    so the check has no claim on it - untouched even though 2 != 4 headings."""
    repo, rep = resolved_report(tmp_path, 2)
    before = (repo / KI).read_bytes()
    assert call(rep, repo) == ""
    assert (repo / KI).read_bytes() == before
    assert rep.auto_resolved == [KI, LOW] and rep.deferred == [], rep.to_json()
    assert unmerged(repo) == set() and stage(repo, KI, 0) is not None


def test_a_doc_that_was_not_auto_resolved_is_a_no_op(tmp_path):
    """`known_issues.md` is not in `auto_resolved` (the resolve loop deferred it), so nothing here
    runs: the buckets and the index stay exactly as the loop left them."""
    repo = merge_repo(tmp_path, ki(9))
    rep = report(auto=[LOW], conflicted=[KI, LOW], deferred=[KI])
    before = (repo / KI).read_bytes()
    assert call(rep, repo) == ""
    assert (repo / KI).read_bytes() == before
    assert rep.deferred == [KI] and rep.auto_resolved == [LOW], rep.to_json()
    assert unmerged(repo) == set() and stage(repo, KI, 0) is not None


def test_a_check_that_raises_defers_instead_of_raising(tmp_path, monkeypatch):
    """Totality: the check runs just before the driver emits its JSON, so a raise would lose the
    whole report. A counting failure defers the doc (fail-safe) and prints nothing."""
    def boom(root):
        raise RuntimeError("cannot count")
    monkeypatch.setattr(low_doc_parts, "total_lows", boom)
    repo, rep = resolved_report(tmp_path, 4)
    assert call(rep, repo) == ""
    assert rep.deferred == [KI] and rep.auto_resolved == [LOW], rep.to_json()
    assert "low-count" in outcome_of(rep, KI)["reason"], rep.to_json()
    assert unmerged(repo, KI) == {KI}


# --- the seam: both post-merge passes run, hard-cap first ---------------------------------------

def test_post_merge_runs_the_hard_cap_pass_then_the_count_check(tmp_path, monkeypatch):
    """`apply_post_merge_passes` is the driver's one post-merge call. The hard-cap backstop goes
    FIRST because a Low-part split keeps the `### L` count, so the count check afterwards still
    reads the right number over the split parts."""
    import post_merge

    seen = []
    monkeypatch.setattr(post_merge, "apply_hard_cap_backstop",
                        lambda repo, rep: seen.append("hard-cap"))
    monkeypatch.setattr(post_merge, "apply_low_count_check",
                        lambda repo, rep: seen.append("low-count"))
    repo = tmp_path / "r"
    repo.mkdir()
    post_merge.apply_post_merge_passes(str(repo), report(auto=[KI, LOW]))
    assert seen == ["hard-cap", "low-count"], seen


# --- a hand-back after the hard-cap backstop rolled the doc puts the archive back too ----------

ARCH = "three-pillars-docs/known_issues_resolved.md"


def test_a_count_hand_back_undoes_the_hard_cap_rollover(tmp_path):
    """Regression (PR #321 r1): the backstop runs first and rolls History out of a doc the merge
    pushed over its cap into the archive, staging both. A count mismatch then hands the doc back
    with `git checkout -m`, which restores only the doc, so the archive must be undone too - or
    every rolled History line sits in both the restored doc and the staged archive."""
    import post_merge

    hist = "".join(f"- 2026-04-{i % 28 + 1:02d} — rolled entry {i} {'h' * 90}\n" for i in range(220))
    medium = "# Known issues\n\n### M1: one medium\n- body\n\n"     # an atom for the re-verify
    merged = ki(5).replace("# Known issues\n\n", medium) + hist   # 5 != 4 headings; over the cap
    repo = merge_repo(tmp_path, merged)
    rep = report(auto=[KI, LOW], conflicted=[KI, LOW])
    with contextlib.redirect_stdout(io.StringIO()):
        post_merge.apply_post_merge_passes(str(repo), rep)
    assert rep.deferred == [KI], f"the count check should defer the doc: {rep.to_json()}"
    reason = outcome_of(rep, KI)["reason"]
    assert "undone" in reason, f"the backstop should have rolled, and the hand-back undone it: {reason}"
    assert "hard-cap-rollover" not in outcome_of(rep, KI)["resolved_classes"], \
        f"an undone roll must not stay listed as a resolved class: {rep.to_json()}"
    assert not (repo / ARCH).exists(), "the archive the roll created must be removed again"
    assert stage(repo, ARCH, 0) is None, "the archive the roll staged must be unstaged again"
    assert unmerged(repo, KI) == {KI}, "the doc must be handed back with its unmerged stages"
    ki_sides = (repo / KI).read_text(encoding="utf-8") + (stage(repo, KI, 2) or "") + hist
    arch_now = ((repo / ARCH).read_text(encoding="utf-8") if (repo / ARCH).exists() else "") + \
        (stage(repo, ARCH, 0) or "")
    both = [ln for ln in arch_now.splitlines() if "rolled entry" in ln and ln in ki_sides]
    assert not both, f"{len(both)} History lines sit in both the doc and the archive"
