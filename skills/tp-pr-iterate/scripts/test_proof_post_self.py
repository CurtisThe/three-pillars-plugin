"""test_proof_post_self.py — `post_proof_checked` reads the digest author against the PR's trust set.

design: per-developer-automation-account, Task 1.4 (behaviour 10)

Under `per_developer_author: self` the PR author's own digest is `ok`; someone else's is
`proof-author-untrusted`; under `off` the author's digest is `proof-author-untrusted`, today's
verdict. Hermetic: posts, comments and the head fetch are fakes.

Run with: pytest skills/tp-pr-iterate/scripts/test_proof_post_self.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import review_proof  # noqa: E402  (puts skills/_shared on sys.path)
import proof_post  # noqa: E402

PR = "https://github.com/o/r/pull/9"
HEAD = "abc123def4567890abc123def4567890abc12345"
OFF = {"github": {"pr_author_account": "TeamBot"}}
SELF = {"github": {"pr_author_account": "TeamBot", "per_developer_author": "self"}}


def _digest():
    meta = {"base": "base000", "head": HEAD, "files_changed": 3, "insertions": 5,
            "deletions": 1, "degraded": False, "reason": None}
    return review_proof.format_proof_digest(meta, [("correctness", 0)])


def _head_fn(author):
    return lambda _url: {"author": {"login": author}, "isCrossRepository": False}


def _check(config, pr_author, digest_author="alice"):
    items = [{"author": digest_author, "body": "summary\n" + _digest()}]
    return proof_post.post_proof_checked(
        PR, [], head=HEAD, digest=_digest(), config=config,
        post_fn=lambda url, body: True, comments_fn=lambda _u: items,
        head_fn=_head_fn(pr_author))


def test_self_the_authors_own_digest_is_ok():
    got = _check(SELF, "alice")
    assert (got["status"], got["author"]) == ("ok", "alice")


def test_self_someone_elses_digest_is_untrusted():
    assert _check(SELF, "bob")["status"] == "proof-author-untrusted"


def test_off_the_authors_digest_is_untrusted():
    assert _check(OFF, "alice")["status"] == "proof-author-untrusted"
