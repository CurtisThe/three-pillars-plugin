"""Redirections do not turn off `cd` tracking in fence mode (design
delete-fence-own-tree 2.6).

`2>&1`, `&> /dev/null` and `>/dev/null` say where a segment's output goes, not
which directory a later segment runs in. So a literal `cd` before them is still
followed and a later relative delete resolves against the new cwd. A subshell
`(`…`)`, a pipeline or a background `&` still leaves the cwd unknown, as does a
cd the model cannot follow. Commands are only fed to the classifier; nothing is
executed.
"""
import pytest

from delete_fence_verbs import UNKNOWN_SEP, unknown_separator
from reviewer_delete_guard import classify


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "root"
    (root / "build").mkdir(parents=True)
    return str(root)


def _v(cmd, root, mode="fence"):
    return classify(cmd.replace("<R>", root), scratch=[root], cwd=root, mode=mode)


ALLOWED = [
    "cd build && rm -rf out 2>&1",              # `>&` is a redirection
    "cd build && rm -rf out &> /dev/null",      # `&>` is a redirection
    "cd build; rm -rf out >/dev/null 2>&1",     # both, after a `;`
    "cd build && rm -rf out 1>&2",              # an explicit fd
    "cd build && find . -delete 2>&1",          # and for find's start of `.`
    "cd build && git clean -fdx 2>&1",
]
DENIED = [
    "cd build & rm -rf out",                    # background: cwd unknown
    "(cd build) ; rm -rf out",                  # subshell
    "echo x | cd build ; rm -rf out",           # pipeline
    "cd .. && rm -rf x",                        # the parent, outside scratch
    "cd build && rm -rf out & wait",            # a lone `&` still separates
]


@pytest.mark.parametrize("cmd", ALLOWED)
def test_fence_redirect_cd_allowed(cmd, tree):
    verdict = _v(cmd, tree)
    assert verdict.allowed, verdict.reason


@pytest.mark.parametrize("cmd", DENIED)
def test_fence_redirect_cd_denied(cmd, tree):
    assert not _v(cmd, tree).allowed


@pytest.mark.parametrize("cmd", ALLOWED)
def test_reviewer_mode_redirect_cd_still_unknown(cmd, tree):
    assert not _v(cmd, tree, mode="reviewer").allowed


def test_redirect_operand_outside_scratch_still_denied(tree):
    # the redirection is not what is checked: the operand still is
    assert not _v("cd <R>/build && rm -rf /elsewhere 2>&1", tree).allowed


REDIRECT_ONLY = [
    "rm -rf out 2>&1",
    "rm -rf out >&2",
    "rm -rf out &> /dev/null",
    "rm -rf out &>> /dev/null",
    "rm -rf out </dev/null 2>&1",
    "echo 'a && b' && rm -rf out",   # quoted text is data, not a separator
]
SEPARATORS = [
    "cd build & rm -rf out",
    "(cd build) ; rm -rf out",
    "echo x | cd build",
    "a && b & c",
    "cd build && rm -rf out & wait",
]


@pytest.mark.parametrize("cmd", REDIRECT_ONLY)
def test_redirections_are_not_separators(cmd):
    assert not unknown_separator(cmd)


@pytest.mark.parametrize("cmd", SEPARATORS)
def test_separators_are_still_unknown(cmd):
    assert unknown_separator(cmd)


def test_unknown_sep_stays_importable():
    # kept for existing callers; the guard no longer decides with it
    assert UNKNOWN_SEP.search("a & b")
