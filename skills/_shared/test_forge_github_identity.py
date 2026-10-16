"""test_forge_github_identity.py — `forge_github` comment and label writes run as the bot.

design: review-proof-ambient-gh-identity, Task 1.4 (behaviours B1, B2, B3 at the forge writes)

`comment_post`, `comment_edit`, `label_add` and `label_remove` default `config=DISCOVER` and run
through `automation_identity.run_gh_write`: with a config naming a bot the child env carries
`GH_TOKEN=<its token>`, fetched per call; an unavailable token raises `BotAuthUnavailable` and
the runner never runs; an explicit `config=None` is today's one-argument `runner(argv)` call.
`pr_read` and `comment_list` stay reads: no config, no token. Hermetic: injected runners, or a
patched `subprocess.run`; no live `gh`, no network. Stdlib only.

Run with: pytest skills/_shared/test_forge_github_identity.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import automation_identity as ai  # noqa: E402
import forge_github  # noqa: E402
from forge import ForgeInfo  # noqa: E402

INFO = ForgeInfo("github", "github.com", "octo", "repo", "https://github.com",
                 "https://api.github.com", "")
BOT = "CurtisTheBot"
CFG = {"github": {"pr_author_account": BOT, "used_for": "all-prs"}}
TOKEN_ARGV = ["gh", "auth", "token", "--user", BOT]
BASE_ENV = {"PATH": "/bin"}
POSTED = json.dumps({"id": 99, "html_url": "https://github.com/octo/repo/issues/7#c-99"})

# op name -> (call, the argv it has always built); `rest` is the trailing call kwargs.
OPS = {
    "comment_post": (lambda **kw: forge_github.comment_post(INFO, 7, "a body", **kw),
                     ["gh", "api", "repos/octo/repo/issues/7/comments", "-f", "body=a body"]),
    "comment_edit": (lambda **kw: forge_github.comment_edit(INFO, 99, "new", **kw),
                     ["gh", "api", "-X", "PATCH", "repos/octo/repo/issues/comments/99",
                      "-f", "body=new"]),
    "label_add": (lambda **kw: forge_github.label_add(INFO, 7, "tp:x", **kw),
                  ["gh", "api", "repos/octo/repo/issues/7/labels", "-f", "labels[]=tp:x"]),
    "label_remove": (lambda **kw: forge_github.label_remove(INFO, 7, "tp:x", **kw),
                     ["gh", "api", "-X", "DELETE", "repos/octo/repo/issues/7/labels/tp%3Ax"]),
}


def _proc(argv, rc=0, out=POSTED, err=""):
    return subprocess.CompletedProcess(argv, rc, stdout=out, stderr=err)


class Rec:
    """A write runner `(argv, env=None)`: records `(argv, env)` per call."""

    def __init__(self):
        self.calls: list = []

    def __call__(self, argv, env=None):
        self.calls.append((list(argv), env))
        return _proc(argv)


class Tok:
    """A token runner: records each probe, answers a fake token (or fails)."""

    def __init__(self, fail=False):
        self.calls: list = []
        self.fail = fail

    def __call__(self, argv):
        self.calls.append(list(argv))
        return _proc(argv, rc=1, out="leaky-tok", err="no keyring") if self.fail \
            else _proc(argv, out="tok-bot\n")


class OneArg:
    """Today's runner shape: exactly `runner(argv)`."""

    def __init__(self):
        self.calls: list = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        return _proc(argv)


# --- B1: configured -> the bot's token in the child env ------------------------


@pytest.mark.parametrize("name", list(OPS))
def test_write_runs_as_the_bot_with_its_existing_argv(name):
    call, argv = OPS[name]
    rec, tok = Rec(), Tok()
    res = call(runner=rec, config=CFG, env=BASE_ENV, token_runner=tok)
    assert res.status == "ok"
    assert tok.calls == [TOKEN_ARGV]
    assert rec.calls == [(argv, {"PATH": "/bin", "GH_TOKEN": "tok-bot"})]
    assert "GH_TOKEN" not in BASE_ENV  # the caller's env is never mutated


def test_comment_post_still_returns_id_and_url():
    res = OPS["comment_post"][0](runner=Rec(), config=CFG, token_runner=Tok())
    assert res.payload == {"id": 99, "url": "https://github.com/octo/repo/issues/7#c-99"}
    assert "tok-bot" not in repr(res)


