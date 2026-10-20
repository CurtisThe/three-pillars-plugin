"""mode="fence" for reviewer_delete_guard (design delete-fence-own-tree 1.2).

Fence mode limits the destructive set to filesystem deletes: git branch/ref
forms are allowed, `git clean` and `git worktree remove` are fenced by the
tree they act on, and `mv` checks only its sources. The default mode stays
"reviewer". Tests only feed command strings; nothing is executed.
"""
import pytest

from reviewer_delete_guard import classify


@pytest.fixture
def tree(tmp_path):
    root, root2, out = tmp_path / "root", tmp_path / "root2", tmp_path / "out"
    for d in (root, root2, out, root / "sub"):
        d.mkdir()
    (out / "existing").write_text("")
    return str(root), str(root2), str(out)


def _v(cmd, tree, cwd="<R>", mode="fence", roots=("<R>",)):
    root, root2, out = tree

    def sub(text):
        return text.replace("<R2>", root2).replace("<R>", root).replace("<O>", out)

    return classify(sub(cmd), scratch=[sub(r) for r in roots],
                    cwd=sub(cwd) if cwd else None, mode=mode)


GIT_FORMS = [
    "git reset --hard", "git checkout main", "git restore .", "git stash",
    "git rm f", "git branch -D tp/x", "git push origin --delete tp/x",
    "git worktree prune",
]
ALLOWED = GIT_FORMS + [
    "git clean -n", "git clean -fdx", "git -C <R>/sub clean -fdx",
    "git worktree remove <R>/.tp-scratch/w", "git -C <R> worktree remove <R>/w",
    "git worktree remove w", "rm -rf build", "find build -delete",
    "find . -name '*.pyc' -exec rm {} +", "mv a b", "mv a <R>/b",
    "mv a /elsewhere", "mv a <O>/existing", "mv -t /elsewhere a b",
    "rsync -a a/ b/", "git --work-tree=<R>/sub clean -fd",
    "git -c core.x=1 -C sub clean -fd",
]
DENIED = [
    "git -C <O> clean -fd", "git -C <O>/sub clean -fdx",
    "git worktree remove <O>/w", "rm -rf <O>/x", "find <O> -delete",
    "rsync -a --delete a/ <O>/", "mv <O>/x <R>/y", "mv x /dev/null",
    "mv -t /dev/null x", "mv -t <R> <O>/x", "rm -rf $HOME/x", "rm -rf ~/x",
    "rm -rf $(pwd)/x", "git worktree remove $(pwd)/w",
    "git -C $HOME clean -fd", "git --work-tree=<O> clean -fd",
    "git --work-tree <O> clean -fd", "git worktree remove",
    "git worktree remove <R>", "git -C <R>/sub worktree remove <R>",
]


@pytest.mark.parametrize("cmd", ALLOWED)
def test_fence_allows(cmd, tree):
    verdict = _v(cmd, tree)
    assert verdict.allowed, verdict.reason


@pytest.mark.parametrize("cmd", DENIED)
def test_fence_denies(cmd, tree):
    assert not _v(cmd, tree).allowed


def test_clean_in_out_cwd_denied(tree):
    assert not _v("git clean -fdx", tree, cwd="<O>").allowed


def test_relative_rm_without_cwd_denied(tree):
    assert not _v("rm -rf x", tree, cwd=None).allowed


def test_clean_without_cwd_denied(tree):
    assert not _v("git clean -fdx", tree, cwd=None).allowed


def test_clean_dry_run_in_out_cwd_allowed(tree):
    assert _v("git clean -n", tree, cwd="<O>").allowed


def test_no_roots_clean_denied(tree):
    verdict = _v("git clean -fdx", tree, roots=())
    assert not verdict.allowed
    assert "no scratch known" in verdict.reason


def test_callable_roots_resolved_for_fence_git(tree):
    root = tree[0]
    ok = classify("git clean -fdx", scratch=lambda: [root], cwd=root, mode="fence")
    assert ok.allowed, ok.reason


def test_registered_worktree_is_a_root(tree):
    seat_roots = ("<R>", "<R2>")
    assert _v("git worktree remove <R2>", tree, roots=seat_roots).allowed
    assert _v("git worktree remove <R2>/sub", tree, roots=seat_roots).allowed


def test_never_the_checkout_cwd_is_in(tree):
    seat_roots = ("<R>", "<R2>")
    assert not _v("git worktree remove <R>", tree, roots=seat_roots).allowed
    assert not _v("git worktree remove <R>", tree, cwd="<R>/sub", roots=seat_roots).allowed
    assert not _v("git worktree remove <R2>", tree, cwd="<R2>", roots=seat_roots).allowed
    assert not _v("git worktree remove .", tree, roots=seat_roots).allowed


@pytest.mark.parametrize("cmd", GIT_FORMS)
def test_reviewer_mode_still_denies_git_forms(cmd, tree):
    assert not _v(cmd, tree, mode="reviewer").allowed


@pytest.mark.parametrize("cmd", GIT_FORMS + ["git clean -fdx", "git worktree remove <R>/w"])
def test_default_mode_is_reviewer(cmd, tree):
    root = tree[0]
    assert not classify(cmd.replace("<R>", root), scratch=[root], cwd=root).allowed


def test_reviewer_mv_still_checks_destination(tree):
    assert not _v("mv a /elsewhere", tree, mode="reviewer").allowed
    assert _v("mv a b", tree, mode="reviewer").allowed
