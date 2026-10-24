"""basesync-docs-only-carry B1-B3: a base-sync merge is a proof-neutral link in the carry walk.

A two-parent merge whose second parent is on the base branch's first-parent history is neutral iff
every path where the merge tree deviates from git's clean merge of its parents (the hand-resolved
paths) is a living-doc `.md`, and so is every conflicted path. A clean auto-merge is git's own
result. B1 neutral and `carry_check` exits 0, B2 a hand-resolved `.py` or skill `.md` is not neutral, B3 a second parent off the base's first-parent history is not.
Oracle: example-based (skills/_shared/test-fragility.md section 3); every case is one concrete
history built in a throwaway git repo (scrubbed of `GIT_*`), asserting the `NeutralStripResult`.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tp-pr-iterate" / "scripts"))
import carry_check  # noqa: E402
import proof_neutral_carry as pnc  # noqa: E402
import review_proof  # noqa: E402

PR = "https://github.com/o/r/pull/1"
AUTHOR = "tp-loop-bot"
GUIDE = "three-pillars-docs/guide.md"
SKILL = "skills/demo/SKILL.md"
ARCH = "three-pillars-docs/completed-tp-designs/demo"
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
CONFIG = json.dumps({"schema_version": 1, "review": {}})


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)
    for key, val in IDENT.items():
        monkeypatch.setenv(key, val)


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
                       capture_output=True, text=True, check=check)
    return r.stdout.strip()


def commit(repo, files, msg="c"):
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def code(repo, files):
    """A branch commit that also adds a `.py`, so it is never neutral and ends the walk."""
    return commit(repo, {**files, "branch.py": "b = 1\n"}, "branch")


def on(repo, branch, files, msg="c"):
    """Commit `files` on `branch`, then return to the PR branch `tp/demo`."""
    git(repo, "checkout", "-q", branch)
    sha = commit(repo, files, msg)
    git(repo, "checkout", "-q", "tp/demo")
    return sha


def merge(repo, ref, resolved=None, *others):
    """`git merge --no-ff` of `ref` (+ `others`) into HEAD; `resolved` files are written over any conflict."""
    git(repo, "merge", "--no-ff", "--no-commit", ref, *others, check=False)
    for rel, text in (resolved or {}).items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "sync")
    return git(repo, "rev-parse", "HEAD")


def src(a=1, c=1, e=1):
    """`src.py`: five lines, so edits on lines 1, 3 and 5 never touch adjacent lines."""
    return f"a = {a}\nb = 1\nc = {c}\nd = 1\ne = {e}\n"


def strip(repo, head, **kw):
    kw.setdefault("base_ref", "main")
    return pnc.strip_proof_neutral_commits(repo, head, **kw)


@pytest.fixture
def repo(tmp_path):
    """main: root. tp/demo: P (config, archived design, `src.py` changed, so P is never neutral)."""
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, {GUIDE: "a\nb\nc\nd\ne\n", "src.py": src(), SKILL: "s1\ns2\n"}, "root")
    git(tmp_path, "checkout", "-q", "-b", "tp/demo")
    p = commit(tmp_path, {f"{ARCH}/design.md": "d\n", f"{ARCH}/decisions.md": "a\n",
                          ".three-pillars/config.json": CONFIG, "src.py": src(a=2)}, "P")
    return tmp_path, p


def assert_neutral(res, anchor, lines):
    assert (res.anchor, res.links, res.neutral_links, res.lines) == (anchor, 1, 1, lines), res


def assert_stops_at(res, merge_sha):
    assert (res.anchor, res.links, res.neutral_links, res.lines) == (merge_sha, 0, 0, 0), res
    assert "merge commit" in res.reason


# ---- B1: living-doc-only merges are neutral ----------------------------------------------


def test_b1_a_clean_auto_merge_of_a_living_doc_is_neutral(repo):
    r, p = repo
    b = code(r, {GUIDE: "a2\nb\nc\nd\ne\n"})
    on(r, "main", {GUIDE: "a\nb\nc\nd\ne2\n", "other.py": "y = 1\n"}, "main edits line 5")
    m = merge(r, "main")
    assert_neutral(strip(r, m), b, 0)  # git merges it cleanly: nothing was hand-resolved


def test_b1_a_hand_resolved_living_doc_conflict_is_neutral(repo):
    r, p = repo
    b = code(r, {GUIDE: "a\nb-branch\nc\nd\ne\n"})
    on(r, "main", {GUIDE: "a\nb-main\nc\nd\ne\n"})
    m = merge(r, "main", {GUIDE: "a\nb-both\nc\nd\ne\n"})
    assert_neutral(strip(r, m), b, 2)


def test_b1_a_resolved_design_dir_md_is_neutral(repo):
    r, p = repo
    own = "three-pillars-docs/tp-designs/demo/decisions.md"
    b = code(r, {own: "one\ntwo\n"})
    on(r, "main", {own: "one\nthree\n"})
    m = merge(r, "main", {own: "one\ntwo+three\n"})
    assert_neutral(strip(r, m), b, 2)


def test_b1_a_merge_that_only_brings_base_history_is_neutral_with_zero_lines(repo):
    r, p = repo
    on(r, "main", {"lib.py": "z = 1\n", SKILL: "s1\nS2\n"})
    m = merge(r, "main")  # the merge tree is the clean merge: all of it came from the reviewed base
    assert_neutral(strip(r, m), p, 0)


def test_b1_carry_check_exits_zero_against_the_converged_head(repo, monkeypatch):
    r, p = repo
    b = code(r, {GUIDE: "a\nb-branch\nc\nd\ne\n"})
    on(r, "main", {GUIDE: "a\nb-main\nc\nd\ne\n", "other.py": "y = 1\n"})
    m = merge(r, "main", {GUIDE: "a\nb-both\nc\nd\ne\n"})
    meta = {"base": "base000", "head": b, "files_changed": 3, "insertions": 5,
            "deletions": 1, "degraded": False, "reason": None}
    body = review_proof.format_proof_digest(meta, [("correctness", 0)])
    runners = {"comments_fn": lambda url: [{"author": AUTHOR, "body": body}],
               "self_login_fn": lambda: AUTHOR, "derive_base_ref_fn": lambda url: "main"}
    res = carry_check.check(str(r), PR, m, runners=runners)
    assert res["carried"] is True
    assert res["reason"] == carry_check.NEUTRAL_ON
    assert f"(anchor {b[:7]})" in res["detail"]
    real_check = carry_check.check
    monkeypatch.setattr(carry_check, "check",
                        lambda repo_root, url, head: real_check(repo_root, url, head, runners=runners))
    assert carry_check.main(["--repo", str(r), "--pr-url", PR, "--head", m]) == 0


# ---- B2: a hand-resolved code or skill-text path is not neutral --------------------------


def test_b2_a_hand_resolved_py_is_not_neutral(repo):
    r, p = repo
    commit(r, {"src.py": src(a=3)})
    on(r, "main", {"src.py": src(a=4)})
    m = merge(r, "main", {"src.py": src(a=5)})
    assert_stops_at(strip(r, m), m)


def test_b2_a_hand_resolved_skill_md_is_not_neutral(repo):
    r, p = repo
    commit(r, {SKILL: "s1\nbranch\n"})
    on(r, "main", {SKILL: "s1\nmain\n"})
    m = merge(r, "main", {SKILL: "s1\nboth\n"})
    assert_stops_at(strip(r, m), m)


def test_b2_one_code_path_among_living_docs_makes_the_merge_not_neutral(repo):
    r, p = repo
    commit(r, {GUIDE: "a\nb-branch\nc\nd\ne\n", "src.py": src(a=3)})
    on(r, "main", {GUIDE: "a\nb-main\nc\nd\ne\n", "src.py": src(a=4)})
    m = merge(r, "main", {GUIDE: "a\nb-both\nc\nd\ne\n", "src.py": src(a=5)})
    assert_stops_at(strip(r, m), m)


def test_b2_a_cleanly_auto_merged_py_is_neutral_because_nothing_was_hand_resolved(repo):
    r, p = repo
    b = commit(r, {"src.py": src(a=2, e=9)})
    on(r, "main", {"src.py": src(c=9)})
    m = merge(r, "main")  # the merge tree is exactly git's own clean merge of two reviewed sides
    assert_neutral(strip(r, m), b, 0)


def test_b2_a_hand_resolved_non_markdown_path_under_the_docs_root_is_not_neutral(repo):
    r, p = repo
    manifest = "three-pillars-docs/tp-designs/demo/lock.json"
    commit(r, {manifest: '{"a": 1}\n'})
    on(r, "main", {manifest: '{"a": 2}\n'})
    m = merge(r, "main", {manifest: '{"a": 3}\n'})
    assert_stops_at(strip(r, m), m)


# ---- B3: the second parent must sit on the base's first-parent history -------------------


def test_b3_a_second_parent_off_the_base_branch_is_not_neutral(repo):
    r, p = repo
    git(r, "branch", "feature", "main")
    on(r, "feature", {"extra.md": "extra\n"})
    m = merge(r, "feature")
    assert_stops_at(strip(r, m), m)


def test_b3_a_second_parent_only_reachable_through_a_base_merge_is_not_neutral(repo):
    r, p = repo
    git(r, "branch", "side", "main")
    side = on(r, "side", {"side.md": "side\n"})
    git(r, "checkout", "-q", "main")
    git(r, "merge", "--no-ff", "-q", "-m", "merge side", "side")
    git(r, "checkout", "-q", "tp/demo")
    git(r, "merge-base", "--is-ancestor", side, "main")  # an ancestor of main (raises if not)
    m = merge(r, side)  # ... but not on main's first-parent chain
    assert_stops_at(strip(r, m), m)


def test_b3_a_three_parent_merge_is_not_neutral(repo):
    r, p = repo
    git(r, "branch", "other", "main")
    on(r, "main", {"main.md": "main\n"})
    on(r, "other", {"other.md": "other\n"})
    m = merge(r, "main", None, "other")
    assert len(git(r, "rev-list", "--parents", "-n1", m).split()) == 4
    assert_stops_at(strip(r, m), m)


@pytest.mark.parametrize("base_ref", [None, "", "no-such-branch", "-main", lambda: None, lambda: "no-such"],
                         ids=["none", "empty", "unknown", "dash", "callable-none", "callable-unknown"])
def test_a_merge_stays_non_neutral_without_a_resolvable_base_ref(repo, base_ref):
    r, p = repo
    on(r, "main", {"lib.py": "z = 1\n"})
    m = merge(r, "main")
    assert_stops_at(strip(r, m, base_ref=base_ref), m)


def test_a_callable_base_ref_is_resolved_lazily_and_only_for_a_merge(repo):
    r, p = repo
    calls = []

    def lazy():
        calls.append(1)
        return "main"

    doc = commit(r, {GUIDE: "a\nb\nc\nd\ne\nf\n"})
    assert strip(r, doc, base_ref=lazy).anchor == p and calls == []
    on(r, "main", {"lib.py": "z = 1\n"})
    res = strip(r, merge(r, "main"), base_ref=lazy)
    assert (res.anchor, res.neutral_links, res.lines) == (p, 2, 1)  # the merge, then the doc commit
    assert calls == [1]


def test_the_remote_tracking_base_is_preferred_over_a_local_branch(repo):
    r, p = repo
    root = git(r, "rev-list", "--max-parents=0", "HEAD")
    tip = on(r, "main", {"lib.py": "z = 1\n"})
    m = merge(r, "main")
    git(r, "update-ref", "refs/remotes/origin/main", root)  # stale: does not hold `tip`
    assert_stops_at(strip(r, m), m)
    git(r, "update-ref", "refs/remotes/origin/main", tip)
    assert_neutral(strip(r, m), p, 0)
