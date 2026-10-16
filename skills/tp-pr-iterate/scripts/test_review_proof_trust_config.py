"""test_review_proof_trust_config.py — the gate's trusted digest authors read config (B3, B5).

design: review-proof-ambient-gh-identity, Task 1.6

With `github.pr_author_account` set, `proof_comment_on_head` trusts that account (plus
`review.automation_identities`) and never asks for the ambient login, so the same comment
list gives the same verdict under any token. A digest authored by the ambient human login is
not proof once a bot is configured, even when `self_login_fn` returns that login. With no
account the trust set is today's (self login plus extras). A malformed `github` block fails
closed: False, never a raise. Hermetic: comments and the self login are fakes, and the
digests are built with the real `format_proof_digest`.

Run with: pytest skills/tp-pr-iterate/scripts/test_review_proof_trust_config.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import review_proof  # noqa: E402

PR = "https://github.com/o/r/pull/9"
HEAD = "abc123def4567890abc123def4567890abc12345"
BOT_CFG = {"github": {"pr_author_account": "CurtisTheBot"},
           "review": {"automation_identities": ["curtisthebot"]}}


def _digest(head=HEAD):
    meta = {"base": "base000", "head": head, "files_changed": 3,
            "insertions": 5, "deletions": 1, "degraded": False, "reason": None}
    return review_proof.format_proof_digest(meta, [("correctness", 0)])


def _comments(author, head=HEAD):
    return lambda _url: [{"author": author, "body": _digest(head)}]


def _boom():
    raise AssertionError("gh api user must not run when a bot is configured")


@pytest.mark.parametrize("ambient", ["CurtisThe", "someone-else"])
def test_bot_authored_digest_passes_under_any_ambient_login(ambient):  # B5
    got = review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=_comments("curtisthebot"), config=BOT_CFG,
        self_login_fn=lambda: ambient)
    assert got is True


ACCOUNT_ONLY_CFG = {"github": {"pr_author_account": "CurtisTheBot"}}  # bot not in automation_identities


@pytest.mark.parametrize("ambient", ["CurtisThe", "someone-else"])
def test_bot_digest_passes_on_pr_author_account_alone(ambient):  # B5: the trust source is the account
    got = review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=_comments("curtisthebot"), config=ACCOUNT_ONLY_CFG,
        self_login_fn=lambda: ambient)
    assert got is True, "bot digest rejected: trust must come from pr_author_account"


def test_bot_authored_digest_passes_without_reading_the_login():
    got = review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=_comments("CurtisTheBot"), config=BOT_CFG, self_login_fn=_boom)
    assert got is True


@pytest.mark.parametrize("ambient", ["CurtisThe", "someone-else"])
def test_human_authored_digest_is_not_proof_when_a_bot_is_configured(ambient):  # B5
    got = review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=_comments("CurtisThe"), config=BOT_CFG,
        self_login_fn=lambda: ambient)
    assert got is False


def test_bot_digest_for_another_head_is_not_proof():
    got = review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=_comments("curtisthebot", head="f" * 40), config=BOT_CFG,
        self_login_fn=_boom)
    assert got is False


def test_no_account_trusts_the_self_login_as_today():  # B3
    cfg = {"review": {"automation_identities": []}}
    ok = review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=_comments("CurtisThe"), config=cfg,
        self_login_fn=lambda: "CurtisThe")
    other = review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=_comments("CurtisThe"), config=cfg,
        self_login_fn=lambda: "someone-else")
    assert (ok, other) == (True, False)


@pytest.mark.parametrize("github", ["x", {"pr_author_account": ""}, {"pr_author_account": 5}])
def test_malformed_github_block_fails_closed_without_raising(github):
    got = review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=_comments("curtisthebot"), config={"github": github},
        self_login_fn=lambda: "curtisthebot")
    assert got is False


def test_private_helper_delegates_to_the_core():
    import automation_identity as ai
    got = review_proof._trusted_digest_authors(BOT_CFG, _boom)
    assert got == ai.trusted_digest_authors(BOT_CFG, _boom) == frozenset({"curtisthebot"})
