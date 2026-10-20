"""`apply_hard_cap_backstop` — the B3 hard-cap backstop (Behavior 11).

The backstop acts on one case: the merge pushed an auto-resolved living doc over its hard cap while
NEITHER side was over it. Then it rolls the doc over, re-verifies it with its archive and stages it,
or restores the snapshot, runs `git checkout -m` and defers it. Every other case keeps today's
outcome: staged, untouched (the commit hook's `rollover-due` warning is the only signal).

Rule: skills/_shared/test-fragility.md — behaviour only. A deferred file keeps git's conflict markers,
which QUOTE both sides' text, so the deferred arms assert the merge DECISIONS (report buckets, the
outcome reason, `git ls-files -u`), never the file's text.
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
import doc_rollover  # noqa: E402
import file_size_guard  # noqa: E402
import living_doc_archive  # noqa: E402
import verify as verify_mod  # noqa: E402
from hardcap_backstop import apply_hard_cap_backstop  # noqa: E402
from merge_driver import FileOutcome, MergeReport  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402  # shipped scrub; git_env is dev-only

LIVE = "three-pillars-docs/product_roadmap.md"
ARCH = living_doc_archive.ARCHIVES[LIVE]
SOFT, HARD = file_size_guard.char_caps(LIVE, False)
ARCH_BASE = "# Product Roadmap — Archive\n\n## History\n\n- 2026-09-01 — ancient entry\n"
HEAD = "# Product Roadmap\n\n## History\n\n"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def entry(n, size=700):
    """One plain-date History bullet, padded to exactly `size` chars."""
    body = "- 2026-%02d-%02d — entry %d" % (n // 28 + 1, n % 28 + 1, n)
    return "%s %s\n" % (body, "x" * (size - len(body) - 1))


def doc(numbers, size=700):
    return HEAD + "".join(entry(n, size) for n in numbers)


ALL = list(range(2, 22)) + [30, 29, 28, 1]
BASE_DOC = doc([1])
OURS_DOC = doc(list(range(2, 22)) + [1])            # under the hard cap
THEIRS_DOC = doc([30, 29, 28, 1])                   # under the hard cap
MERGED_DOC = doc(ALL)                               # over it: the merge pushed it
assert len(OURS_DOC) < HARD and len(THEIRS_DOC) < HARD, "the fixture starts under the cap"
assert len(MERGED_DOC) > HARD, "the fixture ends over the cap"


def roll_one_entry_but_stay_over_cap(repo_root, rel):
    """Stands in for a roll that moved an entry yet left the doc over the HARD cap."""
    path = Path(repo_root) / rel
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(lines[:4] + lines[5:]), encoding="utf-8")
    return doc_rollover.RollToCapResult(1, len("".join(lines)), len("".join(lines[:4] + lines[5:])),
                                        SOFT, True)


def roll_raises(repo_root, rel):
    (Path(repo_root) / rel).write_text("half-written", encoding="utf-8")
    raise RuntimeError("boom")


def verify_finds_a_drop(ours, theirs, resolved, *, base, mechanical_applied):
    return verify_mod.VerifyResult(verdict=verify_mod.DROPS_DETECTED,
                                   dropped=[("log", entry(2).strip())])


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


def pair(repo):
    """The live doc and its archive, as bytes."""
    return (repo / LIVE).read_bytes(), (repo / ARCH).read_bytes()


def report(auto=(), conflicted=(), deferred=()):
    """The driver's `MergeReport` after its resolve loop: one outcome dict per auto-resolved path."""
    out = [dataclasses.asdict(FileOutcome(p, "living-doc", "auto-resolved",
                                          resolved_classes=["log-entry-insertion"])) for p in auto]
    return MergeReport(base_ref="master", merged_clean=False, conflicted=list(conflicted),
                       auto_resolved=list(auto), deferred=list(deferred), outcomes=out)


def outcome_of(rep, path):
    return next(o for o in rep.outcomes if o["path"] == path)


def merge_repo(tmp_path, ours=OURS_DOC, theirs=THEIRS_DOC, merged=MERGED_DOC,
               ours_arch=ARCH_BASE, theirs_arch=ARCH_BASE):
    """A real tmp git repo with an OPEN `git merge --no-commit`: the living doc resolved to `merged`
    and staged, the archive staged unless both sides edited it, `MERGE_HEAD` present so the backstop
    reads both sides off the commits. This is the state the driver is in when B3 runs."""
    if shutil.which("git") is None:
        pytest.skip("git unavailable")
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    write(repo, LIVE, BASE_DOC)
    write(repo, ARCH, ARCH_BASE)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    for branch, live, arch in (("feat", ours, ours_arch), ("master", theirs, theirs_arch)):
        git(repo, "checkout", "-q", *(["-b", "feat"] if branch == "feat" else ["master"]))
        write(repo, LIVE, live)
        write(repo, ARCH, arch)
        git(repo, "add", "-A")
        assert git(repo, "commit", "-q", "-m", branch).returncode == 0
    git(repo, "checkout", "-q", "feat")
    git(repo, "merge", "--no-commit", "--no-ff", "master")
    write(repo, LIVE, merged)
    git(repo, "add", "--", LIVE)
    if ARCH not in unmerged(repo):
        git(repo, "add", "--", ARCH)
    return repo


