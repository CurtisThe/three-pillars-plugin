"""Tests for github_pr_author.py — the single PR-create chokepoint (pr-author-bot-account).

Task 2.1: resolve_pr_author truth table + bot_token fail-loud.

Run with: pytest skills/_shared/test_github_pr_author.py -q
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _cfg(account="CurtisTheBot", used_for=None, github_overrides=None):
    github = {"pr_author_account": account}
    if used_for is not None:
        github["used_for"] = used_for
    if github_overrides:
        github.update(github_overrides)
    return {"schema_version": 1, "github": github}


# ---------------------------------------------------------------------------
# resolve_pr_author truth table
# ---------------------------------------------------------------------------


class TestResolvePrAuthorTruthTable:
    def test_all_prs_returns_account_for_manual(self):
        import github_pr_author

        cfg = _cfg(used_for="all-prs")
        assert github_pr_author.resolve_pr_author(cfg, "manual") == "CurtisTheBot"

    def test_all_prs_returns_account_for_autonomous(self):
        import github_pr_author

        cfg = _cfg(used_for="all-prs")
        assert github_pr_author.resolve_pr_author(cfg, "autonomous") == "CurtisTheBot"

    def test_autonomous_only_returns_account_for_autonomous(self):
        import github_pr_author

        cfg = _cfg(used_for="autonomous-only")
        assert github_pr_author.resolve_pr_author(cfg, "autonomous") == "CurtisTheBot"

    def test_autonomous_only_returns_none_for_manual(self):
        import github_pr_author

        cfg = _cfg(used_for="autonomous-only")
        assert github_pr_author.resolve_pr_author(cfg, "manual") is None

    def test_used_for_absent_treated_as_all_prs(self):
        import github_pr_author

        cfg = _cfg(used_for=None)
        assert github_pr_author.resolve_pr_author(cfg, "manual") == "CurtisTheBot"
        assert github_pr_author.resolve_pr_author(cfg, "autonomous") == "CurtisTheBot"

    def test_used_for_null_treated_as_all_prs(self):
        import github_pr_author

        cfg = _cfg(github_overrides={"used_for": None})
        assert github_pr_author.resolve_pr_author(cfg, "manual") == "CurtisTheBot"

    def test_no_github_key_returns_none(self):
        import github_pr_author

        assert github_pr_author.resolve_pr_author({"schema_version": 1}, "manual") is None

    def test_pr_author_account_null_returns_none(self):
        import github_pr_author

        cfg = {"schema_version": 1, "github": {"pr_author_account": None}}
        assert github_pr_author.resolve_pr_author(cfg, "manual") is None

    def test_pr_author_account_null_returns_none_even_with_bad_used_for(self):
        """A null account is unconfigured regardless of used_for's validity."""
        import github_pr_author

        cfg = {"schema_version": 1, "github": {"pr_author_account": None, "used_for": "sometimes"}}
        assert github_pr_author.resolve_pr_author(cfg, "manual") is None

    def test_non_dict_github_raises_bot_auth_unavailable(self):
        import github_pr_author

        cfg = {"schema_version": 1, "github": "not-a-dict"}
        try:
            github_pr_author.resolve_pr_author(cfg, "manual")
            assert False, "expected BotAuthUnavailable"
        except github_pr_author.BotAuthUnavailable:
            pass

    def test_non_str_account_raises_bot_auth_unavailable(self):
        import github_pr_author

        cfg = {"schema_version": 1, "github": {"pr_author_account": 42}}
        try:
            github_pr_author.resolve_pr_author(cfg, "manual")
            assert False, "expected BotAuthUnavailable"
        except github_pr_author.BotAuthUnavailable:
            pass

    def test_empty_string_account_raises_bot_auth_unavailable(self):
        import github_pr_author

        cfg = _cfg(account="")
        try:
            github_pr_author.resolve_pr_author(cfg, "manual")
            assert False, "expected BotAuthUnavailable"
        except github_pr_author.BotAuthUnavailable:
            pass

    def test_unknown_used_for_raises_bot_auth_unavailable(self):
        import github_pr_author

        cfg = _cfg(used_for="sometimes")
        try:
            github_pr_author.resolve_pr_author(cfg, "manual")
            assert False, "expected BotAuthUnavailable"
        except github_pr_author.BotAuthUnavailable:
            pass

    def test_context_weird_raises_value_error(self):
        import github_pr_author

        cfg = _cfg(used_for="all-prs")
        try:
            github_pr_author.resolve_pr_author(cfg, "weird")
            assert False, "expected ValueError"
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# bot_token fail-loud
# ---------------------------------------------------------------------------


