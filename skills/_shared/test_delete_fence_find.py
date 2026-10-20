"""`find` starts in fence mode (design delete-fence-own-tree 2.3).

`find` never removes its own start directory, so a start that normalises to `.`
is safe when the cwd is one of the agent's own roots — for `-delete` as well as
for `-exec`. Any other start (an explicit path, `..`, an absolute path) is still
checked against the roots, and a `.` start from a cwd outside every root stays
denied. Reviewer mode is unchanged. Tests only feed command strings; nothing is
executed.
"""
import pytest

from reviewer_delete_guard import classify


@pytest.fixture
def tree(tmp_path):
    root, out = tmp_path / "root", tmp_path / "out"
    (root / "build").mkdir(parents=True)
    out.mkdir()
    return str(root), str(out)


def _v(cmd, tree, cwd="<R>", mode="fence"):
    root, out = tree

    def sub(text):
        return text.replace("<R>", root).replace("<O>", out)

    return classify(sub(cmd), scratch=[root], cwd=sub(cwd), mode=mode)


AT_ROOT_ALLOWED = [
    "find . -name '*.pyc' -delete",
    "find -name '*.pyc' -delete",                    # no start path at all
    "find . -name __pycache__ -type d -exec rm -rf {} +",
    "find build -name x -delete",
    "find ./build -delete",
    "find . -name x -delete -o -name y -delete",
]
DENIED = [
    ("find .. -name x -delete", "<R>"),
    ("find /home/x -delete", "<R>"),
    ("find . -delete", "<O>"),
    ("find ../other -delete", "<R>"),
    ("find .. -delete", "<O>"),
    ("find . -name x -exec rm -rf {} +", "<O>"),
]


@pytest.mark.parametrize("cmd", AT_ROOT_ALLOWED)
def test_fence_find_at_root_allowed(cmd, tree):
    verdict = _v(cmd, tree)
    assert verdict.allowed, verdict.reason


@pytest.mark.parametrize("cmd,cwd", DENIED)
def test_fence_find_denied(cmd, cwd, tree):
    assert not _v(cmd, tree, cwd=cwd).allowed


def test_reviewer_mode_find_dot_at_root_still_denied(tree):
    assert not _v("find . -name x -delete", tree, mode="reviewer").allowed


def test_find_dot_denied_without_cwd(tree):
    root = tree[0]
    assert not classify("find . -delete", scratch=[root], cwd=None,
                        mode="fence").allowed
