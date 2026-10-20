"""cd tracking in fence mode (design delete-fence-own-tree 1.3).

A literal `cd <path>` updates the classifier's cwd, so a later relative delete
resolves against the new directory. Any cd the model cannot follow (a flag,
`-`, `~`, an expansion, a bare `cd`, `pushd`/`popd`, or a separator other than
`;`, `&&` or a newline) leaves the cwd unknown, so the delete is denied.
Reviewer mode is unchanged: every cd makes the cwd unknown. Commands are only
fed to the classifier; nothing is executed.
"""
import pytest

from delete_fence_verbs import cd_target
from reviewer_delete_guard import classify


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    out = tmp_path / "out"
    out.mkdir()
    return str(root), str(out)


def _v(cmd, tree, mode="fence"):
    root, _out = tree
    return classify(cmd.replace("<R>", root), scratch=[root], cwd=root, mode=mode)


ALLOWED = [
    "cd build && rm -rf out",              # cwd <R>/build, out inside it
    "cd build && rm -rf ../x",             # ../x -> <R>/x, strictly inside
    "cd sub; cd .. && rm -rf x",           # back to <R>
    "cd . && rm -rf x",
    "cd <R>/sub/deep && rm -rf y",
    "cd <R>/a && git clean -fdx",
    "cd /elsewhere && rm -rf <R>/x",       # absolute operand ignores cwd
    "cd build\nrm -rf out",
]
DENIED = [
    "cd .. && rm -rf x",                   # cwd becomes the parent, outside
    "cd ../.. && rm -rf x",
    "cd /elsewhere && rm -rf x",
    "cd - && rm -rf out",
    "cd $D && rm -rf out",
    "cd ${D} && rm -rf out",
    "cd ~ && rm -rf out",
    "cd && rm -rf out",
    "cd -L build && rm -rf out",
    "pushd build && rm -rf out",
    "popd && rm -rf out",
    "(cd build) ; rm -rf out",             # subshell: outer cwd unchanged, unknown
    "cd build || rm -rf out",
    "cd build & rm -rf out",
    "cd build | cat && rm -rf out",
    "cd build && cd - && rm -rf out",
]


@pytest.mark.parametrize("cmd", ALLOWED)
def test_fence_cd_allowed(cmd, tree):
    verdict = _v(cmd, tree)
    assert verdict.allowed, verdict.reason


@pytest.mark.parametrize("cmd", DENIED)
def test_fence_cd_denied(cmd, tree):
    assert not _v(cmd, tree).allowed


REVIEWER_DENIED = [
    "cd build && rm -rf out",
    "cd build && rm -rf ../x",
    "cd sub; cd .. && rm -rf x",
    "cd . && rm -rf x",
    "cd <R>/sub/deep && rm -rf y",
    "cd <R>/a && git clean -fdx",
    "cd build\nrm -rf out",
]


@pytest.mark.parametrize("cmd", REVIEWER_DENIED)
def test_reviewer_mode_cd_still_unknown(cmd, tree):
    assert not _v(cmd, tree, mode="reviewer").allowed


def test_cd_outside_then_absolute_inside_allowed(tree):
    assert _v("cd .. && rm -rf <R>/x", tree).allowed


def test_cd_outside_then_relative_denied(tree):
    assert not _v("cd .. && rm -rf root", tree).allowed


def test_cd_then_git_worktree_remove_target(tree):
    root, _out = tree
    assert not _v("cd sub && git worktree remove <R>", tree).allowed


def test_cd_into_scratch_keeps_root_itself_denied(tree):
    assert not _v("cd sub && rm -rf <R>", tree).allowed


def test_cd_target_relative(tree):
    root, _out = tree
    assert cd_target(["build"], root) == root + "/build"
    assert cd_target(["../x"], root + "/build") == root + "/x"
    assert cd_target(["sub", "deep"], None) is None


def test_cd_target_dot_keeps_cwd(tree):
    root, _out = tree
    assert cd_target(["."], root + "/sub") == root + "/sub"


def test_cd_target_absolute(tree):
    root, _out = tree
    assert cd_target(["/elsewhere/build"], root) == "/elsewhere/build"
    assert cd_target([root + "/sub"], "/elsewhere") == root + "/sub"


def test_cd_target_unknown_forms(tree):
    root, _out = tree
    for args in ([], ["-"], ["~"], ["~/x"], ["$D"], ["a$b"], ["-L", "build"],
                 ["--"], ["a", "b"], ["`pwd`"]):
        assert cd_target(args, root) is None, args
