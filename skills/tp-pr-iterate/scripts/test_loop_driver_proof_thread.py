"""test_loop_driver_proof_thread.py — run_loop threads proof_ok (B3, B8).

The over-cap test_loop_driver.py is grandfathered — these new run_loop proof-
thread tests live here. Hermetic: scripted poll_fn, injected proof_ok_fn; no live
gh/git. Reuses the scripted-round helpers from test_loop_driver.
"""
from __future__ import annotations

import ast
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import loop_driver  # noqa: E402
import review_proof  # noqa: E402
from test_loop_driver import (  # noqa: E402 — reuse scripted-round helpers
    _base_run_state,
    _make_minor_round,
    _make_poll_fn,
)

PR = "https://github.com/o/r/pull/1"
_CONFIG = {"review": {"expects_copilot": False}, "ci": {"expects_github_checks": False}}


def _converge_rounds():
    """A structural round (caches clean findings) then a minor-only round → eligible."""
    return [
        {
            "new_comments": [{"id": 1}],
            "classified": [{"comment_id": "c1", "verdict": "structural",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": [], "copilot_threads": [],
            "head_sha": "sha1", "commit_id": "sha1",
        },
        _make_minor_round(),
    ]


def _drive(monkeypatch, proof_ok_fn, *, decisions_path=None):
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)
    monkeypatch.setattr(loop_driver, "_ci_settled_on_head",
                        lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)
    return loop_driver.run_loop(
        design="d", pr_url=PR, state=state, config=_CONFIG,
        dry_run=True, poll_fn=_make_poll_fn(_converge_rounds()),
        fix_round_fn=None, sleep_fn=lambda s: None, now_fn=lambda: now,
        unresolved_actionable_fn=lambda u: 0, reviewed_fn=lambda u: False,
        codereview_fn=lambda effort, head_sha: [],
        proof_ok_fn=proof_ok_fn, decisions_path=decisions_path,
    )


# ---------- B3: proof gates convergence ----------


def test_run_loop_threads_proof_ok_blocks_unproofed(monkeypatch):
    result = _drive(monkeypatch, proof_ok_fn=lambda _h: False)
    assert result.get("phase") == "blocked-no-independent-review"
    assert result.get("termination_reason") != "two-stable"


def test_run_loop_threads_proof_ok_converges_when_proofed(monkeypatch):
    result = _drive(monkeypatch, proof_ok_fn=lambda _h: True)
    assert result.get("termination_reason") == "two-stable"


def test_run_loop_proof_ok_computed_against_current_head(monkeypatch):
    """proof_ok_fn is called with the head from poll_fn (sha1), not a cached sha."""
    seen = []

    def spy(head):
        seen.append(head)
        return True

    _drive(monkeypatch, proof_ok_fn=spy)
    assert "sha1" in seen, f"proof_ok_fn must be called with the polled head; got {seen}"
    # Currency: never invoked against an unknown/cached placeholder.
    assert all(h == "sha1" for h in seen), seen


def test_run_loop_default_proof_ok_fn_wires_review_proof(monkeypatch):
    """proof_ok_fn=None binds review_proof.proof_ok (monkeypatch proves the wire),
    threading the loop config into the comment arm's trusted-author set."""
    calls = []

    def fake_proof_ok(head, *, pr_url=None, root=None, comments_fn=None,
                      config=None, self_login_fn=None):
        calls.append((head, pr_url, config))
        return True

    monkeypatch.setattr(review_proof, "proof_ok", fake_proof_ok)
    result = _drive(monkeypatch, proof_ok_fn=None)
    assert calls, "default proof_ok_fn must call review_proof.proof_ok"
    assert calls[0][0] == "sha1"
    assert calls[0][1] == PR
    # Round-2 mutation pin: binding config=None here passed the whole suite while
    # silently untrusted-ing the loop's own digests on repos with
    # review.automation_identities extras (spurious convergence block).
    assert calls[0][2] is _CONFIG
    assert result.get("termination_reason") == "two-stable"


# ---------- B8: escalation note legibility ----------


def test_blocked_terminal_note_says_no_proof(monkeypatch, tmp_path):
    decisions = tmp_path / "decisions.md"
    decisions.write_text("", encoding="utf-8")
    result = _drive(monkeypatch, proof_ok_fn=lambda _h: False,
                    decisions_path=str(decisions))
    # transition reason note
    notes = [t.get("note") for t in result.get("transitions", [])]
    assert any("NEEDS REVIEW — no proof" in (n or "") for n in notes), notes
    # decisions.md line
    text = decisions.read_text(encoding="utf-8")
    assert "NEEDS REVIEW — no proof" in text, text


def test_blocked_terminal_token_and_label_unchanged(monkeypatch):
    """The terminal token stays blocked-no-independent-review (fleet classification)."""
    labels = []
    monkeypatch.setattr(loop_driver, "_ci_settled_on_head",
                        lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label",
                        lambda url, lbl: labels.append(lbl))
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)
    result = loop_driver.run_loop(
        design="d", pr_url=PR, state=state, config=_CONFIG,
        dry_run=True, poll_fn=_make_poll_fn(_converge_rounds()),
        fix_round_fn=None, sleep_fn=lambda s: None, now_fn=lambda: now,
        unresolved_actionable_fn=lambda u: 0, reviewed_fn=lambda u: False,
        codereview_fn=lambda effort, head_sha: [],
        proof_ok_fn=lambda _h: False,
    )
    assert result.get("phase") == "blocked-no-independent-review"
    assert "tp:needs-human-attention" in labels, labels


