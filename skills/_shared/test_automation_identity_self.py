"""test_automation_identity_self.py — the `per_developer_author: self` write-side fallback.

design: per-developer-automation-account, Task 1.1 (behaviours 1-5)

Under `self`, a bot token that cannot be fetched sends the write out on the ambient gh login
instead of raising; under `off` (or no key) the raise is unchanged. Every test is hermetic:
the token runner, the write runner and the login runner are fakes, so no live `gh`, keyring or
network is involved. Assertions read recorded argv, kwargs, env and stderr, never message
wording beyond the names a fix must mention.

Run with: pytest skills/_shared/test_automation_identity_self.py -q
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

BOT = {"github": {"pr_author_account": "TeamBot"}}
SELF = {"github": {"pr_author_account": "TeamBot", "per_developer_author": "self"}}
OFF = {"github": {"pr_author_account": "TeamBot", "per_developer_author": "off"}}
WRITE = ["gh", "pr", "edit", "U"]


class Rec:
    """A write runner: records (argv, kwargs) per call, answers success."""

    def __init__(self):
        self.calls: list = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


def failing_token(argv):
    return subprocess.CompletedProcess(argv, 1, stdout="SECRET", stderr="")


def working_token(argv):
    return subprocess.CompletedProcess(argv, 0, stdout="tok\n", stderr="")


class Login:
    """A fake for `automation_identity._login_runner`: records calls, answers per its mode."""

    def __init__(self, returncode=0, stdout="alice\n"):
        self.calls: list = []
        self.returncode = returncode
        self.stdout = stdout

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, self.returncode, stdout=self.stdout, stderr="")


@pytest.fixture(autouse=True)
def _fresh_ambient():
    ai._reset_ambient_login()
    yield
    ai._reset_ambient_login()


@pytest.fixture
def login(monkeypatch):
    fake = Login()
    monkeypatch.setattr(ai, "_login_runner", fake)
    return fake


@pytest.mark.parametrize("cfg", [BOT, OFF])
def test_a_missing_token_raises_before_the_write_under_off_or_no_key(cfg, login):
    rec = Rec()
    try:
        ai.run_gh_write(WRITE, config=cfg, runner=rec, token_runner=failing_token)
    except ai.BotAuthUnavailable as caught:
        exc = caught
    else:
        exc = None
    assert exc is not None, "off-path must never fall back to the ambient login: nothing raised"
    assert rec.calls == [], "off-path must never fall back to the ambient login: the write ran"
    assert login.calls == [], "off-path must never fall back to the ambient login: gh api user ran"
    message = str(exc)
    assert "pr_author_account" in message
    assert "per_developer_author" in message
    assert "SECRET" not in message


def test_self_runs_the_write_on_the_ambient_login_with_no_env_added(login):
    rec = Rec()
    ai.run_gh_write(WRITE, config=SELF, runner=rec, token_runner=failing_token)
    assert rec.calls == [(WRITE, {})]


def test_self_passes_a_caller_env_through_unchanged(login):
    rec = Rec()
    ai.run_gh_write(WRITE, config=SELF, runner=rec, env={"A": "1"}, token_runner=failing_token)
    assert rec.calls == [(WRITE, {"env": {"A": "1"}})]


def test_a_working_token_wins_and_the_login_is_never_asked(login):
    rec = Rec()
    ai.run_gh_write(WRITE, config=SELF, runner=rec, token_runner=working_token)
    (argv, kwargs), = rec.calls
    assert argv == WRITE
    assert kwargs["env"]["GH_TOKEN"] == "tok"
    assert login.calls == []


def test_the_ambient_login_resolves_once_and_stderr_names_it_never_a_token(login, capsys):
    rec = Rec()
    ai.run_gh_write(WRITE, config=SELF, runner=rec, token_runner=failing_token)
    ai.run_gh_write(WRITE, config=SELF, runner=rec, token_runner=failing_token)
    assert len(login.calls) == 1
    err = capsys.readouterr().err
    assert "alice" in err
    assert err.count("automation writes run as") == 1  # one notice per process
    assert "SECRET" not in err and "tok" not in err.replace("token", "")


def test_self_with_an_unresolvable_login_raises_without_leaking_the_token(monkeypatch):
    monkeypatch.setattr(ai, "_login_runner", Login(returncode=1, stdout=""))
    rec = Rec()
    with pytest.raises(ai.BotAuthUnavailable) as exc:
        ai.run_gh_write(WRITE, config=SELF, runner=rec, token_runner=failing_token)
    assert rec.calls == []
    assert "SECRET" not in str(exc.value)


@pytest.mark.parametrize("cfg", [None, {}, {"github": {}}, {"github": {"per_developer_author": None}}])
def test_per_developer_mode_reads_off_for_an_absent_or_null_key(cfg):
    assert ai.per_developer_mode(cfg) == "off"


@pytest.mark.parametrize("value", ["own-bot", True, "SELF"])
def test_per_developer_mode_raises_on_any_other_value(value):
    with pytest.raises(ai.BotAuthUnavailable):
        ai.per_developer_mode({"github": {"per_developer_author": value}})


def test_per_developer_mode_reads_self_and_off():
    assert ai.per_developer_mode(SELF) == "self"
    assert ai.per_developer_mode(OFF) == "off"


def test_a_malformed_account_under_self_still_raises_and_never_falls_back(login):
    cfg = {"github": {"pr_author_account": "", "per_developer_author": "self"}}
    rec = Rec()
    with pytest.raises(ai.BotAuthUnavailable):
        ai.run_gh_write(WRITE, config=cfg, runner=rec, token_runner=failing_token)
    assert rec.calls == [] and login.calls == []


def test_the_process_env_is_never_mutated(login):
    before = dict(os.environ)
    ai.run_gh_write(WRITE, config=SELF, runner=Rec(), token_runner=failing_token)
    ai.run_gh_write(WRITE, config=SELF, runner=Rec(), token_runner=working_token)
    assert dict(os.environ) == before


@pytest.mark.parametrize("cfg", [
    {"github": {"pr_author_account": "TeamBot", "per_developer_author": "own-bot"}},
    {"github": {"per_developer_author": "own-bot"}},
])
def test_a_bad_mode_value_raises_eagerly_with_or_without_a_working_token(cfg):
    rec = Rec()
    with pytest.raises(ai.BotAuthUnavailable):
        ai.run_gh_write(WRITE, config=cfg, runner=rec, token_runner=working_token)
    assert rec.calls == []
