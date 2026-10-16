"""test_converge_proof_identity.py — converge stops on a proof digest the gate would not trust (B4, B6).

design: review-proof-ambient-gh-identity, Task 1.7

`converge._finish_clean` posts the proof digest through `proof_post.post_proof_checked`, which
reads the digest's author back and compares it with the gate's trust set. An untrusted author
exits 3 with `reason == "proof-author-untrusted"` and `run_round.py` never runs. The same
post path carries the configured bot's token with no `GH_TOKEN` prefix in the calling shell.
Hermetic: posts, comments, git and run_round are seams; the B6 case patches `subprocess.run`
as a module attribute and answers `gh auth token --user CurtisTheBot` with the fake `tok-bot`.

Run with: pytest skills/tp-pr-iterate/scripts/test_converge_proof_identity.py -q
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import converge  # noqa: E402
import converge_cli  # noqa: E402
from automation_identity import BotAuthUnavailable  # noqa: E402

HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
PR = "https://github.com/o/r/pull/1"
CLEAN = {"converged": True, "terminal": "two-stable [code-review-only]"}


def _cfg(**github):
    cfg = {"review": {"expects_copilot": False, "automation_identities": ["tp-bot"]},
           "ci": {"expects_github_checks": False}}
    return {**cfg, "github": github} if github else cfg


def _run_git(args):
    if args[:2] == ["git", "rev-parse"]:
        return 0, HEAD + "\n", ""
    return (0, "3\t1\tfoo.py\n", "") if "--numstat" in args else (0, "", "")


class _Round:
    """A converge call with every external seam faked; records the post and run_round."""

    def __init__(self, tmp_path, *, author="tp-bot", post_ok=True, post_raises=None):
        self.tmp, self.author = tmp_path, author
        self.posts, self.rounds = [], []
        self.post_ok, self.post_raises = post_ok, post_raises
        self.out = io.StringIO()
        angle = tmp_path / "r1.txt"
        angle.write_text('```json\n{"findings": []}\n```\n', encoding="utf-8")
        self.angle = str(angle)

    def _post(self, url, body):
        if self.post_raises:
            raise self.post_raises
        self.posts.append(body)
        return self.post_ok

    def _comments(self, _url):
        return [{"author": self.author, "body": b} for b in self.posts]

    def _run_round(self, stdin):
        self.rounds.append(stdin)
        return dict(CLEAN)

    def go(self, config=None):
        rc = converge.converge(
            base="base000", head=HEAD, pr_url=PR, config=config or _cfg(),
            angle_files=[self.angle], proof_root=self.tmp / "proof",
            state_path=self.tmp / "state.json", post_fn=self._post,
            comments_fn=self._comments, self_login_fn=lambda: "tp-bot",
            run_round_fn=self._run_round, run_git=_run_git,
            runs_record_fn=lambda *a: None, out=self.out, err=io.StringIO())
        return rc, json.loads(self.out.getvalue().strip().splitlines()[-1])


def test_untrusted_digest_author_stops_before_run_round(tmp_path):  # B4
    r = _Round(tmp_path, author="CurtisThe")
    rc, result = r.go()
    assert rc == 3
    assert result["reason"] == "proof-author-untrusted"
    assert result["author"] == "CurtisThe"
    assert result["converged"] is False and result["proof_verified"] is False
    assert r.rounds == []                          # run_round.py never ran
    assert not (tmp_path / "state.json").exists()  # and state was never seeded


def test_trusted_digest_author_converges(tmp_path):
    r = _Round(tmp_path, author="tp-bot")
    rc, result = r.go()
    assert (rc, result["converged"]) == (0, True)
    assert len(r.rounds) == 1


def test_a_bot_configured_run_refuses_a_human_authored_digest(tmp_path):  # B4, B5
    cfg = _cfg(pr_author_account="CurtisTheBot")
    cfg["review"]["automation_identities"] = []
    human = _Round(tmp_path, author="tp-bot")  # the ambient login, not the bot
    rc, result = human.go(cfg)
    assert (rc, result["reason"]) == (3, "proof-author-untrusted")


def test_a_failed_post_keeps_the_post_failed_reason(tmp_path):
    r = _Round(tmp_path, post_ok=False)
    rc, result = r.go()
    assert (rc, result["reason"]) == (3, "post-failed")
    assert r.rounds == []


def test_an_unavailable_bot_stops_with_its_own_reason(tmp_path):  # B2
    r = _Round(tmp_path, post_raises=BotAuthUnavailable("bot 'CurtisTheBot' is not available"))
    rc, result = r.go()
    assert (rc, result["reason"]) == (3, "bot-auth-unavailable")
    assert r.rounds == []


def test_cli_posts_the_digest_as_the_bot_with_no_gh_token_prefix(tmp_path, monkeypatch):  # B6
    monkeypatch.delenv("GH_TOKEN", raising=False)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(_cfg(pr_author_account="CurtisTheBot")), encoding="utf-8")
    r = _Round(tmp_path, author="curtisthebot")
    posts, real_run = [], subprocess.run

    def fake_run(argv, **kw):
        if argv[:1] != ["gh"]:  # the CLI's default proof root asks git; that stays real
            return real_run(argv, **kw)
        if argv[:4] == ["gh", "auth", "token", "--user"]:
            assert argv[4] == "CurtisTheBot"
            return subprocess.CompletedProcess(argv, 0, stdout="tok-bot\n", stderr="")
        posts.append((list(argv), kw.get("env")))
        r.posts.append(next(a[5:] for a in argv if a.startswith("body=")))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    seams = dict(proof_root=tmp_path / "proof", state_path=tmp_path / "state.json",
                 comments_fn=r._comments, self_login_fn=lambda: "tp-bot",
                 run_round_fn=r._run_round, run_git=_run_git,
                 runs_record_fn=lambda *a: None, out=r.out, err=io.StringIO())
    rc = converge_cli.main(["--base", "base000", "--head", HEAD, "--pr-url", PR,
                            "--config", str(cfg), "--angle-file", r.angle], seams=seams)
    assert rc == 0, r.out.getvalue()
    assert len(posts) == 1 and posts[0][0][:2] == ["gh", "api"]
    env = posts[0][1]
    assert env is not None and "GH_TOKEN" in env, \
        "digest posted without the bot GH_TOKEN env (ambient login)"
    assert env["GH_TOKEN"] == "tok-bot", "digest posted with a token that is not the bot's"
    assert "GH_TOKEN" not in os.environ and "tok-bot" not in r.out.getvalue()
