"""Tests for evaluate_gate's `repo_root` override — task 8.1 (dispatch-from-seat
ACTIVATION mechanism, Phase 8).

`repo_root` is NOT a bare runner key: it is an explicit kwarg on evaluate_gate /
merge_gate_blocking / require_merge_gate_pass that replaces `find_project_root()`
for (a) the committed-HEAD config read, (b) gate_roster's project-root resolution
(balloon/stamp), and (c) the carry_repo_root key threaded to both carry consumers.

The CRITICAL regression pin (see test_repo_root_alone_stays_full_live_mode below):
passing repo_root ALONE must NOT flip evaluate_gate's live-mode detection — a
--repo invocation with no other runners injected must stay a FULL LIVE gate.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import deterministic_gate as dg  # noqa: E402
import gate_roster  # noqa: E402


PR_URL = "https://github.com/example/repo/pull/1"


def _git(cwd, *args, check=True):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=check)


def _make_repo(tmp_path, name, config: dict) -> Path:
    """A minimal git repo with a committed .three-pillars/config.json at HEAD."""
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@test")
    _git(repo, "config", "user.name", "fixture")
    cfg_dir = repo / ".three-pillars"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed config")
    # Binding check (W4): the config-root's origin remote must match the PR's
    # owner/repo, else evaluate_gate treats the config as untrusted and resets it to
    # {} (strict defaults) — matching PR_URL below so these fixtures exercise the
    # config VALUE, not the (separately-tested) binding-mismatch fallback.
    _git(repo, "remote", "add", "origin", "https://github.com/example/repo.git")
    return repo


# ============================================================
# Task 8.1: _load_repo_config(repo_root=...) override
# ============================================================


class TestLoadRepoConfigOverride:
    def test_repo_root_reads_that_roots_committed_config(self, tmp_path):
        marker_cfg = {"review": {"require_human_approval": False}, "_marker": "B"}
        repo_b = _make_repo(tmp_path, "repo_b", marker_cfg)

        result = dg._load_repo_config(repo_root=str(repo_b))
        assert result == marker_cfg

    def test_repo_root_none_falls_back_to_find_project_root(self, tmp_path, monkeypatch):
        marker_cfg = {"_marker": "A"}
        repo_a = _make_repo(tmp_path, "repo_a", marker_cfg)

        import project_root
        monkeypatch.setattr(project_root, "find_project_root", lambda: repo_a)

        result = dg._load_repo_config()
        assert result == marker_cfg

    def test_unresolvable_repo_root_fails_closed_to_empty_dict(self, tmp_path):
        not_a_repo = tmp_path / "not-a-repo"
        not_a_repo.mkdir()
        assert dg._load_repo_config(repo_root=str(not_a_repo)) == {}


# ============================================================
# Task 8.1: evaluate_gate(repo_root=...) config override wins over cwd
# ============================================================


class TestEvaluateGateRepoRootOverride:
    """repoA (the wrong/cwd-fallback repo) OMITS human_approved via config; repoB (the
    --repo override target) requires it (ACTIVE). Predicate ACTIVE-vs-OMITTED in the
    roster is the observable signal that repo_root's config won (or lost)."""

    def _runners(self):
        return {
            "pr_state_fn": lambda url: {
                "mergeable": "MERGEABLE", "headRefOid": "deadbeef", "statusCheckRollup": [],
            },
            "threads_fn": lambda url: [],
            "self_login_fn": lambda: "framework-bot",
            "reviews_fn": lambda url: [],
            "head_fn": lambda url: {"headRefOid": "deadbeef"},
        }

    _OMIT_ALL = {
        "review": {"require_human_approval": False, "expects_copilot": False,
                    "require_review_proof": False},
        "ci": {"expects_github_checks": False},
    }
    _REQUIRE_HUMAN = {
        "review": {"require_human_approval": True, "expects_copilot": False,
                    "require_review_proof": False},
        "ci": {"expects_github_checks": False},
    }

    def _roster_status(self, outcome, name):
        entry = next((e for e in outcome.roster if e.name == name), None)
        assert entry is not None, f"no roster entry named {name!r}"
        return entry.status

    def test_without_override_cwd_config_governs(self, tmp_path, monkeypatch):
        repo_a = _make_repo(tmp_path, "repo_a", self._OMIT_ALL)
        import project_root
        monkeypatch.setattr(project_root, "find_project_root", lambda: repo_a)

        outcome = dg.evaluate_gate(PR_URL, runners=self._runners())
        assert self._roster_status(outcome, "human_approved") == "OMITTED"

    def test_repo_root_override_wins_over_cwd(self, tmp_path, monkeypatch):
        repo_a = _make_repo(tmp_path, "repo_a", self._OMIT_ALL)   # wrong-cwd fallback
        repo_b = _make_repo(tmp_path, "repo_b", self._REQUIRE_HUMAN)  # --repo target
        import project_root
        monkeypatch.setattr(project_root, "find_project_root", lambda: repo_a)

        outcome = dg.evaluate_gate(PR_URL, runners=self._runners(), repo_root=str(repo_b))
        assert self._roster_status(outcome, "human_approved") != "OMITTED", (
            "repo_root must override the cwd-derived config — human_approved should be "
            "ACTIVE (repoB requires it), not OMITTED (repoA's config)"
        )


