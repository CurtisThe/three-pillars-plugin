"""A `GIT_WORK_TREE=` / `GIT_DIR=` prefix is an unprovable tree in fence mode
(design delete-fence-own-tree 2.7).

`git clean` and `git worktree remove` act on the tree git resolves, and either
variable moves that tree away from the cwd the fence checked. Whatever value it
holds the tree is unprovable, so the fenced forms are refused; a dry run, other
environment names and a plain `git clean` in scratch keep their old verdicts.
Commands are only fed to the classifier; nothing is executed.
"""
import pytest

from reviewer_delete_guard import classify


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "root"
    (root / "sub" / "w").mkdir(parents=True)
    return str(root)


def _v(cmd, root, mode="fence"):
    return classify(cmd.replace("<R>", root), scratch=[root], cwd=root, mode=mode)


DENIED = [
    "GIT_WORK_TREE=/elsewhere git clean -fdx",
    "GIT_DIR=/elsewhere/.git git clean -fdx",
    "GIT_WORK_TREE=/elsewhere git worktree remove /elsewhere/w",
    "GIT_WORK_TREE=<R>/sub git clean -fdx",          # inside scratch, still unprovable
    "GIT_DIR=<R>/.git git clean -fdx",
    "GIT_DIR=<R>/.git git worktree remove <R>/sub/w",
    "GIT_WORK_TREE=<R> GIT_AUTHOR_NAME=x git clean -fdx",   # beside another name
    "GIT_AUTHOR_NAME=x GIT_DIR=/elsewhere/.git git clean -fdx",
    "env GIT_WORK_TREE=/elsewhere git clean -fdx",   # through a wrapper
    "cd sub && GIT_WORK_TREE=/elsewhere git clean -fdx",
    "bash -c 'GIT_WORK_TREE=/elsewhere git clean -fdx'",
    "find . -exec env GIT_DIR=/elsewhere/.git git clean -fdx ';'",
]
ALLOWED = [
    "git clean -fdx",
    "GIT_AUTHOR_NAME=x git clean -n",
    "GIT_AUTHOR_NAME=x git clean -fdx",
    "GIT_WORK_TREE=/elsewhere git clean -n",         # a dry run deletes nothing
    "GIT_DIR=/elsewhere/.git git status",
    "git log GIT_DIR=/elsewhere",                    # an argument, not an assignment
    "env -u GIT_DIR git clean -fdx",                 # unsetting it is not assigning it
    "git worktree remove <R>/sub/w",
]


@pytest.mark.parametrize("cmd", DENIED)
def test_fence_git_tree_env_denied(cmd, tree):
    assert not _v(cmd, tree).allowed


@pytest.mark.parametrize("cmd", ALLOWED)
def test_fence_git_tree_env_allowed(cmd, tree):
    verdict = _v(cmd, tree)
    assert verdict.allowed, verdict.reason


def test_fence_git_tree_env_reason_names_the_variable(tree):
    verdict = _v("GIT_WORK_TREE=/elsewhere git clean -fdx", tree)
    assert "GIT_WORK_TREE" in verdict.reason


def test_fence_git_tree_env_after_the_verb_is_data(tree):
    # `GIT_DIR=x` after the subcommand is an operand, so it cannot move the tree
    assert _v("git clean -n GIT_DIR=/elsewhere", tree).allowed