# ---------- own guards ----------


def test_loop_driver_proof_thread_under_cap():
    src = (HERE / "test_loop_driver_proof_thread.py").read_text(encoding="utf-8")
    lines = src.count("\n") + 1
    assert lines <= 500, f"file is {lines} lines (cap=500)"
    assert len(src) <= 50000


def test_loop_driver_proof_thread_c1_clean():
    src = (HERE / "test_loop_driver_proof_thread.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = (alias.name or "").lower()
                assert "anthropic" not in name and "claude_agent" not in name
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").lower()
            assert "anthropic" not in module and "claude_agent" not in module


# ---------- terminal label hygiene (round-2: sticky attention label) ----------


def _run_round_at_terminal(proof_ok):
    """Drive loop_driver.run_round to a convergence-eligible round directly."""
    labels, unlabels = [], []
    state = {
        "phase": "awaiting-review",
        "iteration": 1,
        "max_iterations": 8,
        "max_wall_clock_sec": 14400,
        "started_at": "2026-06-05T12:00:00+00:00",
        "last_verdict": "minor-only",
        "transitions": [],
    }
    result = loop_driver.run_round(
        state,
        head_sha="sha1",
        codereview_findings=[],
        reviewed=None,
        unresolved_actionable=0,
        ci_rollup=[],
        config=_CONFIG,
        pr_url=PR,
        label_fn=lambda _u, lbl: labels.append(lbl),
        unlabel_fn=lambda _u, lbl: unlabels.append(lbl),
        proof_ok=proof_ok,
    )
    return result, labels, unlabels


def test_two_stable_terminal_clears_attention_label():
    """CONVERGE applies ready + REMOVES the sticky tp:needs-human-attention
    (round-2 finding: the label is applied on recoverable paths — ci-infra
    hold, F9 escalation — and nothing else ever removes it, so a
    recovered-then-converged EXITED+OPEN run read as fleet 'trouble')."""
    result, labels, unlabels = _run_round_at_terminal(proof_ok=True)
    assert result["terminal"] == "two-stable [code-review-only]"
    assert labels == ["tp:ready-for-human-merge"]
    assert unlabels == ["tp:needs-human-attention"]


def test_blocked_terminal_clears_ready_label():
    """BLOCKED applies attention + REMOVES a stale tp:ready-for-human-merge
    (a prior convergence's label must not read as awaiting-merge after a
    later round blocks on the moved head)."""
    result, labels, unlabels = _run_round_at_terminal(proof_ok=False)
    assert result["terminal"] == "blocked-no-independent-review"
    assert labels == ["tp:needs-human-attention"]
    assert unlabels == ["tp:ready-for-human-merge"]
