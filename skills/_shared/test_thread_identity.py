"""test_thread_identity.py — thread replies and resolves post through the identity core.

design: review-proof-ambient-gh-identity, Task 1.3 (behaviours B1, B2, B3 at the thread writes)

`reply_to_thread` (REST) and `resolve_thread` (GraphQL `resolveReviewThread`) default
`config=DISCOVER` and run as the configured bot via `automation_identity.run_gh_write`; an
explicit `config=None` is today's ambient call. An unavailable bot raises `BotAuthUnavailable`
(never the fail-open `False`) and nothing posts. `dispose_threads` forwards its `config` to both
writes, and the dispose-only branch of `run_round.py` passes the round's config. Reads are
unchanged. Hermetic: an injected runner, or a patched `subprocess.run`; no live `gh`.

Run with: pytest skills/_shared/test_thread_identity.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "tp-pr-iterate" / "scripts"
for _p in (HERE, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import automation_identity as ai  # noqa: E402
import thread_dispose  # noqa: E402
import thread_resolver  # noqa: E402

PR = "https://github.com/o/r/pull/7"
BOT = "CurtisTheBot"
CFG = {"github": {"pr_author_account": BOT, "used_for": "all-prs"}}
TOKEN_ARGV = ["gh", "auth", "token", "--user", BOT]
REPLY_ARGV = ["gh", "api", "repos/o/r/pulls/7/comments/123/replies", "-f", "body=ok"]
RESOLVE_ARGV = [
    "gh", "api", "graphql",
    "-f", f"query={thread_resolver._RESOLVE_MUTATION}",
    "-F", "threadId=T_1",
]
TODAY = {"capture_output": True, "text": True, "check": False}
COPILOT = "copilot-pull-request-reviewer"


class Rec:
    """A write runner: records (argv, kwargs) per call, answers `returncode`."""

    def __init__(self, returncode=0):
        self.calls: list = []
        self.returncode = returncode

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        return subprocess.CompletedProcess(argv, self.returncode, stdout="", stderr="")


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

    def __init__(self):
        self.token_calls: list = []
        self.posts: list = []

    def __call__(self, argv, **kwargs):
        if list(argv[:3]) == ["gh", "auth", "token"]:
            self.token_calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout="tok-bot\n", stderr="")
        self.posts.append((list(argv), kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


def _name_the_bot(monkeypatch, tmp_path: Path, text: "str | None" = None) -> None:
    """Opt back in to discovery: point `_default_repo_root` at a tmp repo whose config names the bot."""
    cfg_dir = tmp_path / "botrepo" / ".three-pillars"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(text if text is not None else json.dumps(CFG))
    monkeypatch.setattr(ai, "_default_repo_root", lambda: tmp_path / "botrepo")


# ------------------------------------------------------------ B1: both writes run as the bot


def test_the_reply_runs_as_the_bot():
    rec, tok = Rec(), Tok()
    assert thread_resolver.reply_to_thread(
        PR, 123, "ok", config=CFG, runner=rec, token_runner=tok
    ) is True
    assert tok.calls == [TOKEN_ARGV]
    assert len(rec.calls) == 1
    argv, kwargs = rec.calls[0]
    assert argv == REPLY_ARGV
    assert {k: kwargs[k] for k in TODAY} == TODAY
    assert kwargs["env"]["GH_TOKEN"] == "tok-bot"


def test_the_resolve_runs_as_the_bot():
    rec, tok = Rec(), Tok()
    assert thread_resolver.resolve_thread(
        "T_1", config=CFG, runner=rec, token_runner=tok
    ) is True
    assert tok.calls == [TOKEN_ARGV]
    assert len(rec.calls) == 1
    argv, kwargs = rec.calls[0]
    assert argv == RESOLVE_ARGV
    assert {k: kwargs[k] for k in TODAY} == TODAY
    assert kwargs["env"]["GH_TOKEN"] == "tok-bot"


def test_a_failed_write_as_the_bot_is_still_false_and_leaks_nothing():
    before = os.environ.get("GH_TOKEN")
    rec = Rec(returncode=1)
    assert thread_resolver.reply_to_thread(
        PR, 123, "ok", config=CFG, runner=rec, token_runner=Tok()
    ) is False
    assert thread_resolver.resolve_thread(
        "T_1", config=CFG, runner=rec, token_runner=Tok()
    ) is False
    assert os.environ.get("GH_TOKEN") == before  # the parent environment is never mutated
    assert all("tok-bot" not in " ".join(argv) for argv, _ in rec.calls)


# ------------------------------------------------------------ B2: an unavailable bot never posts


@pytest.mark.parametrize("write", ["reply", "resolve"])
def test_an_unavailable_bot_raises_and_nothing_posts(write):
    rec, tok = Rec(), Tok(returncode=1, stdout="tok-bot\n")
    with pytest.raises(ai.BotAuthUnavailable) as exc:
        if write == "reply":
            thread_resolver.reply_to_thread(PR, 123, "ok", config=CFG, runner=rec, token_runner=tok)
        else:
            thread_resolver.resolve_thread("T_1", config=CFG, runner=rec, token_runner=tok)
    assert rec.calls == []
    assert tok.calls == [TOKEN_ARGV]
    assert "tok-bot" not in str(exc.value)


# ------------------------------------------------------------ B3: no account = byte-identical


@pytest.mark.parametrize("cfg", [None, {}, {"github": {"pr_author_account": None}}])
def test_without_an_account_the_writes_are_todays_calls(cfg):
    rec, tok = Rec(), Tok()
    assert thread_resolver.reply_to_thread(
        PR, 123, "ok", config=cfg, runner=rec, token_runner=tok
    ) is True
    assert thread_resolver.resolve_thread(
        "T_1", config=cfg, runner=rec, token_runner=tok
    ) is True
    assert [argv for argv, _ in rec.calls] == [REPLY_ARGV, RESOLVE_ARGV]
    assert all(kwargs == TODAY for _, kwargs in rec.calls)  # no `env` key added
    assert tok.calls == []


# ------------------------------------------------------------ default: discovery picks the bot


def test_the_default_config_discovers_the_bot(monkeypatch, tmp_path):
    _name_the_bot(monkeypatch, tmp_path)
    rec, tok = Rec(), Tok()
    assert thread_resolver.reply_to_thread(PR, 123, "ok", runner=rec, token_runner=tok) is True
    assert thread_resolver.resolve_thread("T_1", runner=rec, token_runner=tok) is True
    assert [argv for argv, _ in rec.calls] == [REPLY_ARGV, RESOLVE_ARGV]
    assert all(kwargs["env"]["GH_TOKEN"] == "tok-bot" for _, kwargs in rec.calls)
    assert tok.calls == [TOKEN_ARGV, TOKEN_ARGV]  # fetched per call, never cached


def test_the_default_config_with_no_repo_config_is_ambient():
    rec, tok = Rec(), Tok()
    assert thread_resolver.reply_to_thread(PR, 123, "ok", runner=rec, token_runner=tok) is True
    assert rec.calls == [(REPLY_ARGV, TODAY)] and tok.calls == []


def test_an_unparseable_repo_config_raises_from_the_default(monkeypatch, tmp_path):
    _name_the_bot(monkeypatch, tmp_path, text="{not json")
    rec = Rec()
    with pytest.raises(ai.BotAuthUnavailable):
        thread_resolver.reply_to_thread(PR, 123, "ok", runner=rec, token_runner=Tok())
    with pytest.raises(ai.BotAuthUnavailable):
        thread_resolver.resolve_thread("T_1", runner=rec, token_runner=Tok())
    assert rec.calls == []


# ------------------------------------------------------------ reads stay on the ambient login


def test_the_reads_never_use_the_bot(monkeypatch, tmp_path):
    _name_the_bot(monkeypatch, tmp_path)
    seen: list = []

    def fake_run(argv, **kwargs):
        seen.append((list(argv), kwargs))
        out = json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}})
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert thread_resolver.list_review_threads(PR) == []
    assert thread_resolver.list_review_threads_strict(PR) == []
    assert thread_dispose._thread_has_automation_reply("T_1") is False
    assert len(seen) == 3
    assert all("env" not in kwargs for _, kwargs in seen)
    assert all(argv[:3] != ["gh", "auth", "token"] for argv, _ in seen)


# ------------------------------------------------------------ dispose_threads forwards its config


def _stub_reads(monkeypatch) -> None:
    """One open Copilot thread; every read and guard is stubbed, so only the writes remain."""
    thread = {"thread_id": "T_1", "is_resolved": False, "comment_id": 123,
              "path": "x.py", "body": "nit", "author": COPILOT}
    monkeypatch.setattr(thread_resolver, "list_review_threads", lambda pr_url: [thread])
    monkeypatch.setattr(thread_dispose, "_thread_has_automation_reply", lambda tid: False)
    monkeypatch.setattr(
        thread_dispose.thread_dispose_verify, "check_before_dispose",
        lambda t, base_dir=None: "normal",
    )


def _dispose_world(monkeypatch):
    """The stubbed reads plus recorders for both writes. Returns (replies, resolves)."""
    _stub_reads(monkeypatch)
    replies: list = []
    resolves: list = []

    def reply(pr_url, cid, body, **kwargs):
        replies.append((pr_url, cid, kwargs))
        return True

    def resolve(tid, **kwargs):
        resolves.append((tid, kwargs))
        return True

    monkeypatch.setattr(thread_resolver, "reply_to_thread", reply)
    monkeypatch.setattr(thread_resolver, "resolve_thread", resolve)
    return replies, resolves


EMPTY = {"fixes_applied": [], "fixes_deferred": []}


def test_dispose_forwards_its_config_to_both_writes(monkeypatch):
    replies, resolves = _dispose_world(monkeypatch)
    result = thread_dispose.dispose_threads(PR, EMPTY, config=CFG)
    assert result["replied"] == ["T_1"] and result["resolved"] == ["T_1"]
    assert replies[0][2]["config"] is CFG
    assert resolves[0][1]["config"] is CFG


def test_dispose_without_a_config_forwards_the_discover_default(monkeypatch):
    replies, resolves = _dispose_world(monkeypatch)
    thread_dispose.dispose_threads(PR, EMPTY)
    assert replies[0][2]["config"] is ai.DISCOVER
    assert resolves[0][1]["config"] is ai.DISCOVER


# ------------------------------------------------------------ run_round's dispose-only branch


@pytest.fixture
def dispose_only(monkeypatch, capsys):
    """`run(payload)` runs `run_round._handle_dispose_only` with GitHub faked; returns (rc, FakeGh)."""
    import run_round

    fake = FakeGh()
    _stub_reads(monkeypatch)
    monkeypatch.setattr(subprocess, "run", fake)

    def run(payload: dict) -> "tuple[int, FakeGh]":
        rc = run_round._handle_dispose_only({"pr_url": PR, "dispose_only": True, **payload})
        capsys.readouterr()
        return rc, fake

    return run


def test_dispose_only_passes_the_payload_config(dispose_only):
    rc, fake = dispose_only({"config": CFG})
    assert rc == 0
    assert fake.token_calls == [TOKEN_ARGV, TOKEN_ARGV]  # the reply and the resolve
    assert len(fake.posts) == 2
    assert all(kwargs["env"]["GH_TOKEN"] == "tok-bot" for _, kwargs in fake.posts)


def test_dispose_only_with_a_null_payload_config_is_ambient(dispose_only):
    rc, fake = dispose_only({"config": None})
    assert rc == 0
    assert fake.token_calls == []
    assert len(fake.posts) == 2
    assert all("env" not in kwargs for _, kwargs in fake.posts)


def test_dispose_only_without_a_payload_config_reads_the_repo_config(dispose_only, monkeypatch, tmp_path):
    _name_the_bot(monkeypatch, tmp_path)
    rc, fake = dispose_only({})
    assert rc == 0
    assert fake.token_calls == [TOKEN_ARGV, TOKEN_ARGV]
    assert all(kwargs["env"]["GH_TOKEN"] == "tok-bot" for _, kwargs in fake.posts)


def test_dispose_only_with_an_unparseable_repo_config_escalates_and_posts_nothing(
    dispose_only, monkeypatch, tmp_path
):
    _name_the_bot(monkeypatch, tmp_path, text="{not json")
    rc, fake = dispose_only({})
    assert rc == 2
    assert fake.posts == [] and fake.token_calls == []
