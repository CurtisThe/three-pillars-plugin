"""test_gate_provenance.py — Config provenance: HEAD-read and Behavior 6 tests.

Phase 1: HEAD-read provenance (TestLoadRepoConfigHeadRead)
Phase 2: Behavior 6 config-change gating (TestBehavior6ConfigChangeGating)

Regression floor: test_deterministic_gate.py stays UNMODIFIED and green.
All new tests are in THIS file or test_land_backstop.py.

See also:
  test_land_backstop.py — land() backstop and repro-script regression guards
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure _shared/ is on sys.path
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

# Ensure tp-merge-from-main/scripts is on sys.path (for merge_gate)
_FROM_MAIN_SCRIPTS = _SHARED_DIR.parent / "tp-merge-from-main" / "scripts"
if str(_FROM_MAIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_FROM_MAIN_SCRIPTS))

# Ensure tp-merge/scripts is on sys.path (for land)
_MERGE_SCRIPTS = _SHARED_DIR.parent / "tp-merge" / "scripts"
if str(_MERGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MERGE_SCRIPTS))


# ---------------------------------------------------------------------------
# Helpers: build minimal git repos for provenance tests
# ---------------------------------------------------------------------------

def _git(args, cwd):
    """Run a git command; raise on non-zero exit."""
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _make_committed_config(repo_root: Path, config_dict: dict) -> None:
    """Write, stage, and commit .three-pillars/config.json in repo_root."""
    cfgdir = repo_root / ".three-pillars"
    cfgdir.mkdir(parents=True, exist_ok=True)
    cfgfile = cfgdir / "config.json"
    cfgfile.write_text(json.dumps(config_dict))
    _git(["add", "-A"], repo_root)
    _git(["commit", "-qm", "config commit"], repo_root)


def _init_repo(repo_root: Path) -> None:
    """Create a minimal git repo with user config."""
    _git(["init", "-q", str(repo_root)], ".")
    _git(["config", "user.email", "t@t.test"], repo_root)
    _git(["config", "user.name", "test"], repo_root)


# ---------------------------------------------------------------------------
# Task 1.1: TestLoadRepoConfigHeadRead
# ---------------------------------------------------------------------------

class TestLoadRepoConfigHeadRead:
    """Verify _load_repo_config reads from committed HEAD, never the working tree."""

    def test_committed_true_dirty_false_returns_committed(self, tmp_path, monkeypatch):
        """Committed config has require_human_approval=True; working tree overwritten
        to False uncommitted. The loader must return the committed (True) value."""
        from deterministic_gate import _load_repo_config

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        # Commit config requiring human approval
        _make_committed_config(repo_root, {"review": {"require_human_approval": True}})

        # Now overwrite working tree WITHOUT committing
        cfg_file = repo_root / ".three-pillars" / "config.json"
        cfg_file.write_text(json.dumps({"review": {"require_human_approval": False}}))

        # Chdir into the project repo so find_project_root() resolves it
        monkeypatch.chdir(repo_root)
        loaded = _load_repo_config()

        # Must have read the COMMITTED value (True), not the dirty working tree
        val = loaded.get("review", {}).get("require_human_approval")
        assert val is True, (
            f"Expected committed True, got {val!r}. "
            "Loader honored the dirty working tree, not committed HEAD."
        )

    def test_no_config_at_head_returns_empty(self, tmp_path, monkeypatch):
        """No .three-pillars/config.json at HEAD -> returns {}."""
        from deterministic_gate import _load_repo_config

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        # Make a commit WITHOUT the config file
        (repo_root / "placeholder.txt").write_text("x")
        _git(["add", "-A"], repo_root)
        _git(["commit", "-qm", "no config"], repo_root)

        monkeypatch.chdir(repo_root)
        loaded = _load_repo_config()
        assert loaded == {}

    def test_unborn_head_returns_empty(self, tmp_path, monkeypatch):
        """Unborn HEAD (no commits) -> returns {}."""
        from deterministic_gate import _load_repo_config

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        # No commits at all

        monkeypatch.chdir(repo_root)
        loaded = _load_repo_config()
        assert loaded == {}

    def test_not_a_git_repo_returns_empty(self, tmp_path, monkeypatch):
        """Not inside a git repo -> returns {}."""
        from deterministic_gate import _load_repo_config

        # tmp_path is not a git repo — chdir into it
        non_repo = tmp_path / "not_a_repo"
        non_repo.mkdir()
        monkeypatch.chdir(non_repo)
        loaded = _load_repo_config()
        assert loaded == {}

    def test_committed_bad_json_returns_empty(self, tmp_path, monkeypatch):
        """Committed config is bad JSON -> returns {}."""
        from deterministic_gate import _load_repo_config

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        cfgdir = repo_root / ".three-pillars"
        cfgdir.mkdir(parents=True)
        (cfgdir / "config.json").write_text("{not valid json}")
        _git(["add", "-A"], repo_root)
        _git(["commit", "-qm", "bad json config"], repo_root)

        monkeypatch.chdir(repo_root)
        loaded = _load_repo_config()
        assert loaded == {}

    def test_committed_non_dict_json_returns_empty(self, tmp_path, monkeypatch):
        """Committed config is valid JSON but not a dict (e.g. a list) -> returns {}."""
        from deterministic_gate import _load_repo_config

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        cfgdir = repo_root / ".three-pillars"
        cfgdir.mkdir(parents=True)
        (cfgdir / "config.json").write_text(json.dumps([1, 2, 3]))
        _git(["add", "-A"], repo_root)
        _git(["commit", "-qm", "list json config"], repo_root)

        monkeypatch.chdir(repo_root)
        loaded = _load_repo_config()
        assert loaded == {}

    def test_legit_change_returns_new_committed_value(self, tmp_path, monkeypatch):
        """Commit a config flip -> the next loader call returns the new committed value."""
        from deterministic_gate import _load_repo_config

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _make_committed_config(repo_root, {"review": {"require_human_approval": True}})

        # Now commit a NEW config (the legit operator change)
        _make_committed_config(repo_root, {"review": {"require_human_approval": False}})

        monkeypatch.chdir(repo_root)
        loaded = _load_repo_config()
        val = loaded.get("review", {}).get("require_human_approval")
        # The committed value is now False (legit opt-out)
        assert val is False

    def test_never_falls_back_to_working_tree_on_missing_head_path(self, tmp_path, monkeypatch):
        """Working tree has config but HEAD doesn't: loader returns {} (never disk read)."""
        from deterministic_gate import _load_repo_config

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        # Commit WITHOUT config
        (repo_root / "placeholder.txt").write_text("x")
        _git(["add", "-A"], repo_root)
        _git(["commit", "-qm", "no config commit"], repo_root)

        # Write config to working tree (not committed)
        cfgdir = repo_root / ".three-pillars"
        cfgdir.mkdir(parents=True)
        (cfgdir / "config.json").write_text(
            json.dumps({"review": {"require_human_approval": False}})
        )

        monkeypatch.chdir(repo_root)
        loaded = _load_repo_config()
        # Must return {} (no HEAD config), never the working tree False
        assert loaded == {}


