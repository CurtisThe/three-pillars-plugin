"""test_label_manager_identity.py — label writes post through the identity core.

design: review-proof-ambient-gh-identity, Task 1.5 (behaviours B1, B2, B3 at the label writes)

`ensure_pr_label` (REST add, `gh label create`, the retried add) and `remove_pr_label` (the
labels DELETE) default `config=DISCOVER` and run as the configured bot through
`automation_identity.run_gh_write`; the `gh pr view` reads stay on the ambient login. An
unavailable bot raises `BotAuthUnavailable` from `ensure_pr_label` and never posts;
`remove_pr_label` keeps its never-raise contract (`False`). An explicit `config=None` is
today's ambient call. Hermetic: `label_manager.subprocess.run` is patched to a recorder that
also answers the token probe; no live `gh`, no network.

Run with: pytest skills/tp-pr-fix/scripts/test_label_manager_identity.py -q
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent.parent / "_shared"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import automation_identity as ai  # noqa: E402
import label_manager  # noqa: E402

PR = "https://github.com/example/repo/pull/42"
LABEL = "tp:fix-applied"
BOT = "CurtisTheBot"
CFG = {"github": {"pr_author_account": BOT, "used_for": "all-prs"}}
TOKEN_ARGV = ["gh", "auth", "token", "--user", BOT]
BODY = json.dumps({"labels": [LABEL]})
ADD_ARGV = ["gh", "api", "--method", "POST", "repos/example/repo/issues/42/labels",
            "--input", "-"]
CREATE_ARGV = ["gh", "label", "create", LABEL]
DELETE_ARGV = ["gh", "api", "--method", "DELETE",
               "repos/example/repo/issues/42/labels/tp%3Afix-applied"]
TODAY = {"capture_output": True, "text": True, "check": False}


def _proc(argv, rc=0, out="", err=""):
    return subprocess.CompletedProcess(argv, rc, stdout=out, stderr=err)


class FakeGh:
    """A stand-in for `subprocess.run`: answers the token probe and `gh pr view`; records every call."""

    def __init__(self, labels=(), add_rcs=(0,), token_rc=0):
        self.labels = list(labels)
        self.add_rcs = list(add_rcs)
        self.token_rc = token_rc
        self.calls: list = []

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append((argv, kwargs))
        if argv[:3] == ["gh", "auth", "token"]:
            return _proc(argv, self.token_rc, "tok-bot\n" if self.token_rc == 0 else "")
        if argv[:3] == ["gh", "pr", "view"]:
            return _proc(argv, 0, json.dumps({"labels": [{"name": n} for n in self.labels]}))
        if argv[:2] == ["gh", "label"]:
            return _proc(argv)
        if "POST" in argv:
            rc = self.add_rcs.pop(0) if self.add_rcs else 0
            return _proc(argv, rc, "", "422 label does not exist" if rc else "")
        return _proc(argv)

    def tokens(self):
        return [a for a, _ in self.calls if a[:3] == ["gh", "auth", "token"]]

    def writes(self):
        return [(a, k) for a, k in self.calls
                if a[:3] not in (["gh", "auth", "token"], ["gh", "pr", "view"])]

    def views(self):
        return [(a, k) for a, k in self.calls if a[:3] == ["gh", "pr", "view"]]


@pytest.fixture
def gh(monkeypatch):
    fake = FakeGh()
    monkeypatch.setattr(label_manager.subprocess, "run", fake)
    return fake


def _name_the_bot(monkeypatch, tmp_path: Path) -> None:
    """Opt back in to discovery: `_default_repo_root` -> a tmp repo whose config names the bot."""
    cfg_dir = tmp_path / "botrepo" / ".three-pillars"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps(CFG))
    monkeypatch.setattr(ai, "_default_repo_root", lambda: tmp_path / "botrepo")


# ------------------------------------------------------------ B1: the writes run as the bot


def test_the_add_runs_as_the_bot_and_the_view_stays_ambient(gh):
    label_manager.ensure_pr_label(PR, LABEL, config=CFG)
    assert gh.tokens() == [TOKEN_ARGV]
    [(argv, kwargs)] = gh.writes()
    assert argv == ADD_ARGV
    assert kwargs["env"]["GH_TOKEN"] == "tok-bot"
    assert kwargs["input"] == BODY
    assert {k: kwargs[k] for k in TODAY} == TODAY
    [(view_argv, view_kwargs)] = gh.views()
    assert view_argv == ["gh", "pr", "view", PR, "--json", "labels"]
    assert "env" not in view_kwargs


def test_the_missing_label_path_creates_and_retries_as_the_bot(monkeypatch):
    fake = FakeGh(add_rcs=(1, 0))
    monkeypatch.setattr(label_manager.subprocess, "run", fake)
    label_manager.ensure_pr_label(PR, LABEL, config=CFG)
    assert [a for a, _ in fake.writes()] == [ADD_ARGV, CREATE_ARGV, ADD_ARGV]
    assert all(k["env"]["GH_TOKEN"] == "tok-bot" for _, k in fake.writes())
    assert len(fake.tokens()) == 3  # fetched per write call, never cached
    assert all("env" not in k for _, k in fake.views())


def test_an_already_present_label_posts_nothing_and_fetches_no_token(monkeypatch):
    fake = FakeGh(labels=[LABEL])
    monkeypatch.setattr(label_manager.subprocess, "run", fake)
    label_manager.ensure_pr_label(PR, LABEL, config=CFG)
    assert fake.writes() == [] and fake.tokens() == []


def test_the_delete_runs_as_the_bot_and_the_view_stays_ambient(monkeypatch):
    fake = FakeGh(labels=[LABEL])
    monkeypatch.setattr(label_manager.subprocess, "run", fake)
    assert label_manager.remove_pr_label(PR, LABEL, config=CFG) is True
    [(argv, kwargs)] = fake.writes()
    assert argv == DELETE_ARGV
    assert kwargs["env"]["GH_TOKEN"] == "tok-bot"
    assert {k: kwargs[k] for k in TODAY} == TODAY
    assert all("env" not in k for _, k in fake.views())


def test_the_bot_token_never_reaches_an_argv(gh):
    label_manager.ensure_pr_label(PR, LABEL, config=CFG)
    assert all("tok-bot" not in " ".join(a) for a, _ in gh.calls)


# ------------------------------------------------------------ B2: an unavailable bot never posts


def test_ensure_raises_and_posts_nothing_when_the_token_is_unavailable(monkeypatch):
    fake = FakeGh(token_rc=1)
    monkeypatch.setattr(label_manager.subprocess, "run", fake)
    with pytest.raises(ai.BotAuthUnavailable):
        label_manager.ensure_pr_label(PR, LABEL, config=CFG)
    assert fake.writes() == []


def test_remove_keeps_its_never_raise_contract_when_the_token_is_unavailable(monkeypatch, capsys):
    fake = FakeGh(labels=[LABEL], token_rc=1)
    monkeypatch.setattr(label_manager.subprocess, "run", fake)
    assert label_manager.remove_pr_label(PR, LABEL, config=CFG) is False
    assert fake.writes() == []
    assert "bot auth unavailable: label write skipped" in capsys.readouterr().err, \
        "the swallowed BotAuthUnavailable must leave one stderr line"


# ------------------------------------------------------------ B3: unconfigured is today's call


@pytest.mark.parametrize("config", [None, {}, {"github": {"pr_author_account": None}}])
def test_an_unconfigured_ensure_is_todays_calls_exactly(monkeypatch, config):
    fake = FakeGh(add_rcs=(1, 0))
    monkeypatch.setattr(label_manager.subprocess, "run", fake)
    label_manager.ensure_pr_label(PR, LABEL, config=config)
    assert fake.tokens() == []
    assert [a for a, _ in fake.calls] == [
        ["gh", "pr", "view", PR, "--json", "labels"], ADD_ARGV, CREATE_ARGV, ADD_ARGV]
    assert all("env" not in k for _, k in fake.calls)
    assert fake.calls[1][1] == {"input": BODY, **TODAY}
    assert fake.calls[2][1] == TODAY


def test_an_unconfigured_remove_is_todays_calls_exactly(monkeypatch):
    fake = FakeGh(labels=[LABEL])
    monkeypatch.setattr(label_manager.subprocess, "run", fake)
    assert label_manager.remove_pr_label(PR, LABEL, config=None) is True
    assert fake.tokens() == []
    assert fake.writes() == [(DELETE_ARGV, TODAY)]


def test_the_default_config_is_discovery_and_the_pinned_empty_repo_is_ambient(gh):
    label_manager.ensure_pr_label(PR, LABEL)
    assert gh.tokens() == []
    assert all("env" not in k for _, k in gh.calls)


def test_the_default_config_discovers_the_bot_from_the_repo(gh, monkeypatch, tmp_path):
    _name_the_bot(monkeypatch, tmp_path)
    label_manager.ensure_pr_label(PR, LABEL)
    [(argv, kwargs)] = gh.writes()
    assert argv == ADD_ARGV and kwargs["env"]["GH_TOKEN"] == "tok-bot"


def test_the_default_config_discovers_the_bot_for_remove_too(monkeypatch, tmp_path):
    fake = FakeGh(labels=[LABEL])
    monkeypatch.setattr(label_manager.subprocess, "run", fake)
    _name_the_bot(monkeypatch, tmp_path)
    assert label_manager.remove_pr_label(PR, LABEL) is True
    [(argv, kwargs)] = fake.writes()
    assert argv == DELETE_ARGV and kwargs["env"]["GH_TOKEN"] == "tok-bot"
