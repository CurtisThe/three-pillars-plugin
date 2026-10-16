"""test_review_merge_identity.py — the proof digest posts through the identity core.

design: review-proof-ambient-gh-identity, Task 1.2 (behaviours B1, B2, B3 at the digest write)

`_default_comment_post` and `post_codereview_comment` default `config=DISCOVER`: the write runs
as the configured bot through `automation_identity.run_gh_write`. An explicit `config=None` is
today's ambient call, byte-identical. An unavailable bot never posts: `BotAuthUnavailable`
escapes `post_codereview_comment`'s fail-open wrapper (a digest that silently fell back to the
ambient login would re-create the self-approval trap). Hermetic: `subprocess.run` is patched.

Run with: pytest skills/tp-pr-iterate/scripts/test_review_merge_identity.py -q
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
import review_merge  # noqa: E402

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


# ------------------------------------------------------------ B1: the default poster, as the bot


def test_the_default_poster_runs_the_rest_write_as_the_bot():
    rec, tok = Rec(), Tok()
    ok = review_merge._default_comment_post(PR, "b", config=CFG, runner=rec, token_runner=tok)
    assert ok is True
    assert tok.calls == [["gh", "auth", "token", "--user", BOT]]
    assert len(rec.calls) == 1
    argv, kwargs = rec.calls[0]
    assert argv == POST_ARGV
    assert {k: kwargs[k] for k in TODAY} == TODAY
    assert kwargs["env"]["GH_TOKEN"] == "tok-bot"


def test_the_default_poster_reports_a_failed_write_as_false():
    class Failing(Rec):
        def __call__(self, argv, **kwargs):
            super().__call__(argv, **kwargs)
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")

    assert review_merge._default_comment_post(
        PR, "b", config=CFG, runner=Failing(), token_runner=Tok()
    ) is False


def test_post_codereview_comment_posts_the_digest_as_the_bot(gh):
    ok = review_merge.post_codereview_comment(PR, [], head_sha="a" * 40, config=CFG)
    assert ok is True
    assert gh.token_calls == [["gh", "auth", "token", "--user", BOT]]
    assert len(gh.posts) == 1
    argv, kwargs = gh.posts[0]
    assert argv[:3] == ["gh", "api", "repos/o/r/issues/7/comments"]
    assert kwargs["env"]["GH_TOKEN"] == "tok-bot"
    assert "tok-bot" not in "".join(argv)


def test_an_injected_post_fn_is_still_called_as_pr_url_body(gh):
    seen: list = []

    def post_fn(*args, **kwargs):
        seen.append((args, kwargs))
        return True

    assert review_merge.post_codereview_comment(
        PR, [], head_sha="a" * 40, post_fn=post_fn, config=CFG
    ) is True
    assert len(seen) == 1
    args, kwargs = seen[0]
    assert args[0] == PR and args[1].startswith("## ") and kwargs == {}
    assert gh.token_calls == [] and gh.posts == []  # the seam owns the write; no identity work


# ------------------------------------------------------------ B2: an unavailable bot never posts


def test_an_unavailable_bot_never_posts_the_default_poster():
    rec, tok = Rec(), Tok(returncode=1, stdout="")
    with pytest.raises(ai.BotAuthUnavailable):
        review_merge._default_comment_post(PR, "b", config=CFG, runner=rec, token_runner=tok)
    assert rec.calls == []


def test_an_unavailable_bot_escapes_the_fail_open_wrapper(monkeypatch):
    gh_down = FakeGh(token_rc=1)
    monkeypatch.setattr(subprocess, "run", gh_down)
    with pytest.raises(ai.BotAuthUnavailable) as err:
        review_merge.post_codereview_comment(PR, [], head_sha="a" * 40, config=CFG)
    assert gh_down.posts == []
    assert "tok-bot" not in str(err.value)


def test_a_non_auth_poster_failure_stays_fail_open():
    def boom(pr_url, body):
        raise RuntimeError("network exploded")

    assert review_merge.post_codereview_comment(PR, [], post_fn=boom, config=CFG) is False


# ------------------------------------------------------------ B3: unconfigured is byte-identical


def test_an_explicit_none_config_is_todays_call_exactly():
    rec, tok = Rec(), Tok()
    assert review_merge._default_comment_post(
        PR, "b", config=None, runner=rec, token_runner=tok
    ) is True
    assert rec.calls == [(POST_ARGV, TODAY)]  # no env key
    assert tok.calls == []


def test_post_codereview_comment_with_no_config_posts_ambient(gh):
    assert review_merge.post_codereview_comment(PR, [], config=None) is True
    assert gh.token_calls == []
    assert len(gh.posts) == 1
    assert gh.posts[0][1] == TODAY


def test_the_shipped_fixture_makes_a_bare_call_ambient(gh):
    """No opt-in: `skills/conftest.py` pinned discovery to an empty dir, so the default is {}."""
    assert review_merge.post_codereview_comment(PR, []) is True
    assert gh.token_calls == []
    assert gh.posts[0][1] == TODAY


# ------------------------------------------------------------ discovery: no kwarg, still the bot


def test_with_no_config_kwarg_the_digest_posts_as_the_bot_the_repo_names(
    tmp_path, monkeypatch, gh
):
    repo = tmp_path / "repo"
    (repo / ".three-pillars").mkdir(parents=True)
    (repo / ".three-pillars" / "config.json").write_text(json.dumps(CFG), encoding="utf-8")
    monkeypatch.setattr(ai, "_default_repo_root", lambda: repo)
    assert review_merge.post_codereview_comment(PR, [], head_sha="a" * 40) is True
    assert gh.token_calls == [["gh", "auth", "token", "--user", BOT]]
    assert gh.posts[0][1]["env"]["GH_TOKEN"] == "tok-bot"


# ------------------------------------------------------------ the script-path import


def test_the_script_imports_the_identity_core_from_its_own_directory():
    """A fresh interpreter started in the script dir resolves `automation_identity` (the shim)."""
    code = "import review_merge, automation_identity; print(review_merge.__name__)"
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
