"""test_finalizer_effects_identity.py — the finalizer's comment and label writes run as the bot.

design: review-proof-ambient-gh-identity, Task 1.5 (behaviours B1, B2, B3 at the finalizer writes)

`default_comment_fn` (`gh pr comment`) and `default_label_fn` (the REST label POST and the
`gh label create` path) default `config=DISCOVER` and run through
`automation_identity.run_gh_write`: with a config naming a bot the injected `runner` receives
the same argv as today plus `env["GH_TOKEN"]`, the token fetched per call. A token that cannot
be fetched keeps the fail-open contract: one printed line, `False`, no write recorded. An
explicit `config=None` is today's call (no `env` key). `default_pr_state_fn` stays a read.
Hermetic: injected runners; no live `gh`.

Run with: pytest skills/_shared/test_finalizer_effects_identity.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import automation_identity as ai  # noqa: E402
import finalizer_effects as fe  # noqa: E402

URL = "https://github.com/o/r/pull/7"
BOT = "CurtisTheBot"
CFG = {"github": {"pr_author_account": BOT, "used_for": "all-prs"}}
TOKEN_ARGV = ["gh", "auth", "token", "--user", BOT]
COMMENT_ARGV = ["gh", "pr", "comment", URL, "--body", "the note"]
ADD_ARGV = ["gh", "api", "--method", "POST", "repos/o/r/issues/7/labels", "--input", "-"]
CREATE_ARGV = ["gh", "label", "create", "tp:x", "--repo", "o/r"]
BODY = json.dumps({"labels": ["tp:x"]})
TODAY = {"cwd": None, "capture_output": True, "text": True, "timeout": 30}


class Rec:
    """A write runner: records `(argv, kwargs)` per call; answers the queued return codes."""

    def __init__(self, rcs=(), stderr="422 label does not exist"):
        self.calls: list = []
        self.rcs = list(rcs)
        self.stderr = stderr

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        rc = self.rcs.pop(0) if self.rcs else 0
        return subprocess.CompletedProcess(argv, rc, stdout="", stderr=self.stderr if rc else "")


class Tok:
    """A token runner for `gh auth token --user <bot>`."""

    def __init__(self, returncode=0, stdout="tok-bot\n"):
        self.calls: list = []
        self.returncode = returncode
        self.stdout = stdout

    def __call__(self, argv):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, self.returncode, stdout=self.stdout, stderr="")


def _name_the_bot(monkeypatch, tmp_path: Path) -> None:
    """Opt back in to discovery: `_default_repo_root` -> a tmp repo whose config names the bot."""
    cfg_dir = tmp_path / "botrepo" / ".three-pillars"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps(CFG))
    monkeypatch.setattr(ai, "_default_repo_root", lambda: tmp_path / "botrepo")


# ------------------------------------------------------------ B1: the writes run as the bot


def test_the_comment_runs_as_the_bot():
    rec, tok = Rec(), Tok()
    assert fe.default_comment_fn(URL, "the note", runner=rec, token_runner=tok, config=CFG) is True
    assert tok.calls == [TOKEN_ARGV]
    [(argv, kwargs)] = rec.calls
    assert argv == COMMENT_ARGV
    assert kwargs["env"]["GH_TOKEN"] == "tok-bot"
    assert {k: kwargs[k] for k in TODAY} == TODAY


def test_the_label_add_runs_as_the_bot():
    rec, tok = Rec(), Tok()
    assert fe.default_label_fn(URL, "tp:x", runner=rec, token_runner=tok, config=CFG) is True
    assert tok.calls == [TOKEN_ARGV]
    [(argv, kwargs)] = rec.calls
    assert argv == ADD_ARGV
    assert kwargs["env"]["GH_TOKEN"] == "tok-bot"
    assert kwargs["input"] == BODY
    assert {k: kwargs[k] for k in TODAY} == TODAY


def test_the_missing_label_path_creates_and_retries_as_the_bot():
    rec, tok = Rec(rcs=(1, 0, 0)), Tok()
    assert fe.default_label_fn(URL, "tp:x", runner=rec, token_runner=tok, config=CFG) is True
    assert [a for a, _ in rec.calls] == [ADD_ARGV, CREATE_ARGV, ADD_ARGV]
    assert all(k["env"]["GH_TOKEN"] == "tok-bot" for _, k in rec.calls)
    assert tok.calls == [TOKEN_ARGV] * 3  # fetched per write, never cached


def test_the_token_never_reaches_an_argv_or_the_output(capsys):
    rec, tok = Rec(rcs=(1,), stderr="boom"), Tok()
    fe.default_comment_fn(URL, "the note", runner=rec, token_runner=tok, config=CFG)
    assert all("tok-bot" not in " ".join(a) for a, _ in rec.calls)
    assert "tok-bot" not in capsys.readouterr().out


# ------------------------------------------------------------ B2: an unavailable bot never posts


@pytest.mark.parametrize("call", [
    lambda rec, tok: fe.default_comment_fn(URL, "the note", runner=rec, token_runner=tok, config=CFG),
    lambda rec, tok: fe.default_label_fn(URL, "tp:x", runner=rec, token_runner=tok, config=CFG),
])
def test_a_failing_token_prints_one_line_and_returns_false_with_no_write(call, capsys):
    rec, tok = Rec(), Tok(returncode=1, stdout="")
    assert call(rec, tok) is False
    assert rec.calls == []
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 1 and lines[0].startswith("finalizer-effects:")


# ------------------------------------------------------------ B3: unconfigured is today's call


@pytest.mark.parametrize("config", [None, {}, {"github": {"pr_author_account": None}}])
def test_an_unconfigured_comment_is_todays_call_exactly(config):
    rec, tok = Rec(), Tok()
    assert fe.default_comment_fn(URL, "the note", runner=rec, token_runner=tok, config=config)
    assert rec.calls == [(COMMENT_ARGV, TODAY)]
    assert tok.calls == []


@pytest.mark.parametrize("config", [None, {}])
def test_an_unconfigured_label_is_todays_calls_exactly(config):
    rec, tok = Rec(rcs=(1, 0, 0)), Tok()
    assert fe.default_label_fn(URL, "tp:x", runner=rec, token_runner=tok, config=config)
    assert rec.calls == [(ADD_ARGV, {**TODAY, "input": BODY}), (CREATE_ARGV, TODAY),
                         (ADD_ARGV, {**TODAY, "input": BODY})]
    assert tok.calls == []


def test_the_default_config_is_discovery_and_the_pinned_empty_repo_is_ambient():
    rec, tok = Rec(), Tok()
    assert fe.default_comment_fn(URL, "the note", runner=rec, token_runner=tok)
    assert rec.calls == [(COMMENT_ARGV, TODAY)] and tok.calls == []


def test_the_default_config_discovers_the_bot_from_the_repo(monkeypatch, tmp_path):
    _name_the_bot(monkeypatch, tmp_path)
    rec, tok = Rec(), Tok()
    assert fe.default_comment_fn(URL, "the note", runner=rec, token_runner=tok)
    assert fe.default_label_fn(URL, "tp:x", runner=rec, token_runner=tok)
    assert [a for a, _ in rec.calls] == [COMMENT_ARGV, ADD_ARGV]
    assert all(k["env"]["GH_TOKEN"] == "tok-bot" for _, k in rec.calls)


def test_the_state_read_stays_ambient_whatever_the_config(monkeypatch, tmp_path):
    _name_the_bot(monkeypatch, tmp_path)
    seen: list = []

    def runner(argv, **kwargs):
        seen.append(kwargs)
        out = json.dumps({"state": "OPEN", "headRefOid": "abc"})
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    assert fe.default_pr_state_fn(URL, runner=runner) == {"state": "OPEN", "headRefOid": "abc"}
    assert seen == [TODAY]
