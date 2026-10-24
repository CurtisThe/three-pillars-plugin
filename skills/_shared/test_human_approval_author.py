"""test_human_approval_author.py — `human_approved` never counts the PR author's own review.

design: per-developer-automation-account, Task 1.3 (behaviour 9, decision D4)

The PR author joins the automation set explicitly, under both `per_developer_author` settings and
even on a fork PR (the fork refusal is for the digest-trust arm only). A head payload with no
`author` gives today's result. Hermetic: injected runners, no live gh.

Run with: pytest skills/_shared/test_human_approval_author.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from human_approval import human_approved_on_head  # noqa: E402

URL = "https://github.com/example/repo/pull/7"
H = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
CFGS = [{}, {"github": {"per_developer_author": "self"}}]


def _review(login, state="APPROVED", at="2026-06-08T14:00:00Z"):
    return {"user": {"login": login, "type": "User"}, "state": state,
            "submitted_at": at, "commit_id": H}


def _runners(reviews, head_extra=None):
    head = {"headRefOid": H, "commits": [], **(head_extra or {})}
    return {"self_login_fn": lambda: "teambot", "head_fn": lambda u: head,
            "reviews_fn": lambda u: reviews}


AUTHOR = {"author": {"login": "alice"}}


@pytest.mark.parametrize("cfg", CFGS)
def test_the_authors_own_approval_never_counts(cfg):
    r = _runners([_review("alice")], AUTHOR)
    assert human_approved_on_head(URL, runners=r, config=cfg) is False


@pytest.mark.parametrize("cfg", CFGS)
def test_the_authors_own_approval_never_counts_on_a_fork_pr(cfg):
    r = _runners([_review("alice")], {**AUTHOR, "isCrossRepository": True})
    assert human_approved_on_head(URL, runners=r, config=cfg) is False


@pytest.mark.parametrize("cfg", CFGS)
def test_a_second_humans_approval_counts(cfg):
    r = _runners([_review("alice"), _review("bob", at="2026-06-08T15:00:00Z")], AUTHOR)
    assert human_approved_on_head(URL, runners=r, config=cfg) is True


def test_a_head_without_an_author_gives_todays_result():
    assert human_approved_on_head(URL, runners=_runners([_review("alice")]), config={}) is True


@pytest.mark.parametrize("cfg", CFGS)
def test_a_later_author_comment_does_not_replace_another_humans_approval(cfg):
    reviews = [_review("bob", at="2026-06-08T14:00:00Z"),
               _review("alice", state="COMMENTED", at="2026-06-08T15:00:00Z")]
    r = _runners(reviews, AUTHOR)
    assert human_approved_on_head(URL, runners=r, config=cfg) is True
