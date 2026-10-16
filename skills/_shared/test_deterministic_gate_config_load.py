"""test_deterministic_gate_config_load.py — the gate's config loader + config_warning
roster entry.

design: consumer-repo-parity (Task 1.4)

Covers `_load_repo_config`/`_load_config_load`'s schema-pruning behavior (a pruned
key's valid sibling survives; an uncommitted edit stays invisible; the zero-arg cwd
fallback via find_project_root(); a non-repo cwd fails closed to {}) and
`evaluate_gate`'s OMITTED `config_warning` roster entry: present (naming the pruned
key, or the schema_version upgrade rule) on a pruned/fatal committed config, absent
on no committed config at all (the normal consumer state, not a warning) and on an
injected `config=` dict (never loaded, so never warned about).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))


def _git(args, cwd) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(repo_root: Path) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q"], repo_root)
    _git(["config", "user.email", "t@t.test"], repo_root)
    _git(["config", "user.name", "test"], repo_root)


def _commit_config(repo_root: Path, config: dict) -> None:
    cfgdir = repo_root / ".three-pillars"
    cfgdir.mkdir(parents=True, exist_ok=True)
    (cfgdir / "config.json").write_text(json.dumps(config))
    _git(["add", "-A"], repo_root)
    _git(["commit", "-qm", "config commit"], repo_root)


_HERMETIC_RUNNERS = {
    "pr_state_fn": lambda url: {
        "mergeable": "MERGEABLE", "headRefOid": "deadbeef", "statusCheckRollup": [],
    },
    "threads_fn": lambda url: [],
    "labels_fn": lambda url: [],
    "timeline_fn": lambda url: [],
    "head_fn": lambda url: {},
    "commits_fn": lambda url: [],
    "self_login_fn": lambda: "bot",
}


class TestLoadRepoConfigSchemaPruning:
    """`_load_repo_config` shares the pruning loader: an invalid key is dropped,
    a valid sibling survives — never a raw unvalidated `json.load`."""

    def test_pruned_key_keeps_valid_sibling(self, tmp_path, monkeypatch):
        from deterministic_gate import _load_repo_config

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _commit_config(repo_root, {
            "schema_version": 1,
            "review": {"require_review_proof": "no", "automation_identities": ["keep-me"]},
        })
        monkeypatch.chdir(repo_root)

        loaded = _load_repo_config(repo_root)
        assert "require_review_proof" not in loaded.get("review", {})
        assert loaded.get("review", {}).get("automation_identities") == ["keep-me"]

    def test_uncommitted_edit_invisible(self, tmp_path, monkeypatch):
        from deterministic_gate import _load_repo_config

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _commit_config(repo_root, {
            "schema_version": 1, "review": {"automation_identities": ["committed"]},
        })
        cfg_path = repo_root / ".three-pillars" / "config.json"
        # Uncommitted edit to the working tree — must stay invisible (source="head").
        cfg_path.write_text(json.dumps({
            "schema_version": 1, "review": {"automation_identities": ["dirty"]},
        }))
        monkeypatch.chdir(repo_root)

        loaded = _load_repo_config(repo_root)
        assert loaded.get("review", {}).get("automation_identities") == ["committed"], (
            "HEAD-PROVENANCE: gate read an unstaged working-tree config edit"
        )

        # Staged-but-uncommitted edit — the INDEX is not HEAD, so it must stay
        # invisible too (a `git show :path` index read would surface it).
        cfg_path.write_text(json.dumps({
            "schema_version": 1, "review": {"automation_identities": ["staged"]},
        }))
        _git(["add", "-A"], repo_root)
        cfg_path.write_text(json.dumps({
            "schema_version": 1, "review": {"automation_identities": ["dirty"]},
        }))
        loaded = _load_repo_config(repo_root)
        assert loaded.get("review", {}).get("automation_identities") == ["committed"], (
            "HEAD-PROVENANCE: gate read a staged-but-uncommitted config edit"
        )

    def test_zero_arg_cwd_fallback_reads_committed_config(self, tmp_path, monkeypatch):
        """repo_root=None -> find_project_root() -> that repo's committed config."""
        from deterministic_gate import _load_repo_config

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _commit_config(repo_root, {
            "schema_version": 1, "review": {"automation_identities": ["from-cwd"]},
        })
        monkeypatch.chdir(repo_root)

        loaded = _load_repo_config()
        assert loaded.get("review", {}).get("automation_identities") == ["from-cwd"]

    def test_non_repo_cwd_returns_empty(self, tmp_path, monkeypatch):
        from deterministic_gate import _load_repo_config

        non_repo = tmp_path / "not_a_repo"
        non_repo.mkdir()
        monkeypatch.chdir(non_repo)

        assert _load_repo_config() == {}


