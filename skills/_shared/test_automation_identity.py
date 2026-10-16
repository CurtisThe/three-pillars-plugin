"""test_automation_identity.py — the one identity core for automation's `gh` writes.

design: review-proof-ambient-gh-identity, Task 1.1 (behaviours B1, B2, B3)

The core resolves the automation account from config, fetches its token per call, builds a
child env without touching `os.environ`, runs a gh write as that identity and refuses before
running when the token is unavailable. With no account it is a pass-through: the runner gets
the caller's argv and kwargs and nothing else. Every test is hermetic: the token runner and
the write runner are fakes, so no live `gh`, keyring or network is involved. Assertions read
the recorded argv, kwargs and env, never message wording beyond the account and remediation
command (skills/_shared/test-fragility.md).

Run with: pytest skills/_shared/test_automation_identity.py -q
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import automation_identity as ai  # noqa: E402

BOT = "CurtisTheBot"
CFG = {"github": {"pr_author_account": BOT, "used_for": "all-prs"}}
WRITE = ["gh", "api", "repos/o/r/issues/7/comments", "-f", "body=x"]
TOKEN_ARGV = ["gh", "auth", "token", "--user", BOT]


class Rec:
    """A write runner: records (argv, kwargs) per call, answers success."""

    def __init__(self):
        self.calls: list = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


class Tok:
    """A token runner for `gh auth token --user <bot>`: records argv, answers per its mode."""

    def __init__(self, returncode=0, stdout="tok-bot\n"):
        self.calls: list = []
        self.returncode = returncode
        self.stdout = stdout

    def __call__(self, argv):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, self.returncode, stdout=self.stdout, stderr="")


# ------------------------------------------------------------ account resolution

@pytest.mark.parametrize("used_for", ["all-prs", "autonomous-only", None])
def test_the_account_resolves_whatever_used_for_says(used_for):
    """`used_for` scopes PR authorship only; every automation write uses the account."""
    github = {"pr_author_account": BOT}
    if used_for is not None:
        github["used_for"] = used_for
    assert ai.resolve_automation_account({"github": github}) == BOT


@pytest.mark.parametrize("config", [{}, {"github": {"pr_author_account": None}}, {"github": {}}])
def test_no_account_resolves_to_none(config):
    assert ai.resolve_automation_account(config) is None


@pytest.mark.parametrize("config", [{"github": "x"}, {"github": {"pr_author_account": ""}}])
def test_an_unusable_github_block_fails_loud(config):
    with pytest.raises(ai.BotAuthUnavailable):
        ai.resolve_automation_account(config)


# ------------------------------------------------- B1: the write runs as the account

def test_a_configured_write_runs_with_the_bots_token_in_its_env():
    rec, tok = Rec(), Tok()
    ai.run_gh_write(WRITE, config=CFG, runner=rec, env={"PATH": "/bin"}, token_runner=tok)
    assert tok.calls == [TOKEN_ARGV]
    assert len(rec.calls) == 1
    argv, kwargs = rec.calls[0]
    assert argv == WRITE
    assert kwargs["env"] == {"PATH": "/bin", "GH_TOKEN": "tok-bot"}


def test_the_token_is_fetched_per_call_and_never_cached():
    rec, tok = Rec(), Tok()
    ai.run_gh_write(WRITE, config=CFG, runner=rec, env={}, token_runner=tok)
    ai.run_gh_write(WRITE, config=CFG, runner=rec, env={}, token_runner=tok)
    assert tok.calls == [TOKEN_ARGV, TOKEN_ARGV]
    assert len(rec.calls) == 2


def test_the_process_env_is_never_mutated_and_nothing_switches_accounts(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    before = dict(os.environ)
    rec, tok = Rec(), Tok()
    ai.run_gh_write(WRITE, config=CFG, runner=rec, token_runner=tok)
    assert dict(os.environ) == before and "GH_TOKEN" not in os.environ
    argvs = [argv for argv, _ in rec.calls] + tok.calls
    assert all("switch" not in argv for argv in argvs)


def test_the_caller_kwargs_reach_the_runner_beside_the_env():
    rec = Rec()
    ai.run_gh_write(WRITE, config=CFG, runner=rec, env={}, token_runner=Tok(),
                    capture_output=True, text=True, timeout=30)
    _, kwargs = rec.calls[0]
    assert kwargs["capture_output"] is True and kwargs["text"] is True and kwargs["timeout"] == 30
    assert kwargs["env"]["GH_TOKEN"] == "tok-bot"


def test_the_default_runners_resolve_subprocess_run_at_call_time(monkeypatch):
    """Existing tests patch `subprocess.run` as a module attribute; both the token probe and
    the write must follow that patch, so each looks it up when it runs."""
    seen: list = []

    def fake_run(argv, **kwargs):
        seen.append((list(argv), kwargs))
        out = "tok-bot\n" if list(argv[:3]) == ["gh", "auth", "token"] else ""
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ai.run_gh_write(WRITE, config=CFG, env={"PATH": "/bin"})
    probe, write = seen
    assert probe[0] == TOKEN_ARGV and probe[1].get("capture_output") is True  # never inherited
    assert write[0] == WRITE and write[1]["env"]["GH_TOKEN"] == "tok-bot"


# ------------------------------------------- B2: an unavailable token refuses first

@pytest.mark.parametrize("returncode, stdout", [(1, "tok-bot\n"), (0, ""), (0, "  \n")])
def test_an_unavailable_token_refuses_before_the_write_runs(returncode, stdout):
    rec = Rec()
    with pytest.raises(ai.BotAuthUnavailable) as caught:
        ai.run_gh_write(WRITE, config=CFG, runner=rec, env={},
                        token_runner=Tok(returncode, stdout))
    assert rec.calls == []  # no ambient fallback, nothing posted
    message = str(caught.value)
    assert BOT in message and "gh auth login" in message  # names the account and the fix
    assert "tok-bot" not in message  # the credential never reaches an exception


# ------------------------------------------------------- B3: no account, pass-through

@pytest.mark.parametrize("config", [None, {}, {"github": {"pr_author_account": None}}])
def test_without_an_account_the_runner_gets_the_callers_argv_and_kwargs_only(config):
    rec, tok = Rec(), Tok()
    ai.run_gh_write(WRITE, config=config, runner=rec, token_runner=tok,
                    capture_output=True, text=True)
    assert rec.calls == [(WRITE, {"capture_output": True, "text": True})]  # no env key
    assert tok.calls == []


def test_without_an_account_a_caller_supplied_env_passes_through_unchanged():
    rec = Rec()
    ai.run_gh_write(WRITE, config={}, runner=rec, env={"PATH": "/bin"}, token_runner=Tok())
    assert rec.calls == [(WRITE, {"env": {"PATH": "/bin"}})]


# ----------------------------------------------------------- the env builders

def test_account_env_adds_the_token_to_a_copy_of_the_base_env():
    base = {"PATH": "/bin", "A": "1"}
    tok = Tok()
    assert ai.account_env(BOT, base, token_runner=tok) == {"PATH": "/bin", "A": "1",
                                                            "GH_TOKEN": "tok-bot"}
    assert base == {"PATH": "/bin", "A": "1"} and tok.calls == [TOKEN_ARGV]


def test_account_env_defaults_the_base_to_the_process_env_without_mutating_it(monkeypatch):
    monkeypatch.setenv("TP_PROBE_VAR", "kept")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    env = ai.account_env(BOT, token_runner=Tok())
    assert env["TP_PROBE_VAR"] == "kept" and env["GH_TOKEN"] == "tok-bot"
    assert "GH_TOKEN" not in os.environ


def test_token_env_merges_a_token_into_a_copy_of_the_base_env():
    base = {"PATH": "/bin"}
    assert ai.token_env("tok-bot", base) == {"PATH": "/bin", "GH_TOKEN": "tok-bot"}
    assert base == {"PATH": "/bin"}


def test_automation_env_is_none_when_no_account_is_configured():
    tok = Tok()
    assert ai.automation_env(None, {"PATH": "/bin"}, token_runner=tok) is None
    assert ai.automation_env({}, {"PATH": "/bin"}, token_runner=tok) is None
    assert tok.calls == []


def test_automation_env_matches_account_env_for_the_configured_account():
    base = {"PATH": "/bin"}
    assert ai.automation_env(CFG, base, token_runner=Tok()) == ai.account_env(
        BOT, base, token_runner=Tok())


# ------------------------------------------------------------------ config load

def test_a_missing_config_file_loads_as_empty(tmp_path):
    assert ai.load_repo_config(tmp_path) == {}


def test_a_config_file_loads_as_its_json(tmp_path):
    (tmp_path / ".three-pillars").mkdir()
    (tmp_path / ".three-pillars" / "config.json").write_text(
        '{"github": {"pr_author_account": "CurtisTheBot"}}', encoding="utf-8")
    assert ai.load_repo_config(tmp_path) == {"github": {"pr_author_account": BOT}}


def test_an_unparseable_config_file_fails_loud(tmp_path):
    (tmp_path / ".three-pillars").mkdir()
    (tmp_path / ".three-pillars" / "config.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ai.BotAuthUnavailable):
        ai.load_repo_config(tmp_path)