def test_each_write_fetches_the_token_again():
    tok = Tok()
    for name in ("label_add", "label_remove"):
        OPS[name][0](runner=Rec(), config=CFG, token_runner=tok)
    assert tok.calls == [TOKEN_ARGV, TOKEN_ARGV]


# --- B2: an unavailable token refuses before anything runs ---------------------


@pytest.mark.parametrize("name", list(OPS))
def test_unavailable_token_raises_and_never_runs(name):
    rec = Rec()
    with pytest.raises(ai.BotAuthUnavailable) as err:
        OPS[name][0](runner=rec, config=CFG, token_runner=Tok(fail=True))
    assert rec.calls == []
    assert BOT in str(err.value) and "leaky-tok" not in str(err.value)


# --- B3: no account -> exactly today's call ------------------------------------


@pytest.mark.parametrize("config", [None, {}, {"github": {"pr_author_account": None}}],
                         ids=["none", "empty", "no-account"])
@pytest.mark.parametrize("name", list(OPS))
def test_unconfigured_calls_the_one_arg_runner_as_today(name, config):
    call, argv = OPS[name]
    rec, tok = OneArg(), Tok()
    assert call(runner=rec, config=config, token_runner=tok).status == "ok"
    assert rec.calls == [argv]
    assert tok.calls == []


# --- the default runner --------------------------------------------------------


def _patch_run(monkeypatch):
    seen: list = []

    def fake(argv, **kwargs):
        seen.append((list(argv), kwargs))
        return _proc(argv)

    monkeypatch.setattr(subprocess, "run", fake)
    return seen


def test_default_runner_configured_passes_the_bot_env(monkeypatch):
    seen = _patch_run(monkeypatch)
    res = OPS["comment_post"][0](config=CFG, token_runner=Tok())
    assert res.status == "ok"
    (argv, kwargs), = seen
    assert argv == OPS["comment_post"][1]
    assert kwargs["env"]["GH_TOKEN"] == "tok-bot"
    assert kwargs["capture_output"] is True and kwargs["text"] is True


@pytest.mark.parametrize("name", list(OPS))
def test_default_runner_unconfigured_adds_no_env(name, monkeypatch):
    seen = _patch_run(monkeypatch)
    OPS[name][0](config=None)
    (argv, kwargs), = seen
    assert argv == OPS[name][1]
    assert "env" not in kwargs
    assert kwargs == {"capture_output": True, "text": True}


# --- discovery: the helper picks the identity, never the prompt -----------------


def _repo_naming_the_bot(tmp_path, monkeypatch):
    (tmp_path / ".three-pillars").mkdir()
    (tmp_path / ".three-pillars" / "config.json").write_text(json.dumps(CFG), encoding="utf-8")
    monkeypatch.setattr(ai, "_default_repo_root", lambda: tmp_path)


def test_default_config_is_discovered_from_the_repo(tmp_path, monkeypatch):
    _repo_naming_the_bot(tmp_path, monkeypatch)
    rec = Rec()
    assert OPS["label_add"][0](runner=rec, token_runner=Tok()).status == "ok"
    assert rec.calls[0][1]["GH_TOKEN"] == "tok-bot"


def test_default_config_without_a_repo_config_is_ambient():
    rec = OneArg()
    assert OPS["label_add"][0](runner=rec, token_runner=Tok()).status == "ok"
    assert rec.calls == [OPS["label_add"][1]]


# --- reads never fetch a token ---------------------------------------------------


def test_reads_never_call_the_token_runner_even_when_a_bot_is_configured(tmp_path, monkeypatch):
    _repo_naming_the_bot(tmp_path, monkeypatch)

    def poisoned(*_a, **_k):
        raise AssertionError("a read must not fetch a bot token")

    monkeypatch.setattr(ai, "bot_token", poisoned)
    calls: list = []
    view = json.dumps({"number": 7, "headRefName": "h", "headRefOid": "s",
                       "state": "OPEN", "url": "u"})

    def reads(argv):
        calls.append(list(argv))
        return _proc(argv, out=view if argv[1] == "pr" else "[[]]")

    assert forge_github.pr_read(INFO, 7, runner=reads).status == "ok"
    assert forge_github.comment_list(INFO, 7, runner=reads).status == "ok"
    assert [c[:3] for c in calls] == [["gh", "pr", "view"], ["gh", "api", "--paginate"]]
