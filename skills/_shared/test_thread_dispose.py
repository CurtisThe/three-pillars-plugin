"""Tests for thread_dispose.py — loop-free reply-and-resolve primitive.

Tests:
  - reply precedes resolve in argv order (reply-before-resolve invariant).
  - second run posts ZERO new replies / resolves for already-resolved threads
    (idempotency).
  - threads already marked is_resolved are skipped entirely.
  - threads already carrying the automation signature are not re-replied.
  - result record contains replied / resolved / skipped ids.

Author-filter and spelling tests live in test_thread_dispose_filter.py.

PATH-shims `gh` with a Python script (same pattern as test_thread_resolver.py).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import thread_dispose  # noqa: E402
import thread_resolver  # noqa: E402

# ---------- gh shim templates ----------

# Shim supporting two thread payloads:
#   - RT_open: one open thread, not yet replied by automation
#   - RT_already_resolved: one thread already resolved
#   - RT_already_replied: one thread with automation signature in body
_GH_SHIM_MULTI = '''#!/usr/bin/env python3
import sys, json

LOG = "{logfile}"
argv = sys.argv[1:]
joined = " ".join(argv)

with open(LOG, "a") as fh:
    fh.write(joined + "\\n")

if "replies" in joined:
    print(json.dumps({{"id": 999}}))
    sys.exit(0)

if "api" in argv and "graphql" in argv:
    if "resolveReviewThread" in joined:
        print(json.dumps({{"data": {{"resolveReviewThread": {{"thread": {{"isResolved": True}}}}}}}}))
        sys.exit(0)
    if "reviewThreads" in joined:
        payload = {{"data": {{"repository": {{"pullRequest": {{"reviewThreads": {{"nodes": [
            {{
                "id": "RT_open1",
                "isResolved": False,
                "comments": {{"nodes": [
                    {{"databaseId": 101,
                     "author": {{"login": "copilot-pull-request-reviewer"}},
                     "path": "foo.py", "body": "Fix the loop variable"}}
                ]}}
            }}
        ]}}}}}}}}}}
        print(json.dumps(payload))
        sys.exit(0)

sys.exit(0)
'''

# Shim where threads are already resolved on second call
_GH_SHIM_SECOND_RUN = '''#!/usr/bin/env python3
import sys, json

LOG = "{logfile}"
argv = sys.argv[1:]
joined = " ".join(argv)

with open(LOG, "a") as fh:
    fh.write(joined + "\\n")

if "replies" in joined:
    print(json.dumps({{"id": 999}}))
    sys.exit(0)

if "api" in argv and "graphql" in argv:
    if "resolveReviewThread" in joined:
        print(json.dumps({{"data": {{"resolveReviewThread": {{"thread": {{"isResolved": True}}}}}}}}))
        sys.exit(0)
    if "reviewThreads" in joined:
        payload = {{"data": {{"repository": {{"pullRequest": {{"reviewThreads": {{"nodes": [
            {{
                "id": "RT_open1",
                "isResolved": True,
                "comments": {{"nodes": [
                    {{"databaseId": 101,
                     "author": {{"login": "copilot-pull-request-reviewer"}},
                     "path": "foo.py", "body": "Fix the loop variable"}}
                ]}}
            }}
        ]}}}}}}}}}}
        print(json.dumps(payload))
        sys.exit(0)

sys.exit(0)
'''

# Shim where the thread is unresolved but already has an automation reply as a
# LATER comment (node query). The first comment has a plain Copilot body.
# This is the realistic shape: list_review_threads uses comments(first:1) so
# body = original Copilot text; the automation reply only appears when the
# node(id:$threadId) query fetches all comments.
_GH_SHIM_ALREADY_REPLIED = '''#!/usr/bin/env python3
import sys, json

LOG = "{logfile}"
argv = sys.argv[1:]
joined = " ".join(argv)

with open(LOG, "a") as fh:
    fh.write(joined + "\\n")

if "replies" in joined:
    print(json.dumps({{"id": 999}}))
    sys.exit(0)

if "api" in argv and "graphql" in argv:
    if "resolveReviewThread" in joined:
        print(json.dumps({{"data": {{"resolveReviewThread": {{"thread": {{"isResolved": True}}}}}}}}))
        sys.exit(0)
    # node(id:$threadId) query — fetch thread comments for prior-reply detection
    if "PullRequestReviewThread" in joined:
        # Return two comments: original Copilot comment + automation reply
        sig = "three-pillars-worker"
        payload = {{"data": {{"node": {{"comments": {{"nodes": [
            {{"body": "Fix the loop variable"}},
            {{"body": "\\U0001f916 {{}} (on behalf of @user)\\n\\naddressed".format(sig)}}
        ]}}}}}}}}
        print(json.dumps(payload))
        sys.exit(0)
    if "reviewThreads" in joined:
        # First comment has plain Copilot body — NO automation signature here
        payload = {{"data": {{"repository": {{"pullRequest": {{"reviewThreads": {{"nodes": [
            {{
                "id": "RT_replied1",
                "isResolved": False,
                "comments": {{"nodes": [
                    {{"databaseId": 202,
                     "author": {{"login": "copilot-pull-request-reviewer"}},
                     "path": "bar.py",
                     "body": "Fix the loop variable"}}
                ]}}
            }}
        ]}}}}}}}}}}
        print(json.dumps(payload))
        sys.exit(0)

sys.exit(0)
'''

# Shim for the resolve-failure window scenario:
#   Run 1: reviewThreads returns open thread (no prior reply).
#          replies endpoint succeeds (reply posted).
#          resolveReviewThread FAILS (non-zero exit).
#   Run 2: reviewThreads returns same thread still unresolved.
#          node query returns both original + automation reply comment.
#          Expected: no duplicate reply posted on run 2.
_GH_SHIM_RESOLVE_FAIL_WINDOW = '''#!/usr/bin/env python3
import sys, json, os

LOG = "{logfile}"
REPLY_DONE_FLAG = "{reply_done_flag}"
argv = sys.argv[1:]
joined = " ".join(argv)

with open(LOG, "a") as fh:
    fh.write(joined + "\\n")

if "replies" in joined:
    # Mark that reply was posted and succeed
    open(REPLY_DONE_FLAG, "w").close()
    print(json.dumps({{"id": 999}}))
    sys.exit(0)

if "api" in argv and "graphql" in argv:
    if "resolveReviewThread" in joined:
        # Always FAIL — simulates the resolve-failure window
        sys.exit(1)
    # node(id:$threadId) query for prior-reply detection
    if "PullRequestReviewThread" in joined:
        reply_done = os.path.exists(REPLY_DONE_FLAG)
        if reply_done:
            # Reply already posted — return it as a later comment
            sig = "three-pillars-worker"
            payload = {{"data": {{"node": {{"comments": {{"nodes": [
                {{"body": "Fix the loop variable"}},
                {{"body": "\\U0001f916 {{}} (on behalf of @user)\\n\\naddressed".format(sig)}}
            ]}}}}}}}}
        else:
            # No reply yet — return only the original comment
            payload = {{"data": {{"node": {{"comments": {{"nodes": [
                {{"body": "Fix the loop variable"}}
            ]}}}}}}}}
        print(json.dumps(payload))
        sys.exit(0)
    if "reviewThreads" in joined:
        # Thread always stays unresolved (resolve never works in this shim)
        payload = {{"data": {{"repository": {{"pullRequest": {{"reviewThreads": {{"nodes": [
            {{
                "id": "RT_resolvefail1",
                "isResolved": False,
                "comments": {{"nodes": [
                    {{"databaseId": 303,
                     "author": {{"login": "copilot-pull-request-reviewer"}},
                     "path": "foo.py", "body": "Fix the loop variable"}}
                ]}}
            }}
        ]}}}}}}}}}}
        print(json.dumps(payload))
        sys.exit(0)

sys.exit(0)
'''

PR = "https://github.com/o/r/pull/9"


def _make_shim(tmp_path: Path, monkeypatch, template: str, **extra_fmt) -> Path:
    logfile = tmp_path / "ghlog.txt"
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir(exist_ok=True)
    shim = shim_dir / "gh"
    shim.write_text(template.format(logfile=str(logfile), **extra_fmt))
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim_dir}:{os.environ.get('PATH', '')}")
    return logfile


ENVELOPE_EMPTY = {
    "fixes_applied": [],
    "fixes_deferred": [],
}


# ---------- result record shape ----------


def test_result_record_has_expected_keys(tmp_path, monkeypatch):
    """dispose_threads returns a dict with replied/resolved/skipped keys."""
    logfile = _make_shim(tmp_path, monkeypatch, _GH_SHIM_MULTI)
    result = thread_dispose.dispose_threads(PR, ENVELOPE_EMPTY, author="bot")
    assert "replied" in result
    assert "resolved" in result
    assert "skipped" in result


# ---------- reply-before-resolve ordering ----------


def test_reply_precedes_resolve_in_argv(tmp_path, monkeypatch):
    """For every thread: reply_to_thread argv must appear BEFORE resolve_thread argv."""
    logfile = _make_shim(tmp_path, monkeypatch, _GH_SHIM_MULTI)
    thread_dispose.dispose_threads(PR, ENVELOPE_EMPTY, author="bot")
    lines = logfile.read_text().splitlines()
    # Find reply and resolve lines
    reply_indices = [i for i, l in enumerate(lines) if "replies" in l]
    resolve_indices = [i for i, l in enumerate(lines) if "resolveReviewThread" in l]
    assert reply_indices, "reply must be called"
    assert resolve_indices, "resolve must be called"
    assert min(reply_indices) < min(resolve_indices), (
        "reply_to_thread must be called before resolve_thread"
    )


# ---------- first run results ----------


def test_first_run_replies_and_resolves(tmp_path, monkeypatch):
    """First run on an open thread returns the thread id in replied + resolved."""
    logfile = _make_shim(tmp_path, monkeypatch, _GH_SHIM_MULTI)
    result = thread_dispose.dispose_threads(PR, ENVELOPE_EMPTY, author="bot")
    assert "RT_open1" in result["replied"]
    assert "RT_open1" in result["resolved"]
    assert "RT_open1" not in result["skipped"]


# ---------- idempotency: already-resolved thread ----------


def test_second_run_skips_already_resolved(tmp_path, monkeypatch):
    """Second run (threads now is_resolved) posts NO new replies/resolves."""
    logfile = _make_shim(tmp_path, monkeypatch, _GH_SHIM_SECOND_RUN)
    result = thread_dispose.dispose_threads(PR, ENVELOPE_EMPTY, author="bot")
    assert "RT_open1" in result["skipped"]
    assert "RT_open1" not in result["replied"]
    assert "RT_open1" not in result["resolved"]
    # No reply calls for already-resolved
    log = logfile.read_text()
    assert "replies" not in log, "no reply should be posted for already-resolved thread"


# ---------- idempotency: already-replied thread ----------


def test_thread_with_automation_signature_not_re_replied(tmp_path, monkeypatch):
    """Thread with automation reply in a LATER comment is not re-replied.

    The realistic fixture: list_review_threads returns comments(first:1) so the
    original Copilot body has NO automation signature. The automation reply only
    appears when the node(id:$threadId) query fetches all comments. The guard
    must read those later comments, not the first comment body.
    """
    logfile = _make_shim(tmp_path, monkeypatch, _GH_SHIM_ALREADY_REPLIED)
    thread_dispose.dispose_threads(PR, ENVELOPE_EMPTY, author="bot")
    log = logfile.read_text()
    reply_calls = [l for l in log.splitlines() if "replies" in l]
    assert len(reply_calls) == 0, (
        "thread already carrying automation reply in a later comment must not get a "
        "duplicate reply — the guard must query thread comments, not just the first body"
    )


# ---------- idempotency: resolve-failure window ----------


def test_resolve_failure_window_no_duplicate_reply(tmp_path, monkeypatch):
    """Prove the resolve-failure-window idempotency guarantee.

    Scenario: run 1 — reply succeeds, resolve FAILS (stays unresolved).
    State between runs: thread is_resolved=False but carries automation reply
    as a later comment.
    Run 2 — dispose_threads is called again on the same unresolved thread.
    Expected: ZERO new replies posted (the node-comment guard fires).
    """
    reply_done_flag = tmp_path / "reply_done"
    logfile = _make_shim(
        tmp_path,
        monkeypatch,
        _GH_SHIM_RESOLVE_FAIL_WINDOW,
        reply_done_flag=str(reply_done_flag),
    )

    # Run 1: reply succeeds, resolve fails
    result1 = thread_dispose.dispose_threads(PR, ENVELOPE_EMPTY, author="bot")
    assert "RT_resolvefail1" in result1["replied"], "run 1 must post the reply"
    assert "RT_resolvefail1" not in result1["resolved"], "run 1 resolve must fail"
    assert reply_done_flag.exists(), "reply_done flag must be set after run 1"

    log_after_run1 = logfile.read_text()
    replies_run1 = [l for l in log_after_run1.splitlines() if "replies" in l]
    assert len(replies_run1) == 1, "exactly one reply posted in run 1"

    # Run 2: thread still unresolved, but automation reply exists as later comment
    result2 = thread_dispose.dispose_threads(PR, ENVELOPE_EMPTY, author="bot")
    assert "RT_resolvefail1" not in result2["replied"], (
        "run 2 must NOT post a duplicate reply — the node-comment guard must catch it"
    )

    log_after_run2 = logfile.read_text()
    replies_total = [l for l in log_after_run2.splitlines() if "replies" in l]
    assert len(replies_total) == 1, (
        "total reply count across both runs must be exactly 1 — no duplicates"
    )


# ---------- _disposition_text lives in thread_dispose ----------


def test_disposition_text_function_exists():
    """_disposition_text must be importable from thread_dispose (its real Python home)."""
    assert hasattr(thread_dispose, "_disposition_text"), (
        "_disposition_text must be defined in thread_dispose, not just SKILL.md pseudocode"
    )


def test_disposition_text_addressed():
    finding = {"comment_id": 1, "thread_id": "RT_1", "body": "bad loop var"}
    envelope = {"fixes_applied": [{"comment_id": 1}], "fixes_deferred": []}
    text = thread_dispose._disposition_text("addressed", finding, envelope)
    assert "addressed" in text.lower()


def test_disposition_text_deferred():
    finding = {"comment_id": 2, "thread_id": "RT_2", "body": "style issue"}
    envelope = {"fixes_applied": [], "fixes_deferred": [{"comment_id": 2}]}
    text = thread_dispose._disposition_text("deferred", finding, envelope)
    assert "deferred" in text.lower()


def test_disposition_text_stale():
    finding = {"comment_id": 3, "thread_id": "RT_3", "body": "old finding"}
    envelope = {"fixes_applied": [], "fixes_deferred": []}
    text = thread_dispose._disposition_text("stale", finding, envelope)
    assert "stale" in text.lower() or "addressed" in text.lower() or "resolved" in text.lower()