class TestEvaluateGateConfigWarningRoster:
    """`evaluate_gate(config=None)` surfaces committed-config prune warnings as an
    OMITTED `config_warning` roster entry — informational, never folds into the
    verdict (roster-only, same placement as `config_root_binding`)."""

    @staticmethod
    def _entries(outcome, name):
        return [e for e in (outcome.roster or ()) if e.name == name]

    def test_pruned_key_warning_names_require_review_proof(self, tmp_path, monkeypatch):
        from deterministic_gate import evaluate_gate

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _commit_config(repo_root, {
            "schema_version": 1, "review": {"require_review_proof": "no"},
        })
        monkeypatch.chdir(repo_root)

        outcome = evaluate_gate(
            "https://github.com/o/r/pull/1", runners=dict(_HERMETIC_RUNNERS)
        )
        entries = self._entries(outcome, "config_warning")
        assert len(entries) == 1
        assert entries[0].status == "OMITTED"
        assert "review.require_review_proof" in entries[0].detail

    def test_pruned_key_warning_on_null_sha_early_return(self, tmp_path, monkeypatch):
        from deterministic_gate import evaluate_gate

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _commit_config(repo_root, {
            "schema_version": 1, "review": {"require_review_proof": "no"},
        })
        monkeypatch.chdir(repo_root)

        runners = dict(_HERMETIC_RUNNERS)
        runners["pr_state_fn"] = lambda url: {
            "mergeable": "MERGEABLE", "headRefOid": "", "statusCheckRollup": [],
        }
        outcome = evaluate_gate("https://github.com/o/r/pull/1", runners=runners)
        entries = self._entries(outcome, "config_warning")
        assert len(entries) == 1
        assert "review.require_review_proof" in entries[0].detail

    def test_missing_schema_version_warning_names_upgrade_rule(self, tmp_path, monkeypatch):
        from deterministic_gate import evaluate_gate

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _commit_config(repo_root, {"review": {"expects_copilot": False}})
        monkeypatch.chdir(repo_root)

        outcome = evaluate_gate(
            "https://github.com/o/r/pull/1", runners=dict(_HERMETIC_RUNNERS)
        )
        entries = self._entries(outcome, "config_warning")
        assert len(entries) == 1
        assert "schema_version" in entries[0].detail

    def test_absent_committed_config_no_warning(self, tmp_path, monkeypatch):
        """No committed config at all is the normal consumer state, not a warning."""
        from deterministic_gate import evaluate_gate

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        (repo_root / "placeholder.txt").write_text("x")
        _git(["add", "-A"], repo_root)
        _git(["commit", "-qm", "no config"], repo_root)
        monkeypatch.chdir(repo_root)

        outcome = evaluate_gate(
            "https://github.com/o/r/pull/1", runners=dict(_HERMETIC_RUNNERS)
        )
        assert self._entries(outcome, "config_warning") == []

    def test_injected_config_no_warning(self, tmp_path, monkeypatch):
        """An injected config= dict is never loaded from disk, so never warned about —
        even from a non-repo cwd."""
        from deterministic_gate import evaluate_gate

        non_repo = tmp_path / "not_a_repo"
        non_repo.mkdir()
        monkeypatch.chdir(non_repo)

        outcome = evaluate_gate(
            "https://github.com/o/r/pull/1",
            runners=dict(_HERMETIC_RUNNERS),
            config={
                "schema_version": 1,
                "ci": {"expects_github_checks": False},
                "review": {"expects_copilot": False},
            },
        )
        assert self._entries(outcome, "config_warning") == []
