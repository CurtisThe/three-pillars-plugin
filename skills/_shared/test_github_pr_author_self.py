"""test_github_pr_author_self.py — `create_pr` under `github.per_developer_author: self`.

design: per-developer-automation-account, Task 1.2 (behaviours 2, 4, 5)

Under `self`, a bot token that cannot be fetched gives a plain ambient `gh pr create` (no
`--reviewer`) plus a distinct `!! per_developer_author: self` warning, never a refusal. A present
token keeps today's bot-authored create; `off` still raises before the create runner runs; a bad
mode value raises eagerly. Hermetic: the token, login and create runners are fakes.

Run with: pytest skills/_shared/test_github_pr_author_self.py -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import automation_identity as ai  # noqa: E402
import github_pr_author as gpa  # noqa: E402

CFG = {"github": {"pr_author_account": "TeamBot", "review_requests": ["lead"],
                  "per_developer_author": "self"}}


class Spy:
    """A create runner: records (argv, env) per call."""

    def __init__(self):
        self.calls: list = []

    def __call__(self, argv, env=None):
        self.calls.append((list(argv), env))
        return subprocess.CompletedProcess(argv, 0)


def failing_token(argv):
    return subprocess.CompletedProcess(argv, 1, stdout="SECRET", stderr="")


def working_token(argv):
    return subprocess.CompletedProcess(argv, 0, stdout="tok\n", stderr="")


@pytest.fixture(autouse=True)
def _alice(monkeypatch):
    ai._reset_ambient_login()
    monkeypatch.setattr(
        ai, "_login_runner",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout="alice\n", stderr=""))
    yield
    ai._reset_ambient_login()


def _without(cfg, key):
    github = {k: v for k, v in cfg["github"].items() if k != key}
    return {"github": github}


def test_a_missing_token_under_self_runs_a_plain_ambient_create_with_no_reviewer():
    spy = Spy()
    rc = gpa.create_pr(["--title", "t"], CFG, "manual", runner=spy, env={"P": "1"},
                       token_runner=failing_token)
    assert rc == 0
    assert spy.calls == [(["gh", "pr", "create", "--title", "t"], {"P": "1"})]


def test_a_working_token_keeps_the_bot_authored_create_with_reviewers():
    spy = Spy()
    gpa.create_pr(["--title", "t"], CFG, "manual", runner=spy, env={}, token_runner=working_token)
    (argv, env), = spy.calls
    assert argv[-2:] == ["--reviewer", "lead"]
    assert env["GH_TOKEN"] == "tok"


def test_without_the_key_a_missing_token_raises_and_the_create_never_runs():
    spy = Spy()
    with pytest.raises(ai.BotAuthUnavailable):
        gpa.create_pr(["--title", "t"], _without(CFG, "per_developer_author"), "manual",
                      runner=spy, env={}, token_runner=failing_token)
    assert spy.calls == []


@pytest.mark.parametrize("cfg", [
    {"github": {"pr_author_account": "TeamBot", "per_developer_author": "own-bot"}},
    {"github": {"per_developer_author": "own-bot"}},
])
def test_a_bad_mode_value_raises_eagerly_and_the_create_never_runs(cfg):
    spy = Spy()
    with pytest.raises(ai.BotAuthUnavailable):
        gpa.create_pr(["--title", "t"], cfg, "manual", runner=spy, env={},
                      token_runner=working_token)
    assert spy.calls == []


def test_the_fallback_prints_a_distinct_warning_naming_the_login_and_the_bot(capsys):
    gpa.create_pr(["--title", "t"], CFG, "manual", runner=Spy(), env={},
                  token_runner=failing_token)
    err = capsys.readouterr().err
    warning = [ln for ln in err.splitlines() if ln.startswith("!! per_developer_author: self")]
    assert len(warning) == 1
    assert "alice" in warning[0] and "TeamBot" in warning[0]
    assert "approve" in warning[0]
    assert "SECRET" not in err
    # distinct from the run_gh_write notice line, which does not start with the `!!` marker
    assert any(ln.startswith("per_developer_author: self") for ln in err.splitlines())
