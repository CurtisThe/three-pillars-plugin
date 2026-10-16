"""test_proof_post.py — post the proof digest, then read its author back (B2, B4, B6).

design: review-proof-ambient-gh-identity, Task 1.7

`post_proof_checked` posts through `review_merge.post_codereview_comment`, reads the PR
comments back with the gate's own reader and checks the digest's author against the trust set
the gate computes (`review_proof._trusted_digest_authors`). An untrusted author is reported
as `proof-author-untrusted` during the round, not at land time. A read-back that cannot
find a digest is `ok` with no author (the converge oracle still fails closed on a missing
proof). Hermetic: posts and comments are fakes; the one default-path test patches
`subprocess.run` and never reaches a real `gh`. Digests are built with the real
`format_proof_digest`. Fake token: `tok-bot`.

Run with: pytest skills/tp-pr-iterate/scripts/test_proof_post.py -q
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import review_proof  # noqa: E402  (puts skills/_shared on sys.path)
from automation_identity import BotAuthUnavailable  # noqa: E402
import proof_post  # noqa: E402

PR = "https://github.com/o/r/pull/9"
HEAD = "abc123def4567890abc123def4567890abc12345"
BOT_CFG = {"github": {"pr_author_account": "CurtisTheBot"},
           "review": {"automation_identities": ["curtisthebot"]}}


def _digest(head=HEAD, degraded=False):
    meta = {"base": "base000", "head": head, "files_changed": 3, "insertions": 5,
            "deletions": 1, "degraded": degraded, "reason": "empty-diff" if degraded else None}
    return review_proof.format_proof_digest(meta, [("correctness", 0)])


def _body(digest=None):
    return "review summary\n" + (digest if digest is not None else _digest())


def _comments(*pairs):
    items = [{"author": a, "body": b} for a, b in pairs]
    return lambda _url: items


def _ok_post(url, body):
    return True


def _check(comments_fn, config=BOT_CFG, **kw):
    return proof_post.post_proof_checked(
        PR, [], head=HEAD, digest=_digest(), config=config,
        post_fn=kw.pop("post_fn", _ok_post), comments_fn=comments_fn, **kw)


def test_untrusted_read_back_author_is_reported():  # B4
    got = _check(_comments(("CurtisThe", _body())))
    assert got["status"] == "proof-author-untrusted"
    assert got["author"] == "CurtisThe"


def test_trusted_read_back_author_is_ok():  # B4
    got = _check(_comments(("curtisthebot", _body())))
    assert (got["status"], got["author"]) == ("ok", "curtisthebot")


def test_the_last_digest_on_the_head_decides():
    after_human = _check(_comments(("curtisthebot", _body()), ("CurtisThe", _body())))
    after_bot = _check(_comments(("CurtisThe", _body()), ("curtisthebot", _body())))
    assert after_human["status"] == "proof-author-untrusted"
    assert after_bot["status"] == "ok"


@pytest.mark.parametrize("items", [
    [("CurtisThe", _body(_digest(head="f" * 40)))],      # digest for another head
    [("CurtisThe", _body(_digest(degraded=True)))],      # DEGRADED digest is not proof
    [("CurtisThe", "no digest here")],
    [],
])
def test_no_digest_on_the_head_is_ok_without_an_author(items):
    got = _check(_comments(*items))
    assert (got["status"], got["author"]) == ("ok", None)


@pytest.mark.parametrize("comments_fn", [
    lambda _u: (_ for _ in ()).throw(RuntimeError("gh pr view failed")),
    lambda _u: "not-a-list",
    lambda _u: None,
])
def test_unreadable_read_back_is_ok_without_an_author(comments_fn):
    got = _check(comments_fn)
    assert (got["status"], got["author"]) == ("ok", None)


def test_failed_post_is_post_failed_and_reads_nothing():
    def never(_u):
        raise AssertionError("comments must not be read after a failed post")
    got = _check(never, post_fn=lambda u, b: False)
    assert got["status"] == "post-failed"


def test_bot_auth_unavailable_reads_nothing_and_leaks_no_token():
    def deny(url, body):
        raise BotAuthUnavailable("bot account 'CurtisTheBot' is not available")

    def never(_u):
        raise AssertionError("comments must not be read when the bot is unavailable")

    got = _check(never, post_fn=deny)
    assert got["status"] == "bot-auth-unavailable"
    assert "tok-bot" not in json.dumps(got)


def test_default_path_without_a_token_posts_nothing(monkeypatch):
    calls = []

    def fake_run(argv, **kw):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="no such account")

    monkeypatch.setattr(subprocess, "run", fake_run)
    got = proof_post.post_proof_checked(PR, [], head=HEAD, digest=_digest(), config=BOT_CFG,
                                        comments_fn=lambda _u: [])
    assert got["status"] == "bot-auth-unavailable"
    assert calls == [["gh", "auth", "token", "--user", "CurtisTheBot"]]  # no write ran


def test_the_digest_rides_in_the_posted_body():
    posts = []
    _check(_comments(("curtisthebot", _body())), post_fn=lambda u, b: posts.append((u, b)) or True)
    assert posts[0][0] == PR and _digest() in posts[0][1]


def test_a_configured_bot_never_asks_for_the_ambient_login():
    def boom():
        raise AssertionError("gh api user must not run when a bot is configured")
    got = _check(_comments(("curtisthebot", _body())), self_login_fn=boom)
    assert got["status"] == "ok"


def test_no_account_trusts_the_self_login_as_the_gate_does():  # B3
    cfg = {"review": {"automation_identities": []}}
    mine = _check(_comments(("CurtisThe", _body())), config=cfg, self_login_fn=lambda: "CurtisThe")
    other = _check(_comments(("CurtisThe", _body())), config=cfg, self_login_fn=lambda: "someone")
    assert (mine["status"], other["status"]) == ("ok", "proof-author-untrusted")


# ---------- CLI ----------


def _files(tmp_path, config=BOT_CFG, findings=None, digest=None):
    f, g, c = tmp_path / "findings.json", tmp_path / "digest.txt", tmp_path / "config.json"
    f.write_text(json.dumps([] if findings is None else findings), encoding="utf-8")
    g.write_text((digest if digest is not None else _digest()) + "\n", encoding="utf-8")
    c.write_text(config if isinstance(config, str) else json.dumps(config), encoding="utf-8")
    return ["--pr-url", PR, "--head", HEAD, "--findings", str(f),
            "--digest-file", str(g), "--config", str(c)]


def _run_main(argv, capsys, **seams):
    rc = proof_post.main(argv, seams=seams)
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    return rc, json.loads(lines[0])


def test_cli_prints_one_json_line_and_exits_zero_on_ok(tmp_path, capsys):
    rc, got = _run_main(_files(tmp_path), capsys, post_fn=_ok_post,
                        comments_fn=_comments(("curtisthebot", _body())))
    assert (rc, got["status"]) == (0, "ok")


def test_cli_exits_three_on_an_untrusted_author(tmp_path, capsys):
    rc, got = _run_main(_files(tmp_path), capsys, post_fn=_ok_post,
                        comments_fn=_comments(("CurtisThe", _body())))
    assert (rc, got["status"], got["author"]) == (3, "proof-author-untrusted", "CurtisThe")


def test_cli_requires_a_config(tmp_path):
    argv = _files(tmp_path)
    i = argv.index("--config")
    with pytest.raises(SystemExit):
        proof_post.main(argv[:i] + argv[i + 2:])


def test_cli_config_load_error_is_bot_auth_unavailable_and_posts_nothing(tmp_path, capsys):
    def never(url, body):
        raise AssertionError("nothing may post on a config load error")
    rc, got = _run_main(_files(tmp_path, config="{ not json"), capsys, post_fn=never)
    assert (rc, got["status"]) == (3, "bot-auth-unavailable")


def test_cli_posts_as_the_bot_with_no_gh_token_prefix(tmp_path, monkeypatch, capsys):  # B6
    monkeypatch.delenv("GH_TOKEN", raising=False)
    writes = []

    def fake_run(argv, **kw):
        if argv[:4] == ["gh", "auth", "token", "--user"]:
            return subprocess.CompletedProcess(argv, 0, stdout="tok-bot\n", stderr="")
        writes.append((list(argv), kw.get("env")))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    rc, got = _run_main(_files(tmp_path), capsys,
                        comments_fn=_comments(("curtisthebot", _body())))
    assert (rc, got["status"]) == (0, "ok")
    assert len(writes) == 1 and writes[0][0][:2] == ["gh", "api"]
    assert writes[0][1]["GH_TOKEN"] == "tok-bot"
    assert "GH_TOKEN" not in os.environ and "tok-bot" not in json.dumps(got)
