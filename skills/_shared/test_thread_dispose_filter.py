"""Tests for thread_dispose.py — author-filter and surface-spelling invariants.

Tests in this module:
  - human-authored threads are NEVER replied to or resolved.
  - filter is load-bearing (mutation test: widening to 'alice' triggers a reply).
  - copilot-authored thread (bare GraphQL login) IS disposed.
  - thread with null thread_id is skipped even for Copilot author.
  - anti-tautology: bare 'copilot-pull-request-reviewer' is disposed;
    '[bot]'-suffixed spelling is treated as non-Copilot and skipped.

Core dispose-path tests (ordering, idempotency, disposition_text) live in
test_thread_dispose.py.

PATH-shims `gh` with a Python script (same pattern as test_thread_resolver.py).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import thread_dispose  # noqa: E402

PR = "https://github.com/o/r/pull/9"

ENVELOPE_EMPTY = {
    "fixes_applied": [],
    "fixes_deferred": [],
}


def _make_shim(tmp_path: Path, monkeypatch, template: str, **extra_fmt) -> Path:
    logfile = tmp_path / "ghlog.txt"
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir(exist_ok=True)
    shim = shim_dir / "gh"
    shim.write_text(template.format(logfile=str(logfile), **extra_fmt))
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim_dir}:{os.environ.get('PATH', '')}")
    return logfile


# ---------- shim templates ----------

_GH_SHIM_HUMAN = '''#!/usr/bin/env python3
import sys, json
LOG = "{logfile}"
argv = sys.argv[1:]; joined = " ".join(argv)
with open(LOG, "a") as fh: fh.write(joined + "\\n")
if "api" in argv and "graphql" in argv and "reviewThreads" in joined:
    print(json.dumps({{"data": {{"repository": {{"pullRequest": {{"reviewThreads": {{"nodes": [
        {{"id": "RT_human1", "isResolved": False, "comments": {{"nodes": [
            {{"databaseId": 501, "author": {{"login": "alice"}}, "path": "a.py", "body": "Nit"}}
        ]}}}}
    ]}}}}}}}}}}))
sys.exit(0)
'''

_GH_SHIM_COPILOT = '''#!/usr/bin/env python3
import sys, json
LOG = "{logfile}"
argv = sys.argv[1:]; joined = " ".join(argv)
with open(LOG, "a") as fh: fh.write(joined + "\\n")
if "replies" in joined: print(json.dumps({{"id": 999}})); sys.exit(0)
if "api" in argv and "graphql" in argv:
    if "resolveReviewThread" in joined:
        print(json.dumps({{"data": {{"resolveReviewThread": {{"thread": {{"isResolved": True}}}}}}}})); sys.exit(0)
    if "PullRequestReviewThread" in joined:
        print(json.dumps({{"data": {{"node": {{"comments": {{"nodes": []}}}}}}}})); sys.exit(0)
    if "reviewThreads" in joined:
        print(json.dumps({{"data": {{"repository": {{"pullRequest": {{"reviewThreads": {{"nodes": [
            {{"id": "RT_cop1", "isResolved": False, "comments": {{"nodes": [
                {{"databaseId": 601, "author": {{"login": "copilot-pull-request-reviewer"}}, "path": "b.py", "body": "Use list comp"}}
            ]}}}}
        ]}}}}}}}}}}))
sys.exit(0)
'''

_GH_SHIM_TID_LESS = '''#!/usr/bin/env python3
import sys, json
LOG = "{logfile}"
argv = sys.argv[1:]; joined = " ".join(argv)
with open(LOG, "a") as fh: fh.write(joined + "\\n")
if "api" in argv and "graphql" in argv and "reviewThreads" in joined:
    print(json.dumps({{"data": {{"repository": {{"pullRequest": {{"reviewThreads": {{"nodes": [
        {{"id": None, "isResolved": False, "comments": {{"nodes": [
            {{"databaseId": 701, "author": {{"login": "copilot-pull-request-reviewer"}}, "path": "c.py", "body": "Unused import"}}
        ]}}}}
    ]}}}}}}}}}}))
sys.exit(0)
'''

# Anti-tautology shims — use LITERAL login strings (not production constants) to
# pin the exact GraphQL surface spelling; future drift back to "[bot]" fails the suite.

_GH_SHIM_SPELLING_BARE = '''#!/usr/bin/env python3
import sys, json
LOG = "{logfile}"
argv = sys.argv[1:]; joined = " ".join(argv)
with open(LOG, "a") as fh: fh.write(joined + "\\n")
if "replies" in joined: print(json.dumps({{"id": 999}})); sys.exit(0)
if "api" in argv and "graphql" in argv:
    if "resolveReviewThread" in joined:
        print(json.dumps({{"data": {{"resolveReviewThread": {{"thread": {{"isResolved": True}}}}}}}})); sys.exit(0)
    if "PullRequestReviewThread" in joined:
        print(json.dumps({{"data": {{"node": {{"comments": {{"nodes": []}}}}}}}})); sys.exit(0)
    if "reviewThreads" in joined:
        print(json.dumps({{"data": {{"repository": {{"pullRequest": {{"reviewThreads": {{"nodes": [
            {{"id": "RT_bare1", "isResolved": False, "comments": {{"nodes": [
                {{"databaseId": 801, "author": {{"login": "copilot-pull-request-reviewer"}}, "path": "x.py", "body": "Bare login"}}
            ]}}}}
        ]}}}}}}}}}}))
sys.exit(0)
'''

_GH_SHIM_SPELLING_BOT_SUFFIX = '''#!/usr/bin/env python3
import sys, json
LOG = "{logfile}"
argv = sys.argv[1:]; joined = " ".join(argv)
with open(LOG, "a") as fh: fh.write(joined + "\\n")
if "api" in argv and "graphql" in argv and "reviewThreads" in joined:
    print(json.dumps({{"data": {{"repository": {{"pullRequest": {{"reviewThreads": {{"nodes": [
        {{"id": "RT_botsuffix1", "isResolved": False, "comments": {{"nodes": [
            {{"databaseId": 901, "author": {{"login": "copilot-pull-request-reviewer[bot]"}}, "path": "y.py", "body": "Bot-suffix login"}}
        ]}}}}
    ]}}}}}}}}}}))
sys.exit(0)
'''

_GH_SHIM_SPELLING_HUMAN_ONLY = '''#!/usr/bin/env python3
import sys, json
LOG = "{logfile}"
argv = sys.argv[1:]; joined = " ".join(argv)
with open(LOG, "a") as fh: fh.write(joined + "\\n")
if "api" in argv and "graphql" in argv and "reviewThreads" in joined:
    print(json.dumps({{"data": {{"repository": {{"pullRequest": {{"reviewThreads": {{"nodes": [
        {{"id": "RT_human2", "isResolved": False, "comments": {{"nodes": [
            {{"databaseId": 902, "author": {{"login": "bob"}}, "path": "z.py", "body": "Human"}}
        ]}}}}
    ]}}}}}}}}}}))
sys.exit(0)
'''


# ---------- author filter: human threads never touched ----------


def test_human_authored_thread_not_touched(tmp_path, monkeypatch):
    """Human-authored thread must trigger zero gh reply or resolve mutations."""
    logfile = _make_shim(tmp_path, monkeypatch, _GH_SHIM_HUMAN)
    result = thread_dispose.dispose_threads(PR, ENVELOPE_EMPTY, author="bot")
    log = logfile.read_text()
    assert "replies" not in log, "reply must NOT be posted for human thread"
    assert "resolveReviewThread" not in log, "resolve must NOT be called for human thread"
    assert result["replied"] == [] and result["resolved"] == []


def test_human_thread_filter_is_mutation_real(tmp_path, monkeypatch):
    """Filter is load-bearing: widening it to accept 'alice' causes a reply to fire."""
    import review_readiness as rr
    logfile = _make_shim(tmp_path, monkeypatch, _GH_SHIM_HUMAN)
    # Patch the canonical helper to accept 'alice' as a Copilot login
    monkeypatch.setattr(rr, "is_copilot_review_author", lambda login, *, surface: login == "alice")
    thread_dispose.dispose_threads(PR, ENVELOPE_EMPTY, author="bot")
    assert "replies" in logfile.read_text(), (
        "widened filter must trigger reply — proves the real filter suppresses it"
    )


def test_copilot_authored_thread_is_disposed(tmp_path, monkeypatch):
    """Copilot-authored thread IS replied to and resolved."""
    logfile = _make_shim(tmp_path, monkeypatch, _GH_SHIM_COPILOT)
    result = thread_dispose.dispose_threads(PR, ENVELOPE_EMPTY, author="bot")
    assert "RT_cop1" in result["replied"] and "RT_cop1" in result["resolved"]


def test_tid_less_thread_no_reply(tmp_path, monkeypatch):
    """Copilot thread with null thread_id is skipped — no reply, no resolve."""
    logfile = _make_shim(tmp_path, monkeypatch, _GH_SHIM_TID_LESS)
    result = thread_dispose.dispose_threads(PR, ENVELOPE_EMPTY, author="bot")
    log = logfile.read_text()
    assert "replies" not in log and "resolveReviewThread" not in log
    assert result["replied"] == [] and result["resolved"] == []


# ---------- anti-tautology spelling tests ----------
# Pin the exact GraphQL surface spelling. These tests use LITERAL strings (not
# production constants) so a future drift back to "[bot]"-suffixed spelling
# will fail the suite rather than silently passing.


def test_bare_graphql_login_is_disposed(tmp_path, monkeypatch):
    """Bare 'copilot-pull-request-reviewer' (real GraphQL spelling) MUST be disposed.

    Uses a literal string — NOT a production constant — to pin the exact surface
    spelling. A future drift in the filter would cause this to fail rather than
    vacuously passing.
    """
    logfile = _make_shim(tmp_path, monkeypatch, _GH_SHIM_SPELLING_BARE)
    result = thread_dispose.dispose_threads(PR, ENVELOPE_EMPTY, author="bot")
    assert "RT_bare1" in result["replied"], (
        "bare 'copilot-pull-request-reviewer' login must be DISPOSED — "
        "the GraphQL surface never carries a [bot] suffix"
    )
    assert "RT_bare1" in result["resolved"]


def test_bot_suffix_login_is_skipped(tmp_path, monkeypatch):
    """'copilot-pull-request-reviewer[bot]' (wrong spelling for GraphQL) MUST be skipped.

    The GraphQL reviewThreads surface does NOT include the [bot] suffix.
    A thread carrying this spelling is not a Copilot thread — must be skipped.
    Uses a literal string to pin the anti-pattern.
    """
    logfile = _make_shim(tmp_path, monkeypatch, _GH_SHIM_SPELLING_BOT_SUFFIX)
    result = thread_dispose.dispose_threads(PR, ENVELOPE_EMPTY, author="bot")
    log = logfile.read_text()
    assert "replies" not in log, (
        "'copilot-pull-request-reviewer[bot]' is NOT the GraphQL login — "
        "must be skipped, not disposed"
    )
    assert result["replied"] == [] and result["resolved"] == []


def test_human_login_is_skipped(tmp_path, monkeypatch):
    """A plain human login must be skipped (not replied to or resolved)."""
    logfile = _make_shim(tmp_path, monkeypatch, _GH_SHIM_SPELLING_HUMAN_ONLY)
    result = thread_dispose.dispose_threads(PR, ENVELOPE_EMPTY, author="bot")
    log = logfile.read_text()
    assert "replies" not in log
    assert result["replied"] == [] and result["resolved"] == []
