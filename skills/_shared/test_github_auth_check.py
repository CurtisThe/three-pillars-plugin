"""Tests for github_auth_check.py — first-run preflight helper (pr-author-bot-account).

Mirrors test_branch_protection_check.py's shape: tmp_path repos, seam runners,
no live gh. Covers Tasks 1.2 (check() action table) and 1.3 (verify_account /
mark_configured / mark_declined + gate-integration source parity).

Run with: pytest skills/_shared/test_github_auth_check.py -q
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

FIRST_RUN_MD = HERE / "first-run.md"


def _init_repo(tmp_path: Path, with_origin: bool = True) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    if with_origin:
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/Acme/widget.git"],
            cwd=repo,
            check=True,
        )
    return repo


def _write_config(repo: Path, data: dict) -> None:
    cfg_dir = repo / ".three-pillars"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Task 1.2 — check() action table
# ---------------------------------------------------------------------------


class TestCheckActionTable:
    def test_no_origin_returns_skip_no_origin(self, tmp_path):
        import github_auth_check

        repo = _init_repo(tmp_path, with_origin=False)
        result = github_auth_check.check(repo)
        assert result.action == "skip-no-origin"
        assert result.config_updated is False

    def test_pr_author_account_set_returns_skip_decided(self, tmp_path, monkeypatch):
        import github_auth_check

        repo = _init_repo(tmp_path)
        _write_config(repo, {"schema_version": 1, "github": {"pr_author_account": "CurtisTheBot"}})
        monkeypatch.setattr(github_auth_check.shutil, "which", lambda name: "/usr/bin/gh")
        result = github_auth_check.check(repo)
        assert result.action == "skip-decided"
        assert result.config_updated is False

    def test_declined_true_returns_skip_decided(self, tmp_path, monkeypatch):
        import github_auth_check

        repo = _init_repo(tmp_path)
        _write_config(repo, {"schema_version": 1, "github": {"declined": True}})
        monkeypatch.setattr(github_auth_check.shutil, "which", lambda name: "/usr/bin/gh")
        result = github_auth_check.check(repo)
        assert result.action == "skip-decided"

    def test_gh_missing_returns_skip_gh_missing_no_write(self, tmp_path, monkeypatch):
        import github_auth_check

        repo = _init_repo(tmp_path)
        monkeypatch.setattr(github_auth_check.shutil, "which", lambda name: None)
        result = github_auth_check.check(repo)
        assert result.action == "skip-gh-missing"
        assert result.config_updated is False
        assert not (repo / ".three-pillars" / "config.json").exists()

    def test_auto_true_returns_auto_skip_and_appends_decision(self, tmp_path, monkeypatch):
        import github_auth_check

        repo = _init_repo(tmp_path)
        monkeypatch.setattr(github_auth_check.shutil, "which", lambda name: "/usr/bin/gh")
        decisions_file = tmp_path / "decisions.md"
        result = github_auth_check.check(repo, auto=True, decisions_file=decisions_file)
        assert result.action == "auto-skip"
        assert result.config_updated is False
        assert decisions_file.exists()
        text = decisions_file.read_text(encoding="utf-8")
        assert "[first-run]" in text
        assert "GitHub" in text

    def test_otherwise_returns_needs_prompt(self, tmp_path, monkeypatch):
        import github_auth_check

        repo = _init_repo(tmp_path)
        monkeypatch.setattr(github_auth_check.shutil, "which", lambda name: "/usr/bin/gh")
        result = github_auth_check.check(repo)
        assert result.action == "needs-prompt"
        assert result.config_updated is False

    def test_module_importable(self):
        import github_auth_check  # noqa: F401


# ---------------------------------------------------------------------------
# Task 1.3 — verify_account / mark_configured / mark_declined
# ---------------------------------------------------------------------------


class TestVerifyAccount:
    def test_rc0_returns_true(self):
        import github_auth_check

        def fake_rc0(argv):
            return subprocess.CompletedProcess(argv, 0, stdout="gho_faketoken\n", stderr="")

        assert github_auth_check.verify_account("CurtisTheBot", runner=fake_rc0) is True

    def test_rc1_returns_false_never_raises(self):
        import github_auth_check

        def fake_rc1(argv):
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="no such account")

        assert github_auth_check.verify_account("CurtisTheBot", runner=fake_rc1) is False

    def test_default_runner_captures_stdout(self, monkeypatch):
        """The default probe runner must use capture_output semantics — an
        inheriting runner would print the credential to the terminal."""
        import github_auth_check

        captured = {}

        def fake_subprocess_run(argv, **kwargs):
            captured.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, stdout="tok\n", stderr="")

        monkeypatch.setattr(github_auth_check.subprocess, "run", fake_subprocess_run)
        github_auth_check.verify_account("CurtisTheBot")
        assert captured.get("capture_output") is True


class TestMarkConfigured:
    def test_writes_schema_valid_config_with_automation_append(self, tmp_path):
        import github_auth_check

        repo = _init_repo(tmp_path)
        github_auth_check.mark_configured(
            repo, "CurtisTheBot", review_requests=["CurtisThe"]
        )
        cfg = json.loads((repo / ".three-pillars" / "config.json").read_text(encoding="utf-8"))
        assert cfg["github"]["pr_author_account"] == "CurtisTheBot"
        assert cfg["github"]["verified_at"] is not None
        assert cfg["github"]["offered_at"] is not None
        assert cfg["github"]["declined"] is False
        assert cfg["github"]["review_requests"] == ["CurtisThe"]
        assert "curtisthebot" in cfg["review"]["automation_identities"]

    def test_dedups_automation_identities_on_second_call(self, tmp_path):
        import github_auth_check

        repo = _init_repo(tmp_path)
        github_auth_check.mark_configured(repo, "CurtisTheBot")
        github_auth_check.mark_configured(repo, "CurtisTheBot")
        cfg = json.loads((repo / ".three-pillars" / "config.json").read_text(encoding="utf-8"))
        assert cfg["review"]["automation_identities"].count("curtisthebot") == 1

    def test_preserves_existing_automation_identities(self, tmp_path):
        import github_auth_check

        repo = _init_repo(tmp_path)
        _write_config(
            repo,
            {"schema_version": 1, "review": {"automation_identities": ["deploybot"]}},
        )
        github_auth_check.mark_configured(repo, "CurtisTheBot")
        cfg = json.loads((repo / ".three-pillars" / "config.json").read_text(encoding="utf-8"))
        assert "deploybot" in cfg["review"]["automation_identities"]
        assert "curtisthebot" in cfg["review"]["automation_identities"]

    def test_creates_review_block_if_absent(self, tmp_path):
        import github_auth_check

        repo = _init_repo(tmp_path)
        github_auth_check.mark_configured(repo, "CurtisTheBot")
        cfg = json.loads((repo / ".three-pillars" / "config.json").read_text(encoding="utf-8"))
        assert isinstance(cfg.get("review"), dict)


class TestMarkDeclined:
    def test_sets_sticky_declined(self, tmp_path):
        import github_auth_check

        repo = _init_repo(tmp_path)
        github_auth_check.mark_declined(repo)
        cfg = json.loads((repo / ".three-pillars" / "config.json").read_text(encoding="utf-8"))
        assert cfg["github"]["declined"] is True
        assert cfg["github"]["offered_at"] is not None

    def test_declined_then_check_returns_skip_decided(self, tmp_path, monkeypatch):
        import github_auth_check

        repo = _init_repo(tmp_path)
        monkeypatch.setattr(github_auth_check.shutil, "which", lambda name: "/usr/bin/gh")
        github_auth_check.mark_declined(repo)
        result = github_auth_check.check(repo)
        assert result.action == "skip-decided"


class TestGateIntegrationSourceParity:
    """B5 — the merge gate reads config from committed HEAD via
    `git show HEAD:.three-pillars/config.json` (deterministic_gate.py:542/693).
    Commit the config in a tmp git repo, load it back the SAME way, and assert
    the gate-facing predicates against that source-parity read."""

    def test_committed_config_makes_bot_automation_and_human_satisfiable(self, tmp_path):
        import github_auth_check

        repo = _init_repo(tmp_path)
        github_auth_check.mark_configured(
            repo, "CurtisTheBot", review_requests=["CurtisThe"]
        )
        subprocess.run(["git", "add", ".three-pillars/config.json"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "config: PR-author bot account"], cwd=repo, check=True)

        show = subprocess.run(
            ["git", "show", "HEAD:.three-pillars/config.json"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        git_show_cfg = json.loads(show.stdout)

        import human_approval

        automation = human_approval.automation_identities(self_login="x", config=git_show_cfg)
        assert "curtisthebot" in automation

        bot_event = {"actor": {"type": "User", "login": "CurtisTheBot"}}
        human_event = {"actor": {"type": "User", "login": "CurtisThe"}}
        assert human_approval._actor_is_human(bot_event, automation) is False
        assert human_approval._actor_is_human(human_event, automation) is True


# ---------------------------------------------------------------------------
# Task 4.1 — first-run.md prose guard (condition 7 + ## GitHub PR-author offer)
# ---------------------------------------------------------------------------


class TestFirstRunMdProseGuard:
    def _read(self) -> str:
        return FIRST_RUN_MD.read_text(encoding="utf-8")

    def _offer_section(self) -> str:
        text = self._read()
        # Newline-prefixed heading anchor — the cheap-path routing sentence
        # above references '## GitHub PR-author offer' inline (backtick-quoted),
        # so a bare split() would capture that earlier mention instead.
        return text.split("\n## GitHub PR-author offer", 1)[1].split("\n## ", 1)[0]

    def test_cheap_path_condition_names_pr_author_fields(self):
        text = self._read()
        assert "github.pr_author_account" in text
        assert "github.declined" in text

    def test_all_conditions_summary_updated_to_seven(self):
        text = self._read()
        assert "all seven" in text.lower(), (
            "the cheap-path summary must be updated from 'all six' to 'all seven'"
        )
        assert "all six" not in text.lower()

    def test_github_pr_author_offer_section_exists(self):
        assert "## GitHub PR-author offer" in self._read()

    def test_offer_section_references_helper(self):
        assert "github_auth_check.py" in self._offer_section()

    def test_offer_section_documents_account_no_skip_prompt(self):
        section = self._offer_section()
        assert "account" in section.lower()
        assert re.search(r"/\s*no\s*/", section) or re.search(r"\bno\b", section, re.IGNORECASE)
        assert "skip" in section.lower()

    def test_offer_section_documents_auto_skip_row(self):
        assert "--auto" in self._offer_section()

    def test_offer_section_documents_verify_fail_no_write_reoffer(self):
        section = self._offer_section()
        assert "gh auth login" in section
        assert re.search(r"do not\s+write|not write|re-offer", section, re.IGNORECASE)

    def test_offer_section_documents_commit_immediately(self):
        section = self._offer_section()
        assert "commit" in section.lower()
        assert re.search(r"committed head", section, re.IGNORECASE)

    def test_offer_section_no_invariant_or_known_issue_citations(self):
        section = self._offer_section()
        assert not re.search(r"invariant\s*#?\d+", section, re.IGNORECASE)
        assert not re.search(r"\bM\d+\b", section)

    def test_auto_defaults_table_gains_github_pr_author_row(self):
        text = self._read()
        assert "GitHub PR-author unconfigured" in text
