"""Tests for cert_comment.py -- the `basesync-cert.v1` producer breadcrumb.

Task 9.1. Audit-only, ZERO gate authority (see module docstring / detailed-design.md
Producer breadcrumb section). Run with:
  pytest skills/tp-merge-from-main/scripts/test_cert_comment.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cert_comment  # noqa: E402

_LOOP_DIR = Path(__file__).resolve().parent.parent.parent / "tp-pr-iterate" / "scripts"
if str(_LOOP_DIR) not in sys.path:
    sys.path.insert(0, str(_LOOP_DIR))
import review_proof  # noqa: E402


def test_format_cert_comment_exact_shape():
    body = cert_comment.format_cert_comment(
        "a" * 40, "b" * 40, ["design-inventory-row-merge"],
    )
    assert body == (
        f"<sub>basesync-cert.v1: pre `{'a' * 40}` · post `{'b' * 40}` · "
        "allowlist v1 · classes [design-inventory-row-merge]</sub>"
    )


def test_format_cert_comment_default_allowlist_version_is_v1():
    body = cert_comment.format_cert_comment("a" * 40, "b" * 40, ["design-inventory-row-merge"])
    assert "allowlist v1" in body


def test_format_cert_comment_honors_explicit_allowlist_version():
    body = cert_comment.format_cert_comment(
        "a" * 40, "b" * 40, ["design-inventory-row-merge"], allowlist_version="v2",
    )
    assert "allowlist v2" in body


def test_format_cert_comment_multiple_resolved_classes():
    body = cert_comment.format_cert_comment(
        "a" * 40, "b" * 40, ["design-inventory-row-merge", "id-renumber-collision"],
    )
    assert "classes [design-inventory-row-merge, id-renumber-collision]" in body


def test_post_cert_comment_success_calls_injected_run_gh():
    calls = []

    def fake_run_gh(pr_url, body):
        calls.append((pr_url, body))
        return True

    ok = cert_comment.post_cert_comment(
        "https://github.com/o/r/pull/5", "hello", run_gh=fake_run_gh,
    )
    assert ok is True
    assert calls == [("https://github.com/o/r/pull/5", "hello")]


def test_post_cert_comment_never_raises_on_failing_run_gh():
    """A failing injected run_gh (returns False) -> False, no exception."""
    ok = cert_comment.post_cert_comment(
        "https://github.com/o/r/pull/5", "hello", run_gh=lambda *_a, **_k: False,
    )
    assert ok is False


def test_post_cert_comment_never_raises_on_exception_from_run_gh():
    """An injected run_gh that RAISES must still yield False, never propagate."""
    def boom(*_a, **_k):
        raise RuntimeError("network exploded")

    ok = cert_comment.post_cert_comment(
        "https://github.com/o/r/pull/5", "hello", run_gh=boom,
    )
    assert ok is False


def test_disjointness_cert_comment_never_matches_proof_digest_regex():
    """Envelope word `basesync-cert.v1:` is disjoint from `proof: base` --
    mirrors test_base_sync_cert_attacks.py's task 7.4 pin, asserted locally here too."""
    body = cert_comment.format_cert_comment("a" * 40, "b" * 40, ["design-inventory-row-merge"])
    for line in body.splitlines():
        assert review_proof._DIGEST_HEAD_RE.search(line) is None
        assert review_proof._DEGRADED_RE.search(line) is None


def test_disjointness_proof_digest_never_contains_cert_envelope_word():
    meta = {
        "base": "base000", "head": "c" * 40, "files_changed": 2,
        "insertions": 3, "deletions": 1, "degraded": False, "reason": None,
    }
    digest_body = review_proof.format_proof_digest(meta, [("correctness", 0)])
    assert "basesync-cert.v1" not in digest_body
