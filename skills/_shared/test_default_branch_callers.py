"""test_default_branch_callers.py — default_branch_names + its callers.

design: consumer-repo-parity (Task 4.5, spec part B §M4)

`default_branch.default_branch_names(repo)` is the fail-safe helper — the
fixed `("main", "master")` tuple plus `repo`'s resolved default-branch name,
deduplicated. This module pins that helper AND the four call sites that route
through it: `diff_balloon_guard`'s CLI `--base-ref` default, `gate_roster`'s
hermetic balloon call, and both worktree guards' default-branch membership
checks (`worktree_write_guard.should_block`, `worktree_isolation_guard`'s
`_is_default_branch_root` / `assert_own_worktree`).

Fixtures are real `tmp_path` repos whose `refs/remotes/origin/HEAD` points at
`trunk` — built directly (no bare remote needed): a local `trunk` branch, a
seed commit, then `refs/remotes/origin/trunk` and `refs/remotes/origin/HEAD`
created by hand. House rules honoured here: GIT_* env scrubbed (plus isolated
HOME) both for the fixture builds and — via an autouse fixture — for the
in-process git calls the modules under test make (mirrors
test_default_branch_ref.py). No test pins prose wording. Stdlib + pytest only.

Run with: python3 -m pytest skills/_shared/test_default_branch_callers.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import default_branch as db  # noqa: E402
import diff_balloon_guard  # noqa: E402
from worktree_write_guard import should_block  # noqa: E402
from worktree_isolation_guard import _is_default_branch_root, assert_own_worktree  # noqa: E402

CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
CLEAN_ENV["GIT_AUTHOR_NAME"] = "fixture"
CLEAN_ENV["GIT_AUTHOR_EMAIL"] = "fixture@test"
CLEAN_ENV["GIT_COMMITTER_NAME"] = "fixture"
CLEAN_ENV["GIT_COMMITTER_EMAIL"] = "fixture@test"


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Scrub inherited GIT_* vars and isolate HOME (see test_default_branch_ref.py)."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, env=CLEAN_ENV,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)


def _make_trunk_repo(path: Path) -> Path:
    """A real repo whose `origin/HEAD` points at `trunk` — built by hand, no
    bare remote required (see Task 4.5's dispatcher notes)."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "trunk")
    (path / "README.md").write_text("# fixture\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "seed")
    _git(path, "update-ref", "refs/remotes/origin/trunk", "HEAD")
    _git(path, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
    return path


# ---------------------------------------------------------------------------
# default_branch.default_branch_names — the shared helper
# ---------------------------------------------------------------------------


def test_names_include_resolved_trunk(tmp_path):
    repo = _make_trunk_repo(tmp_path / "repo")
    assert db.default_branch_names(str(repo)) == ("main", "master", "trunk")


def test_names_dedupe_when_resolved_is_already_fixed(tmp_path):
    """origin/HEAD -> main: no duplicate 'main' appended."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    assert db.default_branch_names(str(repo)) == ("main", "master")


def test_names_fallback_on_resolver_error(monkeypatch):
    def boom(*args, **kwargs):
        raise db.DefaultBranchError("synthetic")
    monkeypatch.setattr(db, "resolve_default_branch", boom)
    assert db.default_branch_names("anything") == ("main", "master")


def test_names_never_raises_on_bad_repo_path(tmp_path):
    """A nonexistent repo path (OSError from subprocess) never propagates."""
    ghost = tmp_path / "does-not-exist"
    assert db.default_branch_names(str(ghost)) == ("main", "master")


# ---------------------------------------------------------------------------
# diff_balloon_guard — CLI --base-ref default
# ---------------------------------------------------------------------------


def test_balloon_cli_default_base_resolves_to_trunk(tmp_path):
    """No --base-ref: the trunk repo's own HEAD is a clean fork-point of itself
    (zero diff) -> PASS (exit 0). Falling back to 'master' would error (no
    such branch) -> exit 2, so PASS here proves the resolved 'trunk' was used.
    """
    repo = _make_trunk_repo(tmp_path / "repo")
    rc = diff_balloon_guard.main(["--repo", str(repo)])
    assert rc == 0


def test_balloon_cli_resolver_error_falls_back_to_master(tmp_path, monkeypatch):
    """Resolver raises -> CLI falls back to 'master', which doesn't exist in
    this trunk-only repo -> git errors -> INDETERMINATE (exit 2)."""
    repo = _make_trunk_repo(tmp_path / "repo")

    def boom(*args, **kwargs):
        raise diff_balloon_guard.DefaultBranchError("synthetic")
    monkeypatch.setattr(diff_balloon_guard, "resolve_default_branch", boom)

    rc = diff_balloon_guard.main(["--repo", str(repo)])
    assert rc == 2


# ---------------------------------------------------------------------------
# gate_roster — the hermetic balloon call's base_ref
# ---------------------------------------------------------------------------


def _hermetic_runners(**extra):
    base = {
        "pr_state_fn": lambda url: {
            "mergeable": "MERGEABLE", "headRefOid": "deadbeef",
            "statusCheckRollup": [],
        },
        "threads_fn": lambda url: [],
        "labels_fn": lambda url: [],
        "timeline_fn": lambda url: [],
        "head_fn": lambda url: {},
        "commits_fn": lambda url: [],
        "self_login_fn": lambda: "bot",
    }
    base.update(extra)
    return base


_HERMETIC_CONFIG = {
    "review": {"expects_copilot": False, "require_human_approval": False},
    "ci": {"expects_github_checks": False},
}


def _captured_balloon_base_ref(monkeypatch) -> str:
    from deterministic_gate import evaluate_gate, GateVerdict, PredicateResult

    captured = {}

    def fake_pred(**kwargs):
        captured.update(kwargs)
        return PredicateResult(name="diff_not_ballooned", verdict=GateVerdict.PASS, detail="ok")

    # gate_roster's balloon call does a function-local `import diff_balloon_guard`
    # -> the singleton module object we already imported above, so patching it
    # here is visible there too.
    monkeypatch.setattr(diff_balloon_guard, "pred_diff_not_ballooned", fake_pred)
    evaluate_gate(
        "https://github.com/o/r/pull/1",
        runners=_hermetic_runners(balloon_sizes=(1, 10)),
        config=_HERMETIC_CONFIG,
    )
    return captured.get("base_ref")


def test_gate_roster_hermetic_balloon_base_ref_trunk(tmp_path, monkeypatch):
    repo = _make_trunk_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    assert _captured_balloon_base_ref(monkeypatch) == "trunk"


def test_gate_roster_hermetic_balloon_base_ref_master_fallback(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise db.DefaultBranchError("synthetic")
    monkeypatch.setattr(db, "resolve_default_branch", boom)
    assert _captured_balloon_base_ref(monkeypatch) == "master"


# ---------------------------------------------------------------------------
# worktree_write_guard.should_block — default-branch membership via repo
# ---------------------------------------------------------------------------

_PORCELAIN_WITH_TP_X = """\
worktree /home/user/repo
HEAD abc123
branch refs/heads/trunk

worktree /home/user/repo-wt/x
HEAD def456
branch refs/heads/tp/x

"""


def test_write_guard_refuses_design_file_on_trunk_seat(tmp_path):
    repo = _make_trunk_repo(tmp_path / "repo")
    blocked, msg = should_block(
        branch="trunk",
        staged_paths=["three-pillars-docs/tp-designs/x/plan.md"],
        worktree_porcelain=_PORCELAIN_WITH_TP_X,
        repo=str(repo),
    )
    assert blocked is True
    assert msg


def test_write_guard_resolver_error_keeps_fixed_tuple(monkeypatch):
    def boom(*args, **kwargs):
        raise db.DefaultBranchError("synthetic")
    monkeypatch.setattr(db, "resolve_default_branch", boom)

    # 'trunk' is not in the fixed fallback tuple -> not blocked.
    blocked, _ = should_block(
        branch="trunk",
        staged_paths=["three-pillars-docs/tp-designs/x/plan.md"],
        worktree_porcelain=_PORCELAIN_WITH_TP_X,
        repo="anything",
    )
    assert blocked is False

    # 'master' remains in the fixed fallback tuple -> still blocked.
    blocked, _ = should_block(
        branch="master",
        staged_paths=["three-pillars-docs/tp-designs/x/plan.md"],
        worktree_porcelain=_PORCELAIN_WITH_TP_X,
        repo="anything",
    )
    assert blocked is True


# ---------------------------------------------------------------------------
# worktree_isolation_guard — default-branch root via repo
# ---------------------------------------------------------------------------


def test_isolation_guard_trunk_root_is_default_branch_root(tmp_path):
    repo = _make_trunk_repo(tmp_path / "repo")
    assert _is_default_branch_root(str(repo), "trunk", False) is True


def test_isolation_guard_assert_own_worktree_blocks_trunk_seat(tmp_path):
    repo = _make_trunk_repo(tmp_path / "repo")
    porcelain = (
        f"worktree {repo}\nHEAD abc123\nbranch refs/heads/trunk\n\n"
        f"worktree {repo}-wt/x\nHEAD def456\nbranch refs/heads/tp/x\n\n"
    )
    ok, msg = assert_own_worktree(
        cwd=str(repo), worktree_porcelain=porcelain, current_branch="trunk",
    )
    assert ok is False
    assert msg


def test_isolation_guard_resolver_error_keeps_fixed_tuple(monkeypatch):
    """Isolate the `branch in default_branch_names(toplevel)` arm: an agent
    worktree path (`.claude/worktrees/...`) never hits the path-shape
    fallback, so only the resolved-tuple membership decides the outcome."""
    def boom(*args, **kwargs):
        raise db.DefaultBranchError("synthetic")
    monkeypatch.setattr(db, "resolve_default_branch", boom)
    agent_wt = "/repo/.claude/worktrees/agent-x"
    assert _is_default_branch_root(agent_wt, "trunk", False) is False
    assert _is_default_branch_root(agent_wt, "master", False) is True
