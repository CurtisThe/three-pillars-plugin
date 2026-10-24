"""test_per_developer_author.py — reading the PR author for `per_developer_author: self`.

design: per-developer-automation-account, Task 1.3 (behaviours 6, 8)

`login_from_head` pulls the author login from the human-approval head fetch payload and refuses
an automation author; `pr_author_fn_for` is a fresh memoized closure that refuses a fork PR and any
fetch failure; `self_posted_detail` is the fixed roster text. Hermetic: `head_fn` is a fake.

Run with: pytest skills/_shared/test_per_developer_author.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import per_developer_author as pda  # noqa: E402


def test_login_from_head_returns_the_author_login():
    assert pda.login_from_head({"author": {"login": "Alice"}}) == "Alice"


@pytest.mark.parametrize("payload", [{}, {"author": None}, {"author": {"login": ""}}, "x", None])
def test_login_from_head_is_none_without_a_usable_author(payload):
    assert pda.login_from_head(payload) is None


@pytest.mark.parametrize("author", [
    {"login": "ci-runner", "is_bot": True},
    {"login": "app/ci"},
    {"login": "renovate[bot]"},
    {"login": "ghost"},
    {"login": "Copilot"},
    {"login": "github-actions"},
])
def test_login_from_head_is_none_for_an_automation_author(author):
    assert pda.login_from_head({"author": author}) is None


def _head_fn(payload):
    calls = []

    def f(url):
        calls.append(url)
        if isinstance(payload, Exception):
            raise payload
        return payload

    f.calls = calls
    return f


def test_pr_author_fn_memoizes_per_closure_and_never_across_closures():
    f = _head_fn({"author": {"login": "Alice"}, "isCrossRepository": False})
    g = pda.pr_author_fn_for("U", head_fn=f)
    assert g() == "Alice" and g() == "Alice"
    assert f.calls == ["U"]
    pda.pr_author_fn_for("U", head_fn=f)()
    assert f.calls == ["U", "U"]


def test_pr_author_fn_is_none_when_the_fetch_raises():
    g = pda.pr_author_fn_for("U", head_fn=_head_fn(RuntimeError("boom")))
    assert g() is None


@pytest.mark.parametrize("payload", [
    {"author": {"login": "Alice"}, "isCrossRepository": True},
    {"author": {"login": "Alice"}},
])
def test_pr_author_fn_is_none_for_a_fork_pr_or_an_unknown_shape(payload):
    assert pda.pr_author_fn_for("U", head_fn=_head_fn(payload))() is None


def test_self_posted_detail_is_the_fixed_roster_text():
    assert pda.self_posted_detail("Alice") == (
        "self-attested digest by Alice (per_developer_author: self)")
