"""test_automation_identity_trust.py — the gate's digest trust set (core side).

design: review-proof-ambient-gh-identity, Task 1.6 (behaviours B3, B5)

`trusted_digest_authors(config, self_login_fn)` is the set of lowercased logins whose posted
proof digests count. With `github.pr_author_account` set it is that account plus
`review.automation_identities`, and the ambient login is never asked: the same comments give
the same verdict under any token. With no account it is today's set: the self login plus the
extras. An unresolvable self login only shrinks the set (fail-closed). Hermetic: every
`self_login_fn` is a fake, so no live `gh` is involved.

Run with: pytest skills/_shared/test_automation_identity_trust.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import automation_identity as ai  # noqa: E402

BOT_CFG = {"github": {"pr_author_account": "CurtisTheBot"},
           "review": {"automation_identities": ["curtisthebot"]}}


def _boom():
    raise AssertionError("the ambient login must not be read when a bot is configured")


def _raises():
    raise RuntimeError("gh api user failed")


def test_bot_configured_trusts_account_and_extras_without_self_login():
    got = ai.trusted_digest_authors(BOT_CFG, self_login_fn=_boom)
    assert got == frozenset({"curtisthebot"})


def test_bot_configured_unions_extras_lowercased():
    cfg = {"github": {"pr_author_account": "CurtisTheBot"},
           "review": {"automation_identities": ["Other-Bot", "", 7]}}
    got = ai.trusted_digest_authors(cfg, self_login_fn=_boom)
    assert got == frozenset({"curtisthebot", "other-bot"})


def test_autonomous_only_account_still_trusted():
    cfg = {"github": {"pr_author_account": "CurtisTheBot", "used_for": "autonomous-only"}}
    assert ai.trusted_digest_authors(cfg, self_login_fn=_boom) == frozenset({"curtisthebot"})


def test_no_account_trusts_self_login():  # B3
    assert ai.trusted_digest_authors({}, lambda: "CurtisThe") == frozenset({"curtisthe"})


def test_no_account_unions_self_login_and_extras():
    cfg = {"review": {"automation_identities": ["Ci-Bot"]}}
    got = ai.trusted_digest_authors(cfg, lambda: "CurtisThe")
    assert got == frozenset({"curtisthe", "ci-bot"})


def test_null_account_is_the_unconfigured_set():
    cfg = {"github": {"pr_author_account": None}}
    assert ai.trusted_digest_authors(cfg, lambda: "CurtisThe") == frozenset({"curtisthe"})


@pytest.mark.parametrize("cfg", [{}, {"review": {"automation_identities": ["ci-bot"]}}])
def test_unresolvable_self_login_shrinks_to_extras(cfg):
    extras = frozenset(
        s.lower() for s in (cfg.get("review") or {}).get("automation_identities", []))
    assert ai.trusted_digest_authors(cfg, _raises) == extras
    assert ai.trusted_digest_authors(cfg, lambda: None) == extras


def test_non_dict_config_is_the_unconfigured_set():
    assert ai.trusted_digest_authors(None, lambda: "CurtisThe") == frozenset({"curtisthe"})


@pytest.mark.parametrize("github", ["x", {"pr_author_account": ""}, {"pr_author_account": 5}])
def test_malformed_github_block_raises_and_never_reads_the_login(github):
    with pytest.raises(ai.BotAuthUnavailable):
        ai.trusted_digest_authors({"github": github}, self_login_fn=_boom)
