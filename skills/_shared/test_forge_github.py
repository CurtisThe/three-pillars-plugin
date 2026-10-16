"""Tests for forge_github.py: the GitHub backend on today's paths.

design: forge-interface (Task 1.2). Hermetic: one recording fake `runner` (argv ->
CompletedProcess-like) and a fake `token_runner`; no real `gh`, no network. The
PR-create assertions are DIFFERENTIAL — the wrapper and `github_pr_author.create_pr`
are both driven through the SAME recorder and must produce the same argv and child
env, so the chokepoint stays the only builder of `gh pr create` argv. The REST
shapes are EXAMPLES taken from today's callers (`cert_comment`, `review_merge`,
`label_manager`).
Run with: python3 -m pytest skills/_shared/test_forge_github.py -q -n0
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forge_github  # noqa: E402
from forge import ForgeInfo  # noqa: E402
from github_pr_author import BotAuthUnavailable, create_pr  # noqa: E402

INFO = ForgeInfo("github", "github.com", "octo", "repo", "https://github.com",
                 "https://api.github.com", "")
BASE_ENV = {"PATH": "/usr/bin", "HOME": "/home/op"}
GH_ARGS = ["--title", "T", "--body", "B", "--base", "master"]


class FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class Recorder:
    """One fake runner for both the wrapper and the chokepoint.

    Records every argv and the `env` keyword it was called with. Answers from a
    scripted queue whose LAST entry repeats, so a two-call test can script one
    shared outcome. `missing=True` raises what a machine without `gh` raises.
    """

    def __init__(self, *procs: FakeProc, missing: bool = False) -> None:
        self.calls: list[list] = []
        self.envs: list = []
        self.procs = list(procs) or [FakeProc()]
        self.missing = missing

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        self.envs.append(kwargs.get("env"))
        if self.missing:
            raise FileNotFoundError(2, "No such file or directory: 'gh'")
        return self.procs[-1] if len(self.procs) == 1 else self.procs.pop(0)


def token_runner(account: str = "bot") -> Recorder:
    """`gh auth token --user <account>` answering with a token."""
    return Recorder(FakeProc(0, "s3cret-token\n", ""))


# --- pr_create: the chokepoint stays the only argv builder -------------------

def test_pr_create_plain_path_argv_and_env():
    """No bot configured -> exactly `gh pr create <gh_args>`, env unchanged."""
    rec = Recorder(FakeProc(0, "https://github.com/octo/repo/pull/7\n"))
    res = forge_github.pr_create(INFO, GH_ARGS, {}, "manual", runner=rec, env=BASE_ENV)
    assert res.status == "ok"
    assert rec.calls == [["gh", "pr", "create", *GH_ARGS]]
    assert rec.envs == [BASE_ENV]  # the same mapping, nothing added
    assert rec.envs[0] is BASE_ENV or dict(rec.envs[0]) == BASE_ENV


def test_pr_create_bot_path_equals_the_chokepoint():
    """Differential: wrapper and `create_pr` produce the same argv + child env."""
    rec = Recorder(FakeProc(0, "https://github.com/octo/repo/pull/7\n"))
    config = {"github": {"pr_author_account": "bot", "review_requests": ["human"]}}
    res = forge_github.pr_create(INFO, GH_ARGS, config, "manual", runner=rec,
                                 env=BASE_ENV, token_runner=token_runner())
    rc = create_pr(GH_ARGS, config, "manual", runner=rec, env=BASE_ENV,
                   token_runner=token_runner())
    assert res.status == "ok"
    assert rc == 0
    assert len(rec.calls) == 2
    assert rec.calls[0] == rec.calls[1]  # the chokepoint's argv, not a copy built here
    assert rec.envs[0] == rec.envs[1]
    assert rec.envs[0]["GH_TOKEN"] == "s3cret-token"
    assert "GH_TOKEN" not in BASE_ENV  # the caller's env object is never mutated


def test_pr_create_propagates_bot_auth_unavailable():
    """A bot account that cannot be honored is fail-loud, never a silent fallback."""
    rec = Recorder(FakeProc(0, ""))
    with pytest.raises(BotAuthUnavailable):
        forge_github.pr_create(INFO, GH_ARGS, {"github": {"pr_author_account": "bot"}},
                               "manual", runner=rec, env=BASE_ENV,
                               token_runner=Recorder(FakeProc(1, "", "no keyring")))
    assert rec.calls == []  # no ambient `gh pr create` after a failed token probe


def test_pr_create_nonzero_rc_degrades_one_line():
    rec = Recorder(FakeProc(4, "", "could not compute commits\nsecond line\n"))
    res = forge_github.pr_create(INFO, GH_ARGS, {}, "manual", runner=rec, env=BASE_ENV)
    assert res.status == "degraded"
    assert res.payload == {}
    assert res.line == res.line.strip() and "\n" not in res.line
    assert "gh pr create" in res.line and "4" in res.line


def test_pr_create_without_gh_names_install():
    rec = Recorder(missing=True)
    res = forge_github.pr_create(INFO, GH_ARGS, {}, "manual", runner=rec, env=BASE_ENV)
    assert res.status == "degraded"
    assert "install gh" in res.line


# --- pr_read -----------------------------------------------------------------

def test_pr_read_parses_the_gh_json():
    rec = Recorder(FakeProc(0, '{"number": 7, "headRefName": "tp/x", "headRefOid": "abc123",'
                              ' "state": "OPEN", "url": "https://github.com/octo/repo/pull/7"}'))
    res = forge_github.pr_read(INFO, 7, runner=rec)
    assert rec.calls == [["gh", "pr", "view", "7", "--json",
                          "number,headRefName,headRefOid,state,url"]]
    assert res.status == "ok"
    assert res.payload == {"number": 7, "head": "tp/x", "head_sha": "abc123", "state": "OPEN",
                           "url": "https://github.com/octo/repo/pull/7"}


def test_pr_read_failure_carries_the_first_stderr_line():
    rec = Recorder(FakeProc(1, "", "unknown revision\nno such PR\n"))
    res = forge_github.pr_read(INFO, 7, runner=rec)
    assert res.status == "degraded"
    assert res.line == "unknown revision"


# --- the REST ops: today's shapes -------------------------------------------

def test_comment_post_argv_and_payload():
    rec = Recorder(FakeProc(0, '{"id": 99, "html_url":'
                               ' "https://github.com/octo/repo/issues/7#issuecomment-99"}'))
    res = forge_github.comment_post(INFO, 7, "a body", runner=rec)
    assert rec.calls == [["gh", "api", "repos/octo/repo/issues/7/comments",
                          "-f", "body=a body"]]
    assert res.status == "ok"
    assert res.payload == {"id": 99,
                           "url": "https://github.com/octo/repo/issues/7#issuecomment-99"}


def test_comment_edit_argv():
    rec = Recorder(FakeProc(0, '{"id": 99}'))
    res = forge_github.comment_edit(INFO, 99, "new body", runner=rec)
    assert rec.calls == [["gh", "api", "-X", "PATCH",
                          "repos/octo/repo/issues/comments/99", "-f", "body=new body"]]
    assert res.status == "ok"


def test_label_add_argv():
    rec = Recorder(FakeProc(0, "[]"))
    res = forge_github.label_add(INFO, 7, "tp:needs-human-attention", runner=rec)
    assert rec.calls == [["gh", "api", "repos/octo/repo/issues/7/labels", "-f",
                          "labels[]=tp:needs-human-attention"]]
    assert res.status == "ok"


def test_label_remove_argv_encodes_like_todays_caller():
    """`label_manager` URL-encodes the label (tp: labels carry a colon)."""
    rec = Recorder(FakeProc(0, ""))
    res = forge_github.label_remove(INFO, 7, "tp:needs-human-attention", runner=rec)
    assert rec.calls == [["gh", "api", "-X", "DELETE",
                          "repos/octo/repo/issues/7/labels"
                          "/tp%3Aneeds-human-attention"]]
    assert res.status == "ok"


# --- every REST op degrades the same way ------------------------------------

def test_rest_without_gh_names_install():
    rec = Recorder(missing=True)
    for res in (forge_github.comment_post(INFO, 7, "b", runner=rec),
                forge_github.pr_read(INFO, 7, runner=rec)):
        assert res.status == "degraded"
        assert "install gh" in res.line


def test_rest_nonzero_rc_carries_first_stderr_line():
    rec = Recorder(FakeProc(1, "", "gh: Bad credentials (HTTP 401)\n"
                                   "something else\n"))
    res = forge_github.comment_post(INFO, 7, "b", runner=rec)
    assert res.status == "degraded"
    assert res.line == "gh: Bad credentials (HTTP 401)"


def test_rest_unparsable_json_degrades_one_line():
    rec = Recorder(FakeProc(0, "not json"))
    res = forge_github.comment_post(INFO, 7, "b", runner=rec)
    assert res.status == "degraded"
    assert res.payload == {}
    assert res.line and "\n" not in res.line