def conflicted_archive_repo(tmp_path):
    """`merge_repo` where BOTH sides edited the archive, so it really is conflicted."""
    return merge_repo(tmp_path, ours_arch=ARCH_BASE + "- 2026-08-01 — ours archived entry\n",
                      theirs_arch=ARCH_BASE + "- 2026-08-02 — theirs archived entry\n")


def call(rep, repo):
    """One backstop call, stdout captured: the driver's JSON must stay clean."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        apply_hard_cap_backstop(str(repo), rep)
    return buf.getvalue()


def assert_deferred(rep, repo):
    """What the in-scope deferrals share: out of `auto_resolved`, into `deferred` with a reason
    naming the cap, and git's unmerged stages of the doc back in the index."""
    assert rep.deferred == [LIVE] and rep.auto_resolved == [], rep.to_json()
    assert outcome_of(rep, LIVE)["action"] == "deferred", rep.to_json()
    reason = outcome_of(rep, LIVE)["reason"]
    assert "cap" in reason.lower() and str(HARD) in reason, reason
    assert unmerged(repo) == {LIVE} and stage(repo, LIVE, 0) is None
    assert stage(repo, LIVE, 2) == OURS_DOC and stage(repo, LIVE, 3) == THEIRS_DOC


# --- in scope: the merge pushed the doc over the cap -------------------------------------------

def test_in_scope_doc_is_rolled_staged_and_tagged(tmp_path):
    """Behavior 11's rolled arm: both sides under the cap and the merge over it, so the backstop
    rolls the oldest bullets into the archive and stages both files at or under the cap."""
    repo = merge_repo(tmp_path)
    rep = report(auto=[LIVE])
    assert call(rep, repo) == ""
    live = (repo / LIVE).read_text(encoding="utf-8")
    arch = (repo / ARCH).read_text(encoding="utf-8")
    assert len(live) <= HARD, len(live)
    assert entry(2) in live and entry(30) not in live and entry(30) in arch
    for n in ALL:                                        # nothing lost, nothing duplicated
        assert (live + arch).count(entry(n)) == 1, n
    assert unmerged(repo) == set() and stage(repo, LIVE, 0) == live and stage(repo, ARCH, 0) == arch
    assert rep.auto_resolved == [LIVE] and rep.deferred == [], rep.to_json()
    assert outcome_of(rep, LIVE)["action"] == "auto-resolved"
    assert "hard-cap-rollover" in outcome_of(rep, LIVE)["resolved_classes"], rep.to_json()


def test_re_verify_sees_the_pair_before_and_after_the_roll(tmp_path, monkeypatch):
    """The re-verify is the merge's own zero-drop check over the rolled pair: ours is the live doc
    plus its archive as they were before the roll, theirs is empty, the resolved text is the pair
    after it, with no base and a mechanical resolution applied."""
    repo = merge_repo(tmp_path)
    seen, real = [], verify_mod.verify

    def spy(ours, theirs, resolved, *, base, mechanical_applied):
        seen.append((ours, theirs, resolved, base, mechanical_applied))
        return real(ours, theirs, resolved, base=base, mechanical_applied=mechanical_applied)
    monkeypatch.setattr(verify_mod, "verify", spy)
    call(report(auto=[LIVE]), repo)
    assert len(seen) == 1, len(seen)
    ours, theirs, resolved, base, mechanical = seen[0]
    assert ours == MERGED_DOC + "\n" + ARCH_BASE, ours[:120]
    assert theirs == "" and base is None and mechanical is True
    assert resolved == ((repo / LIVE).read_text(encoding="utf-8") + "\n"
                        + (repo / ARCH).read_text(encoding="utf-8"))


