"""basesync-docs-only-carry C1/C2: a merge is judged against git's own clean merge of its parents.

`merge_carry.merge_link` computes the clean merge tree (`git merge-tree --write-tree P1 P2`) and
accepts the merge commit only when its tree deviates from that tree on living-doc `.md` paths alone,
and every conflicted path is a living-doc `.md` too. So a whole code file kept from ONE side (`-s ours`,
`checkout --ours`/`--theirs`) is never neutral, whichever side's change it drops, a clean merge is
neutral, a hand-resolved living-doc conflict is neutral, a `merge-tree` failure is not neutral, and
lines are counted over the hand-resolved paths only (a binary file that came in unchanged is free).
Oracle: example-based (skills/_shared/test-fragility.md section 3); each case is one concrete history
built in a throwaway git repo scrubbed of `GIT_*`.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import merge_carry  # noqa: E402
import proof_neutral_carry as pnc  # noqa: E402

GUIDE = "three-pillars-docs/guide.md"
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


def commit(repo, files, msg="c"):
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def on_main(repo, files):
    git(repo, "checkout", "-q", "main")
    sha = commit(repo, files, "main")
    git(repo, "checkout", "-q", "tp/demo")
    return sha


def merge(repo, resolved=None, strategy=()):
    """Merge `main` into HEAD; `resolved` files are written over whatever the merge left."""
    git(repo, "merge", "--no-ff", "--no-commit", *strategy, "main", check=False)
    for rel, content in (resolved or {}).items():
        (repo / rel).write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", "sync")
    return git(repo, "rev-parse", "HEAD")


def src(a=1, c=1, e=1):
    return f"a = {a}\nb = 1\nc = {c}\nd = 1\ne = {e}\n"


def strip(repo, head, **kw):
    kw.setdefault("base_ref", "main")
    return pnc.strip_proof_neutral_commits(repo, head, **kw)


def real_git(repo):
    def _run(args):
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        return (r.returncode, r.stdout, r.stderr)
    return _run


def parents_of(repo, sha):
    return git(repo, "rev-list", "--parents", "-n1", sha).split()[1:]


@pytest.fixture
def repo(tmp_path):
    """main: root. tp/demo: B (a branch `.py` plus a guide edit, so B is never neutral)."""
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, {GUIDE: "a\nb\nc\nd\ne\n", "src.py": src()}, "root")
    git(tmp_path, "checkout", "-q", "-b", "tp/demo")
    b = commit(tmp_path, {"branch.py": "b = 1\n"}, "B")
    return tmp_path, b


def stops_at_merge(res, m):
    assert (res.anchor, res.links, res.neutral_links, res.lines) == (m, 0, 0, 0), res
    assert "merge commit" in res.reason


# ---- C1: a whole code file kept from one side is not neutral ---------------------------------


def test_s_ours_dropping_a_base_py_change_is_not_neutral(repo):
    r, b = repo
    on_main(r, {"src.py": src(e=9)})  # the reviewed base change `-s ours` throws away
    m = merge(r, strategy=("-s", "ours"))
    assert git(r, "diff", "--stat", "main", m, "--", "src.py")  # base's change really is reverted
    stops_at_merge(strip(r, m), m)


def test_keeping_the_branch_side_of_a_conflicted_py_is_not_neutral(repo):
    r, b = repo
    commit(r, {"src.py": src(a=2)})
    on_main(r, {"src.py": src(a=3)})
    m = merge(r, {"src.py": src(a=2)})  # `checkout --ours`: the base's edit is dropped
    stops_at_merge(strip(r, m), m)


def test_taking_the_base_side_whole_dropping_the_branch_py_change_is_not_neutral(repo):
    r, b = repo
    commit(r, {"src.py": src(a=2)})  # the branch's own reviewed change
    on_main(r, {"src.py": src(e=9)})  # git would merge both cleanly
    m = merge(r, {"src.py": src(e=9)})  # ... but this keeps base's whole file: the branch edit is gone
    stops_at_merge(strip(r, m), m)


def test_a_conflicted_py_committed_with_its_markers_is_not_neutral(repo):
    r, b = repo
    commit(r, {"src.py": src(a=2)})
    on_main(r, {"src.py": src(a=3)})
    git(r, "merge", "--no-ff", "--no-commit", "main", check=False)
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "sync with markers")  # the merge tree IS merge-tree's tree
    m = git(r, "rev-parse", "HEAD")
    ok, why, lines = merge_carry.merge_link(real_git(r), m, parents_of(r, m), base_ref="main")
    assert (ok, lines) == (False, 0) and "src.py conflicts" in why


# ---- the neutral shapes ----------------------------------------------------------------------


def test_a_clean_merge_with_no_conflicts_is_neutral_with_zero_lines(repo):
    r, b = repo
    on_main(r, {"lib.py": "z = 1\n", GUIDE: "a\nb\nc\nd\ne2\n"})
    m = merge(r)
    res = strip(r, m)
    assert (res.anchor, res.links, res.neutral_links, res.lines) == (b, 1, 1, 0), res


def test_a_doc_only_conflict_resolved_by_hand_is_still_neutral(repo):
    r, b = repo
    commit(r, {GUIDE: "a\nb-branch\nc\nd\ne\n"})
    on_main(r, {GUIDE: "a\nb-main\nc\nd\ne\n", "lib.py": "z = 1\n"})
    m = merge(r, {GUIDE: "a\nb-both\nc\nd\ne\n"})
    ok, why, lines = merge_carry.merge_link(real_git(r), m, parents_of(r, m), base_ref="main")
    assert (ok, why, lines) == (True, "", 2)
    res = strip(r, m)  # the merge (2 lines) and the branch's own doc commit (2 lines), down to B
    assert (res.anchor, res.links, res.neutral_links, res.lines) == (b, 2, 2, 4), res


def test_dropping_a_base_living_doc_change_with_s_ours_stays_neutral(repo):
    r, b = repo
    on_main(r, {GUIDE: "a\nb\nc\nd\ne2\n"})
    m = merge(r, strategy=("-s", "ours"))  # a living-doc deviation is within the accepted class
    res = strip(r, m)
    assert (res.anchor, res.links, res.neutral_links) == (b, 1, 1), res


def test_a_binary_file_that_came_unchanged_from_the_base_does_not_block_the_sync(repo):
    r, b = repo
    commit(r, {GUIDE: "a\nb-branch\nc\nd\ne\n"})
    on_main(r, {GUIDE: "a\nb-main\nc\nd\ne\n", "logo.bin": b"\x00\x01\x02" * 50})
    m = merge(r, {GUIDE: "a\nb-both\nc\nd\ne\n"})
    ok, why, lines = merge_carry.merge_link(real_git(r), m, parents_of(r, m), base_ref="main")
    assert (ok, why, lines) == (True, "", 2)


def test_a_hand_resolved_binary_path_is_not_neutral(repo):
    r, b = repo
    commit(r, {"logo.png": b"\x00\x01"})
    on_main(r, {"logo.png": b"\x00\x02"})
    git(r, "merge", "--no-ff", "--no-commit", "main", check=False)
    (r / "logo.png").write_bytes(b"\x00\x03")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "sync")
    m = git(r, "rev-parse", "HEAD")
    stops_at_merge(strip(r, m), m)


# ---- merge-tree failures fail closed --------------------------------------------------------


@pytest.mark.parametrize("answer", [(2, "", "fatal"), (129, "", "usage"), (0, "", ""),
                                    (0, "not-a-tree\0\0", ""), (1, "a" * 40 + "\0\0", ""),
                                    (0, "a" * 40 + "\0README.md\0\0", "")],
                         ids=["rc2", "rc129-old-git", "empty", "bad-tree", "conflict-without-paths",
                              "paths-without-conflict"])
def test_a_merge_tree_failure_or_odd_answer_is_not_neutral(repo, answer):
    r, b = repo
    on_main(r, {"lib.py": "z = 1\n"})
    m = merge(r)
    real = real_git(r)

    def flaky(args):
        return answer if args[0] == "merge-tree" else real(args)

    parents = parents_of(r, m)
    assert merge_carry.merge_link(real, m, parents, base_ref="main") == (True, "", 0)
    ok, why, lines = merge_carry.merge_link(flaky, m, parents, base_ref="main")
    assert (ok, lines) == (False, 0) and why.startswith("merge commit")
