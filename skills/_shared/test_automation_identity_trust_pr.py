"""test_automation_identity_trust_pr.py — the digest trust set gains the PR author under `self`.

design: per-developer-automation-account, Task 1.4 (behaviours 6, 7)

`trusted_digest_authors(config, self_login_fn, pr_author_fn=None)` adds the lowercased PR author
only when the gate-side mode (`_gate_mode`) is `self`; the author lookup is lazy and any error
leaves the set as it was (fail closed). An invalid mode value reads as `off` and never raises.
`trusted_digest_authors_for_pr` binds the lookup to a PR url and refuses a fork PR. Hermetic.

Run with: pytest skills/_shared/test_automation_identity_trust_pr.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import automation_identity as ai  # noqa: E402

REVIEW = {"review": {"automation_identities": ["teambot"]}}
OFF = {"github": {"pr_author_account": "TeamBot"}, **REVIEW}
SELF = {"github": {"pr_author_account": "TeamBot", "per_developer_author": "self"}, **REVIEW}
BAD = {"github": {"pr_author_account": "TeamBot", "per_developer_author": "own-bot"}, **REVIEW}


def _boom():
    raise AssertionError("must not be called")


def _raises():
    raise RuntimeError("lookup failed")


def test_self_adds_the_lowercased_pr_author():
    got = ai.trusted_digest_authors(SELF, self_login_fn=_boom, pr_author_fn=lambda: "Alice")
    assert got == {"teambot", "alice"}


def _recording(author="Alice"):
    calls = []

    def lookup():
        calls.append(1)
        return author

    lookup.calls = calls
    return lookup


def test_off_never_calls_the_author_lookup():
    lookup = _recording()
    got = ai.trusted_digest_authors(OFF, self_login_fn=_boom, pr_author_fn=lookup)
    assert got == {"teambot"}
    assert lookup.calls == []


@pytest.mark.parametrize("lookup", [_raises, lambda: None])
def test_self_with_a_failing_or_empty_lookup_leaves_the_set_unchanged(lookup):
    got = ai.trusted_digest_authors(SELF, self_login_fn=_boom, pr_author_fn=lookup)
    assert got == {"teambot"}


def test_an_invalid_mode_reads_as_off_without_raising_or_looking_up():
    lookup = _recording()
    got = ai.trusted_digest_authors(BAD, self_login_fn=_boom, pr_author_fn=lookup)
    assert got == {"teambot"}
    assert lookup.calls == []


def test_for_pr_binds_the_lookup_to_the_head_fetch():
    head = {"author": {"login": "Alice"}, "isCrossRepository": False}
    got = ai.trusted_digest_authors_for_pr(SELF, "U", _boom, head_fn=lambda u: head)
    assert "alice" in got


def test_for_pr_never_trusts_the_author_of_a_fork_pr():
    head = {"author": {"login": "Alice"}, "isCrossRepository": True}
    got = ai.trusted_digest_authors_for_pr(SELF, "U", _boom, head_fn=lambda u: head)
    assert got == {"teambot"}


def test_for_pr_under_off_never_fetches_the_head():
    calls = []

    def head(url):
        calls.append(url)
        return {"author": {"login": "Alice"}, "isCrossRepository": False}

    got = ai.trusted_digest_authors_for_pr(OFF, "U", _boom, head_fn=head)
    assert got == {"teambot"}
    assert calls == []