@pytest.mark.parametrize("patch", [
    pytest.param(("doc_rollover", "roll_to_cap", roll_one_entry_but_stay_over_cap), id="still-over"),
    pytest.param(("verify_mod", "verify", verify_finds_a_drop), id="reverify-drop"),
    pytest.param(("doc_rollover", "roll_to_cap", roll_raises), id="roll-raises"),
])
def test_an_in_scope_failure_restores_and_defers(tmp_path, monkeypatch, patch):
    """Behavior 11: a roll that moved entries but left the doc over the hard cap, a drop found by the
    re-verify, and a roll that raises each defer: the pre-roll bytes come back, git's unmerged
    stages return for the doc, and nothing is raised or printed."""
    obj, name, fake = patch
    monkeypatch.setattr(globals()[obj], name, fake)
    repo = merge_repo(tmp_path)
    before = pair(repo)
    rep = report(auto=[LIVE])
    assert call(rep, repo) == ""
    assert_deferred(rep, repo)
    assert (repo / ARCH).read_bytes() == before[1], "the archive was not restored"
    assert stage(repo, ARCH, 0) == ARCH_BASE


def test_conflicted_archive_defers_the_doc_without_a_roll(tmp_path, monkeypatch):
    """Design step 1: the doc's archive is conflicted and was not auto-resolved, so no roll may run
    over it. The doc defers, and the archive stays deferred as the resolve loop left it."""
    rolled = []
    monkeypatch.setattr(doc_rollover, "roll_to_cap", lambda r, p: rolled.append(p))
    repo = conflicted_archive_repo(tmp_path)
    assert unmerged(repo) == {ARCH}, unmerged(repo)         # the doc was resolved and staged
    rep = report(auto=[LIVE], conflicted=[LIVE, ARCH], deferred=[ARCH])
    assert call(rep, repo) == ""
    assert rolled == [] and rep.auto_resolved == [], rep.to_json()
    assert rep.deferred == [ARCH, LIVE], rep.to_json()
    assert unmerged(repo) == {LIVE, ARCH}
    assert stage(repo, LIVE, 2) == OURS_DOC and stage(repo, LIVE, 3) == THEIRS_DOC


# --- out of scope: today's outcome, nothing changes --------------------------------------------

@pytest.mark.parametrize("ours,theirs", [
    pytest.param(doc([100, 101, 102, 1], size=4000), doc([200, 201, 202, 1], size=4000),
                 id="both-sides-over-the-cap"),
    pytest.param(doc([300, 301, 302, 1], size=4000), doc([1], size=100), id="one-side-over-the-cap"),
])
def test_a_side_already_over_the_cap_is_left_staged(tmp_path, ours, theirs, monkeypatch):
    """Behavior 11's out-of-scope arms: a doc already over the hard cap on both sides, or on one
    side, is not the merge's doing. No roll runs and the doc keeps today's staged outcome."""
    rolled = []
    monkeypatch.setattr(doc_rollover, "roll_to_cap", lambda r, p: rolled.append(p))
    repo = merge_repo(tmp_path, ours=ours, theirs=theirs, merged=doc([100, 101, 200, 201, 1], 4000))
    before = pair(repo)
    assert len(before[0]) > HARD, len(before[0])
    rep = report(auto=[LIVE])
    assert call(rep, repo) == ""
    assert rolled == [] and pair(repo) == before
    assert rep.auto_resolved == [LIVE] and rep.deferred == [], rep.to_json()
    assert "hard-cap-rollover" not in outcome_of(rep, LIVE)["resolved_classes"], rep.to_json()
    assert stage(repo, LIVE, 0) is not None and unmerged(repo) == set()


def test_an_unreadable_side_is_out_of_scope(tmp_path, monkeypatch):
    """With no open merge `MERGE_HEAD` cannot be read, which is a git failure and not an absent
    path: the doc is out of scope, so nothing rolls and nothing changes."""
    rolled = []
    monkeypatch.setattr(doc_rollover, "roll_to_cap", lambda r, p: rolled.append(p))
    repo = merge_repo(tmp_path)
    git(repo, "merge", "--abort")
    write(repo, LIVE, MERGED_DOC)
    before = pair(repo)
    rep = report(auto=[LIVE])
    assert call(rep, repo) == ""
    assert rolled == [] and pair(repo) == before
    assert rep.auto_resolved == [LIVE] and rep.deferred == [], rep.to_json()


def test_a_roll_that_moves_nothing_leaves_the_doc_staged_and_identical(tmp_path):
    """Behavior 11's empty-History arm (the architecture doc's shape): a roll cannot help, so the doc
    stays staged and byte-identical. Deferring it would only add a stall."""
    repo = merge_repo(tmp_path, ours=HEAD, theirs=HEAD, merged=HEAD + "y" * (HARD + 500) + "\n")
    before = pair(repo)
    assert len(before[0]) > HARD, len(before[0])
    rep = report(auto=[LIVE])
    assert call(rep, repo) == ""
    assert pair(repo) == before, "a file changed"
    assert stage(repo, LIVE, 0) is not None and unmerged(repo) == set()
    assert rep.auto_resolved == [LIVE] and rep.deferred == [], rep.to_json()
    assert "hard-cap-rollover" not in outcome_of(rep, LIVE)["resolved_classes"], rep.to_json()
