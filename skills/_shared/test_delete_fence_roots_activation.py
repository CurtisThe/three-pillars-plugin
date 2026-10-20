"""Activation and run kind for the delete fence (design delete-fence-own-tree 1.6).

`fence_active(env, project_top, exists)`, `repo_info(git, cwd)` and
`run_kind(env, info)` are pure: the env dict and the git callable are injected,
so nothing here shells out except the fixture-repo test at the bottom. The
fixture (`fixtures/delete_fence_repo.py`) builds a real `git init` repo with two
linked `tp/<slug>` worktrees under `tmp_path`; no `rm` is ever run.
"""
import os
import sys

from delete_fence_roots import fence_active, repo_info, run_kind

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))
from delete_fence_repo import build  # noqa: E402

TP_MARKER = os.path.join("three-pillars-docs", "")
CONFIG_MARKER = ".three-pillars/config.json"


def _exists(*present):
    """An `exists` predicate over the paths in `present` (posix-relative)."""
    have = {p.rstrip("/") for p in present}

    def pred(path):
        return path.replace(os.sep, "/").rstrip("/") in have
    return pred


def test_design_run_env_activates():
    assert fence_active({"TP_DESIGN_RUN": "1"}, "/top", _exists()) is True


def test_docs_marker_activates():
    env = {}
    top = "/top"
    assert fence_active(env, top, _exists("/top/three-pillars-docs")) is True


def test_config_marker_activates():
    assert fence_active({}, "/top", _exists("/top/.three-pillars/config.json")) is True


def test_plain_repo_is_not_fenced():
    assert fence_active({}, "/top", _exists("/top/README.md")) is False


def test_off_switch_beats_the_design_run_env():
    env = {"TP_DESIGN_RUN": "1", "TP_DELETE_FENCE": "off"}
    assert fence_active(env, "/top", _exists("/top/three-pillars-docs")) is False


def test_off_switch_beats_the_marker():
    env = {"TP_DELETE_FENCE": "off"}
    assert fence_active(env, "/top", _exists("/top/three-pillars-docs")) is False


def test_off_switch_is_the_only_off_value():
    env = {"TP_DESIGN_RUN": "1", "TP_DELETE_FENCE": "0"}
    assert fence_active(env, "/top", _exists()) is True


def test_missing_env_keys_are_absent_not_keyerror():
    assert fence_active({}, "", _exists()) is False


class _FakeGit:
    """Records the calls made, returns one canned `rev-parse` block."""

    def __init__(self, out):
        self.out = out
        self.calls = []

    def __call__(self, args, cwd):
        self.calls.append((list(args), cwd))
        return self.out


REV_PARSE = ("/top\n/top/.git\n/top/.git\ntp/x\n")


def test_repo_info_makes_one_rev_parse_call():
    git = _FakeGit(REV_PARSE)
    info = repo_info(git, "/top/sub")
    assert len(git.calls) == 1
    args, cwd = git.calls[0]
    assert args == ["rev-parse", "--show-toplevel", "--git-dir",
                    "--git-common-dir", "--abbrev-ref", "HEAD"]
    assert cwd == "/top/sub"
    assert info == {"top": "/top", "git_dir": "/top/.git",
                    "common_dir": "/top/.git", "branch": "tp/x"}


def test_repo_info_of_a_linked_worktree_reports_different_dirs():
    git = _FakeGit("/top-wt/a\n/top/.git/worktrees/a\n/top/.git\ntp/a\n")
    info = repo_info(git, "/top-wt/a")
    assert info["git_dir"] != info["common_dir"]
    assert info["branch"] == "tp/a"


def test_run_kind_design_run_from_env():
    info = {"top": "/top", "git_dir": "/top/.git", "common_dir": "/top/.git",
            "branch": "master"}
    assert run_kind({"TP_DESIGN_RUN": "1"}, info) == "design-run"


def test_run_kind_linked_tp_worktree_is_a_design_run():
    info = {"top": "/repo-wt/a", "git_dir": "/repo/.git/worktrees/a",
            "common_dir": "/repo/.git", "branch": "tp/a"}
    assert run_kind({}, info) == "design-run"


def test_run_kind_linked_worktree_on_a_non_tp_branch_is_the_seat():
    info = {"top": "/repo-wt/a", "git_dir": "/repo/.git/worktrees/a",
            "common_dir": "/repo/.git", "branch": "master"}
    assert run_kind({}, info) == "seat"


def test_run_kind_main_checkout_on_a_tp_branch_is_the_seat():
    info = {"top": "/repo", "git_dir": "/repo/.git", "common_dir": "/repo/.git",
            "branch": "tp/a"}
    assert run_kind({}, info) == "seat"


def test_run_kind_detached_head_is_the_seat():
    info = {"top": "/repo-wt/a", "git_dir": "/repo/.git/worktrees/a",
            "common_dir": "/repo/.git", "branch": "HEAD"}
    assert run_kind({}, info) == "seat"


def test_run_kind_slug_must_be_non_empty():
    info = {"top": "/repo-wt/a", "git_dir": "/repo/.git/worktrees/a",
            "common_dir": "/repo/.git", "branch": "tp/"}
    assert run_kind({}, info) == "seat"


def test_fixture_repo_activates_the_fence(tmp_path):
    paths = build(tmp_path)
    assert os.path.isdir(os.path.join(paths["repo"], "three-pillars-docs"))
    assert fence_active({}, paths["repo"], os.path.exists) is True


def test_fixture_linked_worktree_is_a_design_run(tmp_path):
    paths = build(tmp_path)
    wt = paths["a"]
    assert os.path.realpath(wt) != os.path.realpath(paths["repo"])
    info = repo_info(_real_git, wt)
    assert run_kind({}, info) == "design-run"


def test_fixture_main_checkout_is_the_seat(tmp_path):
    paths = build(tmp_path)
    info = repo_info(_real_git, paths["repo"])
    assert info["git_dir"] == info["common_dir"]
    assert run_kind({}, info) == "seat"


def _real_git(args, cwd):
    import subprocess
    r = subprocess.run(["git", "-C", str(cwd), *[str(a) for a in args]],
                       capture_output=True, text=True, check=True)
    return r.stdout
