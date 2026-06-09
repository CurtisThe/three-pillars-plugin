"""Tests for thread_resolver — reply-and-resolve plumbing (Enhancement 1).

PATH-shims `gh` with a Python script that captures argv to a file and returns
canned JSON / exit codes, mirroring test_fix_round.py's pattern.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import thread_resolver  # noqa: E402


_GH_SHIM = '''#!/usr/bin/env python3
import sys, json

LOG = "{logfile}"
MODE = "{mode}"
argv = sys.argv[1:]
joined = " ".join(argv)
with open(LOG, "a") as fh:
    fh.write(joined + "\\n")

# Replies POST (REST): repos/.../comments/{{cid}}/replies
if "replies" in joined:
    if MODE == "reply-fail":
        print("gh: HTTP 404", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({{"id": 999}}))
    sys.exit(0)

# GraphQL: resolve mutation OR threads query
if argv[:3] == ["api", "graphql"] or (len(argv) >= 2 and argv[0] == "api" and argv[1] == "graphql"):
    if "resolveReviewThread" in joined:
        if MODE == "resolve-fail":
            print("gh: error", file=sys.stderr)
            sys.exit(1)
        print(json.dumps({{"data": {{"resolveReviewThread": {{"thread": {{"isResolved": True}}}}}}}}))
        sys.exit(0)
    if "reviewThreads" in joined and MODE == "null-pr":
        print(json.dumps({{"data": {{"repository": {{"pullRequest": None}}}}}}))
        sys.exit(0)
    if "reviewThreads" in joined:
        payload = {{"data": {{"repository": {{"pullRequest": {{"reviewThreads": {{"nodes": [
            {{"id": "RT_kwA", "isResolved": False, "comments": {{"nodes": [
                {{"databaseId": 12345, "author": {{"login": "Copilot"}}, "path": "x.py", "body": "stale ref"}}
            ]}}}}
        ]}}}}}}}}}}
        print(json.dumps(payload))
        sys.exit(0)

sys.exit(0)
'''


def _shim(tmp_path: Path, monkeypatch, mode: str = "ok") -> Path:
    """Install a PATH-shimmed `gh`; returns the argv logfile path."""
    logfile = tmp_path / "ghlog.txt"
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    shim = shim_dir / "gh"
    shim.write_text(_GH_SHIM.format(logfile=str(logfile), mode=mode))
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim_dir}:{os.environ.get('PATH', '')}")
    return logfile


PR = "https://github.com/o/r/pull/7"


# ---------- disposition ----------


def test_disposition_addressed():
    finding = {"comment_id": 1, "thread_id": "RT_1"}
    envelope = {"fixes_applied": [{"comment_id": 1}], "fixes_deferred": []}
    assert thread_resolver.disposition_for(finding, envelope, set()) == "addressed"


def test_disposition_deferred():
    finding = {"comment_id": 2, "thread_id": "RT_2"}
    envelope = {"fixes_applied": [], "fixes_deferred": [{"comment_id": 2}]}
    assert thread_resolver.disposition_for(finding, envelope, set()) == "deferred"


def test_disposition_stale():
    finding = {"comment_id": 3, "thread_id": "RT_3"}
    envelope = {"fixes_applied": [], "fixes_deferred": []}
    assert thread_resolver.disposition_for(finding, envelope, {"RT_3"}) == "stale"


def test_disposition_default_deferred():
    finding = {"comment_id": 4, "thread_id": "RT_4"}
    envelope = {"fixes_applied": [], "fixes_deferred": []}
    assert thread_resolver.disposition_for(finding, envelope, set()) == "deferred"


# ---------- signature ----------


def test_sign_reply_prefix():
    out = thread_resolver.sign_reply("Addressed in abc123.", "curtis")
    first = out.splitlines()[0]
    assert first == "🤖 three-pillars-worker (on behalf of @curtis)"
    assert "Addressed in abc123." in out


# ---------- GraphQL / REST plumbing ----------


def test_resolve_thread_uses_graphql(tmp_path, monkeypatch):
    logfile = _shim(tmp_path, monkeypatch, mode="ok")
    assert thread_resolver.resolve_thread("RT_kwA") is True
    log = logfile.read_text()
    assert "graphql" in log and "resolveReviewThread" in log
    assert "edit" not in log  # never `gh pr edit`


def test_resolve_thread_fail_open(tmp_path, monkeypatch):
    _shim(tmp_path, monkeypatch, mode="resolve-fail")
    assert thread_resolver.resolve_thread("RT_kwA") is False


def test_list_review_threads_query_and_id_split(tmp_path, monkeypatch):
    logfile = _shim(tmp_path, monkeypatch, mode="ok")
    threads = thread_resolver.list_review_threads(PR)
    log = logfile.read_text()
    assert "reviewThreads(first:100)" in log
    assert len(threads) == 1
    t = threads[0]
    # thread node id (resolve) is distinct from comment databaseId (reply)
    assert t["thread_id"] == "RT_kwA"
    assert t["comment_id"] == 12345
    assert t["author"] == "Copilot"


def test_reply_to_thread_uses_comment_id_rest(tmp_path, monkeypatch):
    logfile = _shim(tmp_path, monkeypatch, mode="ok")
    ok = thread_resolver.reply_to_thread(PR, 12345, "hello")
    assert ok is True
    log = logfile.read_text()
    assert "comments/12345/replies" in log


def test_reply_failure_returns_false_no_raise(tmp_path, monkeypatch):
    _shim(tmp_path, monkeypatch, mode="reply-fail")
    assert thread_resolver.reply_to_thread(PR, 12345, "hello") is False


def test_list_review_threads_fail_open_on_null_pullrequest(tmp_path, monkeypatch):
    """GraphQL partial-error returns pullRequest: null with exit 0 — must fail
    open to [] (Copilot/-code-review PR #33 finding), not raise AttributeError."""
    _shim(tmp_path, monkeypatch, mode="null-pr")
    assert thread_resolver.list_review_threads(PR) == []