class TestBotToken:
    def test_rc1_raises_bot_auth_unavailable_with_actionable_message(self):
        import github_pr_author

        def fake_rc1(argv):
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="no such account")

        try:
            github_pr_author.bot_token("CurtisTheBot", runner=fake_rc1)
            assert False, "expected BotAuthUnavailable"
        except github_pr_author.BotAuthUnavailable as exc:
            msg = str(exc)
            assert "CurtisTheBot" in msg
            assert "gh auth login" in msg
            assert "github.pr_author_account" in msg
            assert "2.40" in msg

    def test_rc0_returns_token(self):
        import github_pr_author

        def fake_rc0(argv):
            return subprocess.CompletedProcess(argv, 0, stdout="gho_secrettoken\n", stderr="")

        assert github_pr_author.bot_token("CurtisTheBot", runner=fake_rc0) == "gho_secrettoken"

    def test_token_never_in_exception_message(self):
        import github_pr_author

        def fake_rc1(argv):
            return subprocess.CompletedProcess(argv, 1, stdout="gho_leaked", stderr="")

        try:
            github_pr_author.bot_token("CurtisTheBot", runner=fake_rc1)
            assert False, "expected BotAuthUnavailable"
        except github_pr_author.BotAuthUnavailable as exc:
            assert "gho_leaked" not in str(exc)

    def test_default_runner_captures_stdout(self, monkeypatch):
        """The default probe runner must use capture_output semantics — an
        inheriting runner would print the credential to the terminal."""
        import github_pr_author

        captured = {}

        def fake_subprocess_run(argv, **kwargs):
            captured.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, stdout="tok\n", stderr="")

        monkeypatch.setattr(github_pr_author.subprocess, "run", fake_subprocess_run)
        github_pr_author.bot_token("CurtisTheBot")
        assert captured.get("capture_output") is True

    def test_no_gh_auth_switch_anywhere_in_module(self):
        """Grep assertion: the module must never INVOKE `gh auth switch` as a
        subprocess argv (prose mentioning the prohibition is fine — this
        checks for the quoted argv literal, not a substring anywhere)."""
        source = Path(github_pr_author_path()).read_text(encoding="utf-8")
        assert '"switch"' not in source and "'switch'" not in source


def github_pr_author_path():
    import github_pr_author

    return github_pr_author.__file__


# ---------------------------------------------------------------------------
# Task 2.2 — create_pr: env isolation, no fallback, reviewer append
# ---------------------------------------------------------------------------


class _Spy:
    """Records every call; returns a fixed CompletedProcess."""

    def __init__(self, returncode=0, stdout="https://github.com/Acme/widget/pull/1\n"):
        self.calls = []
        self.returncode = returncode
        self.stdout = stdout

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), "kwargs": kwargs})
        return subprocess.CompletedProcess(argv, self.returncode, stdout=self.stdout, stderr="")