# ============================================================
# Task 8.1: CRITICAL regression pin — repo_root alone stays full live mode
# ============================================================


class TestRunningLiveRegressionPin:
    def test_repo_root_alone_stays_full_live_mode(self, monkeypatch, tmp_path):
        """A --repo invocation with NO other runners injected must remain a FULL LIVE
        gate: _running_live must stay True, and the carry_repo_root key must be
        threaded into gate_roster's r — computed from the ORIGINAL (empty) runners
        dict, never from a dict that already carries the repo_root injection."""
        captured = {}

        def _spy(**kwargs):
            captured["running_live"] = kwargs.get("running_live")
            captured["r"] = kwargs.get("r")
            return [], []

        monkeypatch.setattr(gate_roster, "build_predicates_and_roster", _spy)
        monkeypatch.setattr(
            dg, "_live_pr_state_fn",
            lambda pr_url: {"mergeable": "MERGEABLE", "headRefOid": "deadbeef",
                            "statusCheckRollup": []},
        )
        monkeypatch.setattr(dg, "_default_threads_fn", lambda pr_url: [])

        repo_root = str(tmp_path)  # config load fails closed to {} here; irrelevant to the pin
        dg.evaluate_gate(PR_URL, repo_root=repo_root)

        assert captured["running_live"] is True, (
            "passing repo_root alone must not flip running_live to False — a --repo "
            "invocation must stay a FULL LIVE gate, never look like a hermetic run"
        )
        assert captured["r"].get("carry_repo_root") == repo_root

    def test_runners_plus_repo_root_stays_non_live(self, monkeypatch, tmp_path):
        """Sanity: when the caller DOES inject runners alongside repo_root, live-mode
        detection is unaffected by repo_root — it was already non-live because of the
        injected runners, exactly as before this task."""
        captured = {}

        def _spy(**kwargs):
            captured["running_live"] = kwargs.get("running_live")
            captured["r"] = kwargs.get("r")
            return [], []

        monkeypatch.setattr(gate_roster, "build_predicates_and_roster", _spy)

        repo_root = str(tmp_path)
        dg.evaluate_gate(
            PR_URL,
            runners={
                "pr_state_fn": lambda url: {
                    "mergeable": "MERGEABLE", "headRefOid": "deadbeef", "statusCheckRollup": [],
                },
            },
            repo_root=repo_root,
        )

        assert captured["running_live"] is False
        assert captured["r"].get("carry_repo_root") == repo_root
        assert captured["r"].get("pr_state_fn") is not None


# ============================================================
# Task 8.1: merge_gate_blocking / require_merge_gate_pass passthrough
# ============================================================


class TestMergeGatePassthrough:
    def test_merge_gate_blocking_threads_repo_root(self, tmp_path, monkeypatch):
        sys.path.insert(0, str(HERE.parent / "tp-merge-from-main" / "scripts"))
        import merge_gate

        captured = {}

        def fake_evaluate_gate(pr_url, *, runners=None, config=None, repo_root=None):
            captured["repo_root"] = repo_root
            return dg.GateOutcome(verdict=dg.GateVerdict.PASS, blocking=[], label=dg.GATE_LABEL)

        monkeypatch.setattr(merge_gate, "evaluate_gate", fake_evaluate_gate)
        merge_gate.merge_gate_blocking(PR_URL, repo_root="/some/repo")
        assert captured["repo_root"] == "/some/repo"

    def test_require_merge_gate_pass_threads_repo_root(self, tmp_path, monkeypatch):
        sys.path.insert(0, str(HERE.parent / "tp-merge-from-main" / "scripts"))
        import merge_gate

        captured = {}

        def fake_evaluate_gate(pr_url, *, runners=None, config=None, repo_root=None):
            captured["repo_root"] = repo_root
            return dg.GateOutcome(verdict=dg.GateVerdict.PASS, blocking=[], label=dg.GATE_LABEL)

        monkeypatch.setattr(merge_gate, "evaluate_gate", fake_evaluate_gate)
        merge_gate.require_merge_gate_pass(PR_URL, repo_root="/some/other/repo")
        assert captured["repo_root"] == "/some/other/repo"