# ---------------------------------------------------------------------------
# Behavior 6: TestBehavior6ConfigChangeGating (design.md Behavior 6)
# ---------------------------------------------------------------------------

class TestBehavior6ConfigChangeGating:
    """Behavior 6: legit config change gated under pre-merge HEAD rules.

    design.md Behavior 6 states: "A legit config change is itself gated under
    the pre-merge HEAD rules." The loader reads the COMMITTED HEAD, so an
    uncommitted config B in the working tree is invisible to the gate;
    only after committing B does the next load return B.
    """

    def test_uncommitted_config_b_returns_config_a(self, tmp_path, monkeypatch):
        """Working-tree config B (uncommitted) -> loader still returns committed A."""
        from deterministic_gate import _load_repo_config

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        config_a = {"review": {"require_human_approval": True}}
        # Commit config A
        _make_committed_config(repo_root, config_a)

        # Write config B to the working tree WITHOUT committing
        cfg_file = repo_root / ".three-pillars" / "config.json"
        config_b = {"review": {"require_human_approval": False}}
        cfg_file.write_text(json.dumps(config_b))

        monkeypatch.chdir(repo_root)
        loaded = _load_repo_config()

        # Must return config A (committed), not config B (uncommitted working tree)
        val = loaded.get("review", {}).get("require_human_approval")
        assert val is True, (
            f"Expected committed config A (True), got {val!r}. "
            "Loader honored the uncommitted working-tree change."
        )

    def test_after_committing_b_returns_config_b(self, tmp_path, monkeypatch):
        """After committing config B -> loader returns B (the legit change is now visible)."""
        from deterministic_gate import _load_repo_config

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        # Commit config A (the old value)
        _make_committed_config(repo_root, {"review": {"require_human_approval": True}})

        # Now commit config B (the legit operator change — creates a git trace)
        _make_committed_config(repo_root, {"review": {"require_human_approval": False}})

        monkeypatch.chdir(repo_root)
        loaded = _load_repo_config()

        # After committing B, the loader must return B
        val = loaded.get("review", {}).get("require_human_approval")
        assert val is False, (
            f"Expected committed config B (False), got {val!r}. "
            "Loader did not pick up the committed change."
        )
