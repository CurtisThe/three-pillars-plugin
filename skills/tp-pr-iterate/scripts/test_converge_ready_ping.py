"""Ready-ping wiring at the converge two-stable finish (pr-ready-ping Task 1.3).

The converged finish calls an injected `ready_ping_fn(pr_url, head)` exactly once
and puts its dict under `ready_ping` in the terminal JSON; a raising ping leaves
`converged` true (fail-open); a blocked finish never pings; the real
`ready_ping.ping_ready` dedupes a re-finish of one head to one `sent` + one
`duplicate`; the CLI wires `ready_ping.ping_ready` only when `seams is None`.

Hermetic — every seam injected; no live gh, no network, no run_round subprocess.
"""
from __future__ import annotations

import functools
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
_SHARED = HERE.parent.parent / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import converge  # noqa: E402
import converge_cli  # noqa: E402
import ready_ping  # noqa: E402 — skills/_shared, on sys.path via converge's shim


_FULL_HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
_PR = "https://github.com/o/r/pull/1"
_TWO_STABLE = "two-stable [code-review-only]"


def _angle(findings) -> str:
    return json.dumps({"findings": findings}, indent=2) + "\n"


def _config(author="tp-bot") -> dict:
    return {"review": {"expects_copilot": False, "automation_identities": [author]},
            "ci": {"expects_github_checks": False}}


def _run_git(numstat="3\t1\tfoo.py\n", head=_FULL_HEAD):
    def _run(args):
        if args[:2] == ["git", "rev-parse"]:
            return 0, head + "\n", ""
        if "--numstat" in args:
            return 0, numstat, ""
        return 0, "", ""
    return _run


class _Recorder:
    def __init__(self, env):
        self.posts = []
        self.env = env

    def post_fn(self, url, body):
        self.posts.append((url, body))
        return True

    def run_round_fn(self, stdin):
        self.last_stdin = stdin
        return dict(self.env)

    def comments_fn(self, _url):
        return [{"author": "tp-bot", "body": self.posts[-1][1]}] if self.posts else []


def _finish(tmp_path, *, ready_ping_fn=None, post_fn=None):
    """One clean-round finish; returns (rc, terminal JSON, recorder)."""
    angle = tmp_path / "r1.txt"
    angle.write_text(_angle([]), encoding="utf-8")
    rec = _Recorder({"converged": True, "terminal": _TWO_STABLE})
    out = io.StringIO()
    rc = converge.converge(
        base="base000", head=_FULL_HEAD, pr_url=_PR, config=_config(),
        angle_files=[str(angle)], proof_root=tmp_path / "proof",
        state_path=tmp_path / "state.json",
        post_fn=post_fn or rec.post_fn, run_round_fn=rec.run_round_fn,
        comments_fn=rec.comments_fn, self_login_fn=lambda: "tp-bot",
        run_git=_run_git(), now_iso="2026-10-15T00:00:00+00:00",
        out=out, err=io.StringIO(), ready_ping_fn=ready_ping_fn,
    )
    return rc, json.loads(out.getvalue().strip().splitlines()[-1]), rec


# ============================================================
# The converged finish pings once, verdict-first, key in the JSON
# ============================================================


def test_converged_finish_calls_ready_ping_once(tmp_path):
    calls = []

    def ready_ping_fn(pr_url, head):
        calls.append((pr_url, head))
        return {"status": "sent", "kind": "ready", "channel": "push"}

    rc, result, _rec = _finish(tmp_path, ready_ping_fn=ready_ping_fn)
    assert rc == 0
    assert calls == [(_PR, _FULL_HEAD)]
    assert result["converged"] is True
    assert result["ready_ping"] == {"status": "sent", "kind": "ready",
                                    "channel": "push"}


def test_raising_ready_ping_leaves_converged_true(tmp_path):
    def boom(pr_url, head):
        raise RuntimeError("push transport died")

    rc, result, _rec = _finish(tmp_path, ready_ping_fn=boom)
    assert rc == 0
    assert result["converged"] is True
    assert result["terminal"] == _TWO_STABLE


def test_no_seam_emits_no_ready_ping_key(tmp_path):
    rc, result, _rec = _finish(tmp_path)
    assert rc == 0
    assert "ready_ping" not in result


def test_blocked_finish_never_pings(tmp_path):
    calls = []

    def ready_ping_fn(pr_url, head):
        calls.append((pr_url, head))
        return {"status": "sent"}

    rc, result, _rec = _finish(tmp_path, ready_ping_fn=ready_ping_fn,
                               post_fn=lambda url, body: False)  # blocked finish
    assert rc != 0
    assert result["converged"] is False
    assert calls == []
    assert "ready_ping" not in result


# ============================================================
# The real ping_ready dedupes a re-finish of one head
# ============================================================


def test_refinish_one_head_pings_sent_then_duplicate(tmp_path):
    ledger = tmp_path / "ledger.ndjson"
    info = {"mergeable": "MERGEABLE", "title": "t", "headRefName": "tp/x"}
    fn = functools.partial(ready_ping.ping_ready, info_fn=lambda url: info,
                           ledger=ledger, out=io.StringIO())
    rc1, result1, _rec1 = _finish(tmp_path, ready_ping_fn=fn)
    rc2, result2, _rec2 = _finish(tmp_path, ready_ping_fn=fn)
    assert rc1 == 0 and rc2 == 0
    assert result1["ready_ping"]["status"] == "sent"
    assert result2["ready_ping"]["status"] == "duplicate"


# ============================================================
# CLI wiring — default seams ping, explicit seams wire nothing
# ============================================================


def _cli_argv(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(_config()), encoding="utf-8")
    return ["--base", "base000", "--head", _FULL_HEAD, "--pr-url", _PR,
            "--config", str(config_file), "--angle-file", str(tmp_path / "r1.txt")]


def test_cli_with_no_seams_wires_ping_ready(tmp_path, monkeypatch):
    captured = {}

    def fake_converge(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(converge_cli.converge, "converge", fake_converge)
    rc = converge_cli.main(_cli_argv(tmp_path))
    assert rc == 0
    assert captured.get("ready_ping_fn") is ready_ping.ping_ready


def test_cli_with_explicit_seams_wires_no_ping(tmp_path, monkeypatch):
    captured = {}

    def fake_converge(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(converge_cli.converge, "converge", fake_converge)
    rc = converge_cli.main(_cli_argv(tmp_path), seams={"out": io.StringIO()})
    assert rc == 0
    assert captured.get("ready_ping_fn") is None
