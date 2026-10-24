"""basesync-docs-only-carry B4, B5 and the caps: renumber commits, the opt-out, merge links in the caps.

B4 a single-parent `chore(ids)` commit that touches only `known_issues*.md` and the design's own
`decisions.md` is neutral. B5 `review.proof_neutral_carry: false` still turns the whole carry off,
merge links included. A merge is ONE link, its resolved lines count toward `MAX_LINES`, and
`MAX_LINKS` is 4 so sync + renumber + log flush fits. `merge_carry.merge_link` is total: a git
failure at any step is "not neutral". Oracle: example-based (skills/_shared/test-fragility.md
section 3), real throwaway git repos scrubbed of `GIT_*`.
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
import living_doc_carry  # noqa: E402
import merge_carry  # noqa: E402
import proof_neutral_carry as pnc  # noqa: E402
import proof_predicate  # noqa: E402
import review_proof  # noqa: E402
from deterministic_gate import GateVerdict  # noqa: E402

PR = "https://github.com/o/r/pull/1"
AUTHOR = "tp-loop-bot"
GUIDE = "three-pillars-docs/guide.md"
# split so rule_ledger_extract.pin_tests_for does not take this file for a pin test of that doc
ISSUES = "three-pillars-docs/known_" "issues.md"
ISSUES_LOW = "three-pillars-docs/known_issues_low_2.md"
OWN = "three-pillars-docs/tp-designs/demo"
ARCH = "three-pillars-docs/completed-tp-designs/demo"
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


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


def real_git(repo):
    def _run(args):
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        return (r.returncode, r.stdout, r.stderr)
    return _run


def commit(repo, files, msg="c"):
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def sync(repo, branch_text=None, main_text=None, resolved=None):
    """Edit the guide on both sides (a conflict when both are given), merge main, return the merge."""
    if branch_text is not None:
        commit(repo, {GUIDE: branch_text, "branch.py": "b = 1\n"})
    if main_text is not None:
        git(repo, "checkout", "-q", "main")
        commit(repo, {GUIDE: main_text})
        git(repo, "checkout", "-q", "tp/demo")
    git(repo, "merge", "--no-ff", "--no-commit", "main", check=False)
    for rel, text in (resolved or {}).items():
        (repo / rel).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "sync")
    return git(repo, "rev-parse", "HEAD")


def doc(repo, n):
    """A neutral one-line doc commit."""
    old = (repo / GUIDE).read_text(encoding="utf-8")
    return commit(repo, {GUIDE: old + f"more {n}\n"})


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, {GUIDE: "a\nb\nc\nd\ne\n", ISSUES: "i\n", f"{OWN}/decisions.md": "d\n"}, "root")
    git(tmp_path, "checkout", "-q", "-b", "tp/demo")
    config = json.dumps({"schema_version": 1, "review": {}})
    p = commit(tmp_path, {".three-pillars/config.json": config, "src.py": "x = 2\n"}, "P")
    return tmp_path, p


def strip(repo, head, **kw):
    kw.setdefault("base_ref", "main")
    return pnc.strip_proof_neutral_commits(repo, head, **kw)


# ---- B4: ID-renumber commits ---------------------------------------------------------------


def test_b4_a_chore_ids_commit_over_issues_and_the_design_decisions_is_neutral(repo):
    r, p = repo
    head = commit(r, {ISSUES: "i2\n", ISSUES_LOW: "L9\n", f"{OWN}/decisions.md": "d2\n"},
                  "chore(ids): renumber after base-sync")
    ok, why, lines = pnc.is_proof_neutral_commit(real_git(r), p, head)
    assert (ok, why) == (True, "")
    assert lines == 5
    res = strip(r, head, base_ref=None)
    assert (res.anchor, res.links, res.neutral_links, res.lines) == (p, 1, 1, 5)


def test_b4_the_design_dir_is_already_in_the_living_doc_class():
    for path in (f"{OWN}/decisions.md", f"{ARCH}/decisions.md", f"{OWN}/design.md"):
        assert living_doc_carry.is_living_doc_carry_path(path), path
    for path in (f"{OWN}/lock.json", f"{ARCH}/escape-ledger.ndjson", "three-pillars-docs/specs/x.md"):
        assert not living_doc_carry.is_living_doc_carry_path(path), path


def test_b4_a_chore_ids_commit_that_also_touches_a_manifest_is_not_neutral(repo):
    r, p = repo
    head = commit(r, {ISSUES: "i2\n", f"{OWN}/lock.json": "{}\n"}, "chore(ids): renumber")
    res = strip(r, head)
    assert (res.anchor, res.links) == (head, 0)
    assert "lock.json" in res.reason


# ---- caps ------------------------------------------------------------------------------------


def test_the_default_caps_are_four_links_and_two_hundred_lines():
    assert (pnc.MAX_LINKS, pnc.MAX_LINES) == (4, 200)


def test_a_merge_counts_as_one_link_beside_a_renumber_and_a_log_flush(repo):
    r, p = repo
    m = sync(r, "a\nb-branch\nc\nd\ne\n", "a\nb-main\nc\nd\ne\n", {GUIDE: "a\nb-both\nc\nd\ne\n"})
    branch = git(r, "rev-parse", f"{m}^1")
    commit(r, {ISSUES: "i2\n", f"{OWN}/decisions.md": "d2\n"}, "chore(ids): renumber")
    commit(r, {f"{ARCH}/design.md": "x\n", f"{ARCH}/decisions.md": "log\n"}, "archive")
    flush = commit(r, {f"{ARCH}/decisions.md": "log\nmore\n"}, "flush")  # a round-log link: no lines
    res = strip(r, flush)
    # flush (round-log) + archive + renumber + merge = the 4-link cap; lines 0 + 2 + 4 + 2
    assert (res.anchor, res.links, res.neutral_links, res.lines) == (branch, 4, 3, 8)


def test_a_fifth_link_stops_at_the_link_cap(repo):
    r, p = repo
    m = sync(r, "a\nb-branch\nc\nd\ne\n", "a\nb-main\nc\nd\ne\n", {GUIDE: "a\nb-both\nc\nd\ne\n"})
    shas = [doc(r, i) for i in range(4)]
    res = strip(r, shas[-1])
    assert (res.anchor, res.links, res.neutral_links) == (m, 4, 4)
    assert "cap of 4" in res.reason


def test_the_resolved_lines_of_a_merge_count_toward_the_line_cap(repo):
    r, p = repo
    m = sync(r, "a\nb-branch\nc\nd\ne\n", "a\nb-main\nc\nd\ne\n", {GUIDE: "a\nb-both\nc\nd\ne\n"})
    assert strip(r, m, max_lines=2).lines == 2
    over = strip(r, m, max_lines=1)
    assert (over.anchor, over.links, over.lines) == (m, 0, 0)
    assert "lines" in over.reason
    head = doc(r, 1)
    summed = strip(r, head, max_lines=2)  # the doc commit (1) fits; the merge (2) would make 3
    assert (summed.anchor, summed.links, summed.lines) == (m, 1, 1)
    assert "lines" in summed.reason


def test_the_resolved_lines_are_the_smaller_diff_against_either_parent(repo):
    r, p = repo
    m = sync(r, "a\nb\nc\nd\ne\nf1\nf2\nf3\nf4\n", "a\nb\nc\nd\ne-main\n",
             {GUIDE: "a\nb\nc\nd\ne-main\nf1\nf2\nf3\nf4\n"})
    assert strip(r, m).lines == 2  # vs the branch: 1 line changed (e -> e-main) = 2; vs main: 4 added


# ---- B5: the opt-out ---------------------------------------------------------------------------


def _runners(head_sha):
    meta = {"base": "base000", "head": head_sha, "files_changed": 3, "insertions": 5,
            "deletions": 1, "degraded": False, "reason": None}
    body = review_proof.format_proof_digest(meta, [("correctness", 0)])
    calls = []

    def comments(url):
        calls.append(url)
        return [{"author": AUTHOR, "body": body}]

    return {"comments_fn": comments, "self_login_fn": lambda: AUTHOR,
            "derive_base_ref_fn": lambda url: "main"}, calls


def _converged_repo(tmp_path, review):
    """A repo whose branch commit B (config committed in it) is the proof head; returns (root, B, M)."""
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, {GUIDE: "a\nb\nc\nd\ne\n"}, "root")
    git(tmp_path, "checkout", "-q", "-b", "tp/demo")
    config = json.dumps({"schema_version": 1, "review": review})
    b = commit(tmp_path, {GUIDE: "a\nb-branch\nc\nd\ne\n", "src.py": "x = 2\n",
                          ".three-pillars/config.json": config}, "B")
    m = sync(tmp_path, None, "a\nb-main\nc\nd\ne\n", {GUIDE: "a\nb-both\nc\nd\ne\n"})
    return tmp_path, b, m


def test_b5_the_default_carries_across_the_sync_merge(tmp_path):
    root, b, m = _converged_repo(tmp_path, {})
    runners, calls = _runners(b)
    res = carry_check.check(str(root), PR, m, runners=runners)
    assert (res["carried"], res["reason"]) == (True, carry_check.NEUTRAL_ON)


def test_b5_the_opt_out_turns_the_merge_carry_off_and_never_fetches_comments(tmp_path):
    root, b, m = _converged_repo(tmp_path, {"proof_neutral_carry": False})
    runners, calls = _runners(b)
    res = carry_check.check(str(root), PR, m, runners=runners)
    assert res == {"carried": False, "reason": carry_check.OFF_KEY, "detail": ""}
    assert calls == []


@pytest.mark.parametrize("review, verdict", [
    ({}, GateVerdict.PASS),
    ({"proof_neutral_carry": False}, GateVerdict.INDETERMINATE),
], ids=["default-on", "opt-out"])
def test_b5_the_gate_predicate_follows_the_opt_out(tmp_path, review, verdict):
    root, b, m = _converged_repo(tmp_path, review)
    runners, _ = _runners(b)
    res = proof_predicate.pred_review_proof_on_head(
        PR, m, comments_fn=runners["comments_fn"], config={"review": review},
        self_login_fn=runners["self_login_fn"], repo_root=root,
        derive_base_ref_fn=runners["derive_base_ref_fn"])
    assert res.verdict == verdict


# ---- merge_link is total -------------------------------------------------------------------------


def _merge_fixture(repo):
    r, p = repo
    m = sync(r, "a\nb-branch\nc\nd\ne\n", "a\nb-main\nc\nd\ne\n", {GUIDE: "a\nb-both\nc\nd\ne\n"})
    return r, m, git(r, "rev-list", "--parents", "-n1", m).split()[1:]


@pytest.mark.parametrize("failing", [("rev-parse",), ("rev-list", "--first-parent"),
                                     ("merge-tree",), ("diff-tree", "--raw"),
                                     ("diff-tree", "--numstat")])
def test_a_failing_git_step_makes_the_merge_not_neutral(repo, failing):
    r, m, parents = _merge_fixture(repo)
    real = real_git(r)

    def flaky(args):
        if all(tok in args for tok in failing):
            return (1, "", "boom")
        return real(args)

    assert merge_carry.merge_link(real, m, parents, base_ref="main") == (True, "", 2)
    ok, why, lines = merge_carry.merge_link(flaky, m, parents, base_ref="main")
    assert (ok, lines) == (False, 0)
    assert why.startswith("merge commit")


def test_a_raising_git_makes_the_merge_not_neutral_and_never_raises(repo):
    r, m, parents = _merge_fixture(repo)

    def boom(args):
        raise RuntimeError("git exploded")

    ok, why, lines = merge_carry.merge_link(boom, m, parents, base_ref="main")
    assert (ok, lines) == (False, 0) and why.startswith("merge commit")


@pytest.mark.parametrize("parents", [[], ["a" * 40], ["a" * 40, "b" * 40, "c" * 40], ["x", "y"]])
def test_the_wrong_parent_shape_is_not_neutral(repo, parents):
    r, m, _ = _merge_fixture(repo)
    ok, why, lines = merge_carry.merge_link(real_git(r), m, parents, base_ref="main")
    assert (ok, lines) == (False, 0) and why.startswith("merge commit")


def test_lazy_base_ref_asks_once_and_swallows_errors():
    calls = []

    def derive(url):
        calls.append(url)
        return "main"

    get = merge_carry.lazy_base_ref(PR, derive)
    assert (get(), get(), calls) == ("main", "main", [PR])

    def boom(url):
        raise RuntimeError("no gh")

    assert merge_carry.lazy_base_ref(PR, boom)() is None