class TestCreatePr:
    def test_unconfigured_calls_runner_once_no_gh_token(self):
        import github_pr_author

        spy = _Spy()
        rc = github_pr_author.create_pr(
            ["--base", "master"], {"schema_version": 1}, "manual", runner=spy
        )
        assert rc == 0
        assert len(spy.calls) == 1
        assert spy.calls[0]["argv"] == ["gh", "pr", "create", "--base", "master"]
        env = spy.calls[0]["kwargs"].get("env") or {}
        assert "GH_TOKEN" not in env

    def test_configured_child_env_carries_token_os_environ_unmutated(self):
        import github_pr_author
        import os

        before = dict(os.environ)
        spy = _Spy()

        def fake_token_runner(argv):
            return subprocess.CompletedProcess(argv, 0, stdout="gho_tok\n", stderr="")

        cfg = _cfg(used_for="all-prs")
        rc = github_pr_author.create_pr(
            ["--base", "master"], cfg, "manual", runner=spy, token_runner=fake_token_runner
        )
        assert rc == 0
        env = spy.calls[0]["kwargs"].get("env")
        assert env is not None
        assert env["GH_TOKEN"] == "gho_tok"
        assert os.environ == before, "os.environ must be unmutated after create_pr"

    def test_configured_token_failure_propagates_create_runner_never_invoked(self):
        import github_pr_author

        spy = _Spy()

        def fake_token_runner(argv):
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="no account")

        cfg = _cfg(used_for="all-prs")
        try:
            github_pr_author.create_pr(
                ["--base", "master"], cfg, "manual", runner=spy, token_runner=fake_token_runner
            )
            assert False, "expected BotAuthUnavailable"
        except github_pr_author.BotAuthUnavailable:
            pass
        assert spy.calls == [], "the create runner must NEVER be invoked after a token failure"

    def test_reviewer_appended_when_configured_and_absent(self):
        import github_pr_author

        spy = _Spy()

        def fake_token_runner(argv):
            return subprocess.CompletedProcess(argv, 0, stdout="tok\n", stderr="")

        cfg = _cfg(used_for="all-prs", github_overrides={"review_requests": ["CurtisThe"]})
        github_pr_author.create_pr(
            ["--base", "master"], cfg, "manual", runner=spy, token_runner=fake_token_runner
        )
        assert "--reviewer" in spy.calls[0]["argv"]
        idx = spy.calls[0]["argv"].index("--reviewer")
        assert spy.calls[0]["argv"][idx + 1] == "CurtisThe"

    def test_reviewer_not_appended_when_already_present(self):
        import github_pr_author

        spy = _Spy()

        def fake_token_runner(argv):
            return subprocess.CompletedProcess(argv, 0, stdout="tok\n", stderr="")

        cfg = _cfg(used_for="all-prs", github_overrides={"review_requests": ["CurtisThe"]})
        github_pr_author.create_pr(
            ["--base", "master", "--reviewer", "SomeoneElse"],
            cfg,
            "manual",
            runner=spy,
            token_runner=fake_token_runner,
        )
        assert spy.calls[0]["argv"].count("--reviewer") == 1

    def test_reviewer_not_appended_when_unconfigured(self):
        import github_pr_author

        spy = _Spy()
        github_pr_author.create_pr(["--base", "master"], {"schema_version": 1}, "manual", runner=spy)
        assert "--reviewer" not in spy.calls[0]["argv"]

    def test_non_list_review_requests_no_append_no_raise(self):
        import github_pr_author

        spy = _Spy()

        def fake_token_runner(argv):
            return subprocess.CompletedProcess(argv, 0, stdout="tok\n", stderr="")

        cfg = _cfg(used_for="all-prs", github_overrides={"review_requests": "not-a-list"})
        rc = github_pr_author.create_pr(
            ["--base", "master"], cfg, "manual", runner=spy, token_runner=fake_token_runner
        )
        assert rc == 0
        assert "--reviewer" not in spy.calls[0]["argv"]

    def test_stdout_stderr_pass_through(self):
        """The PR URL (in stdout) must reach the caller — runner is not swallowed."""
        import github_pr_author

        spy = _Spy(stdout="https://github.com/Acme/widget/pull/42\n")
        github_pr_author.create_pr(["--base", "master"], {"schema_version": 1}, "manual", runner=spy)
        # create_pr's return is the child's returncode; stdout/stderr pass-through
        # is a property of NOT using capture_output on the create runner call.
        assert "capture_output" not in spy.calls[0]["kwargs"] or not spy.calls[0]["kwargs"].get("capture_output")
