"""test_cert_comment_identity.py — the base-sync cert comment posts through the identity core.

design: review-proof-ambient-gh-identity, Task 1.2 (behaviours B1, B2, B3 at the cert write)

`_default_run_gh` and `post_cert_comment` default `config=DISCOVER`: the write runs as the
configured bot through `automation_identity.run_gh_write`. An explicit `config=None` is today's
ambient call, byte-identical. `post_cert_comment` NEVER raises (the breadcrumb is audit-only):
an unavailable bot returns False and the write runner is never called. Hermetic:
`subprocess.run` is patched.

Run with: pytest skills/tp-merge-from-main/scripts/test_cert_comment_identity.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SHARED = HERE.parents[1] / "_shared"
for _p in (HERE, SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import automation_identity as ai  # noqa: E402
import cert_comment  # noqa: E402

PR = "https://github.com/o/r/pull/7"
POST_ARGV = ["gh", "api", "repos/o/r/issues/7/comments", "-f", "body=b"]
BOT = "CurtisTheBot"
CFG = {"github": {"pr_author_account": BOT, "used_for": "all-prs"}}
TODAY = {"capture_output": True, "text": True, "check": False}


class Rec:
    """A write runner: records (argv, kwargs) per call, answers success."""

    def __init__(self):
        self.calls: list = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


class Tok:
    """A token runner for `gh auth token --user <bot>`."""

    def __init__(self, returncode=0, stdout="tok-bot\n"):
        self.calls: list = []
        self.returncode = returncode
        self.stdout = stdout

    def __call__(self, argv):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, self.returncode, stdout=self.stdout, stderr="")


class FakeGh:
    """A stand-in for `subprocess.run`: answers the token probe, records every other call."""

    def __init__(self, token_rc=0):
        self.token_rc = token_rc
        self.token_calls: list = []
        self.posts: list = []

    def __call__(self, argv, **kwargs):
        if list(argv[:3]) == ["gh", "auth", "token"]:
            self.token_calls.append(list(argv))
            out = "tok-bot\n" if self.token_rc == 0 else ""
            return subprocess.CompletedProcess(argv, self.token_rc, stdout=out, stderr="")
        self.posts.append((list(argv), kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


@pytest.fixture
def gh(monkeypatch):
    fake = FakeGh()
    monkeypatch.setattr(subprocess, "run", fake)
    return fake


# ------------------------------------------------------------ B1: the cert write, as the bot


def test_the_default_runner_posts_the_rest_write_as_the_bot():
    rec, tok = Rec(), Tok()
    ok = cert_comment._default_run_gh(PR, "b", config=CFG, runner=rec, token_runner=tok)
    assert ok is True
    assert tok.calls == [["gh", "auth", "token", "--user", BOT]]
    assert len(rec.calls) == 1
    argv, kwargs = rec.calls[0]
    assert argv == POST_ARGV
    assert {k: kwargs[k] for k in TODAY} == TODAY
    assert kwargs["env"]["GH_TOKEN"] == "tok-bot"


def test_post_cert_comment_posts_as_the_bot(gh):
    assert cert_comment.post_cert_comment(PR, "b", config=CFG) is True
    assert gh.token_calls == [["gh", "auth", "token", "--user", BOT]]
    assert len(gh.posts) == 1
    argv, kwargs = gh.posts[0]
    assert argv == POST_ARGV
    assert kwargs["env"]["GH_TOKEN"] == "tok-bot"
    assert "tok-bot" not in "".join(argv)


def test_an_injected_run_gh_is_still_called_as_pr_url_body(gh):
    seen: list = []

    def run_gh(*args, **kwargs):
        seen.append((args, kwargs))
        return True

    assert cert_comment.post_cert_comment(PR, "b", run_gh=run_gh, config=CFG) is True
    assert seen == [((PR, "b"), {})]
    assert gh.token_calls == [] and gh.posts == []  # the seam owns the write; no identity work


# ------------------------------------------------------------ B2: an unavailable bot never posts


def test_an_unavailable_bot_never_posts_the_default_runner():
    rec, tok = Rec(), Tok(returncode=1, stdout="")
    with pytest.raises(ai.BotAuthUnavailable):
        cert_comment._default_run_gh(PR, "b", config=CFG, runner=rec, token_runner=tok)
    assert rec.calls == []


def test_an_unavailable_bot_returns_false_and_never_raises(monkeypatch):
    gh_down = FakeGh(token_rc=1)
    monkeypatch.setattr(subprocess, "run", gh_down)
    assert cert_comment.post_cert_comment(PR, "b", config=CFG) is False
    assert gh_down.posts == []


# ------------------------------------------------------------ B3: unconfigured is byte-identical


def test_an_explicit_none_config_is_todays_call_exactly():
    rec, tok = Rec(), Tok()
    assert cert_comment._default_run_gh(
        PR, "b", config=None, runner=rec, token_runner=tok
    ) is True
    assert rec.calls == [(POST_ARGV, TODAY)]  # no env key
    assert tok.calls == []


def test_post_cert_comment_with_no_config_posts_ambient(gh):
    assert cert_comment.post_cert_comment(PR, "b", config=None) is True
    assert gh.token_calls == []
    assert gh.posts == [(POST_ARGV, TODAY)]


def test_the_shipped_fixture_makes_a_bare_call_ambient(gh):
    """No opt-in: `skills/conftest.py` pinned discovery to an empty dir, so the default is {}."""
    assert cert_comment.post_cert_comment(PR, "b") is True
    assert gh.token_calls == []
    assert gh.posts == [(POST_ARGV, TODAY)]


# ------------------------------------------------------------ discovery: no kwarg, still the bot


def test_with_no_config_kwarg_the_cert_posts_as_the_bot_the_repo_names(tmp_path, monkeypatch, gh):
    repo = tmp_path / "repo"
    (repo / ".three-pillars").mkdir(parents=True)
    (repo / ".three-pillars" / "config.json").write_text(json.dumps(CFG), encoding="utf-8")
    monkeypatch.setattr(ai, "_default_repo_root", lambda: repo)
    assert cert_comment.post_cert_comment(PR, "b") is True
    assert gh.token_calls == [["gh", "auth", "token", "--user", BOT]]
    assert gh.posts[0][1]["env"]["GH_TOKEN"] == "tok-bot"


# ------------------------------------------------------------ the script-path import


def test_the_script_imports_the_identity_core_from_its_own_directory():
    """A fresh interpreter started in the script dir resolves `automation_identity` (the shim)."""
    code = "import cert_comment, automation_identity; print(cert_comment.__name__)"
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
