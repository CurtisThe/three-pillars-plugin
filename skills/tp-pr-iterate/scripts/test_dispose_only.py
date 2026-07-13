"""Behavior tests for --dispose-only mode of /tp-pr-iterate (T1.3).

Tests:
  - SKILL.md documents --dispose-only in Arguments and describes it as
    "calls the helper once and exits, no iteration."
  - Sending a payload with dispose_only=True calls dispose_threads exactly
    once and does NOT enter the run_round iteration / fix dispatch.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

HERE = Path(__file__).resolve().parent
SKILL_MD = HERE.parent / "SKILL.md"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent.parent / "_shared"))

import run_round  # noqa: E402


# ---------- SKILL.md invariant ----------


def test_dispose_only_in_arguments_section():
    """SKILL.md Arguments section must document --dispose-only."""
    body = SKILL_MD.read_text(encoding="utf-8")
    assert "--dispose-only" in body, (
        "SKILL.md must document --dispose-only in the Arguments section"
    )


def test_dispose_only_description_mentions_helper_and_no_iteration():
    """SKILL.md must state --dispose-only calls the helper once and exits, no iteration."""
    body = SKILL_MD.read_text(encoding="utf-8")
    lower = body.lower()
    assert "dispose-only" in lower, "--dispose-only must be documented"
    # The description must contain 'once' and some form of 'exits' or 'exit'
    # near the dispose-only section
    assert "calls the helper once" in lower or "once and exits" in lower or (
        "dispose_threads" in body and "exits" in lower
    ), (
        "SKILL.md must state --dispose-only calls the helper once and exits"
    )


# ---------- behavior: dispose_only=True calls dispose_threads once and exits ----------


def _make_payload(dispose_only: bool = False, **extra) -> str:
    """Build a minimal valid JSON payload for run_round.main()."""
    payload = {
        "state": {
            "version": "iterate-state.v1",
            "iteration_count": 0,
            "last_verdict": None,
            "last_loop_sha": None,
            "seen_thread_ids": [],
            "resolved_thread_ids": [],
            "cumulative_diff_lines": 0,
            "loop_open_diff_lines": None,
            "consecutive_structural": 0,
            "phase": "running",
        },
        "head_sha": "abc123",
        "codereview_findings": [],
        "reviewed": None,
        "unresolved_actionable": None,
        "ci_rollup": [],
        "pr_url": "https://github.com/o/r/pull/1",
        "dispose_only": dispose_only,
        **extra,
    }
    return json.dumps(payload)


def test_dispose_only_calls_dispose_threads_once(monkeypatch, capsys):
    """dispose_only=True must call dispose_threads (via a fake module) exactly once."""
    call_log = []

    def fake_dispose_threads(pr_url, envelope, **kwargs):
        call_log.append(pr_url)
        return {"replied": [], "resolved": [], "skipped": []}

    # Patch thread_dispose at the sys.modules level so run_round's dynamic
    # import picks up the fake (run_round imports thread_dispose inside
    # _handle_dispose_only to keep the module from being a hard import dep)
    fake_module = MagicMock()
    fake_module.dispose_threads = fake_dispose_threads
    with patch.dict("sys.modules", {"thread_dispose": fake_module}):
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(_make_payload(dispose_only=True))
        try:
            rc = run_round.main()
        finally:
            sys.stdin = old_stdin

    out = capsys.readouterr().out
    assert rc == 0, f"dispose_only mode must exit 0; got rc={rc}"
    envelope = json.loads(out.strip())
    assert envelope.get("action") == "dispose-only", (
        f"dispose_only mode must emit action=dispose-only; got {envelope.get('action')!r}"
    )
    assert call_log == ["https://github.com/o/r/pull/1"], (
        f"dispose_threads must be called exactly once; call_log={call_log}"
    )


def test_dispose_only_does_not_enter_run_round_loop(monkeypatch, capsys):
    """dispose_only=True must NOT call loop_driver.run_round."""
    import loop_driver

    run_round_called = []
    original_run_round = loop_driver.run_round

    def fake_run_round(*args, **kwargs):
        run_round_called.append(True)
        return original_run_round(*args, **kwargs)

    monkeypatch.setattr(loop_driver, "run_round", fake_run_round)

    old_stdin = sys.stdin
    sys.stdin = io.StringIO(_make_payload(dispose_only=True))
    try:
        rc = run_round.main()
    finally:
        sys.stdin = old_stdin

    assert run_round_called == [], (
        "dispose_only=True must NOT call loop_driver.run_round; "
        "the dispose-only path exits before entering the round loop"
    )


def test_dispose_only_false_still_enters_run_round(monkeypatch, capsys):
    """dispose_only=False (normal mode) still enters loop_driver.run_round."""
    import loop_driver

    run_round_called = []
    original_run_round = loop_driver.run_round

    def fake_run_round(*args, **kwargs):
        run_round_called.append(True)
        return original_run_round(*args, **kwargs)

    monkeypatch.setattr(loop_driver, "run_round", fake_run_round)

    old_stdin = sys.stdin
    sys.stdin = io.StringIO(_make_payload(dispose_only=False))
    try:
        rc = run_round.main()
    finally:
        sys.stdin = old_stdin

    # Normal mode SHOULD call loop_driver.run_round
    assert run_round_called, (
        "dispose_only=False (normal mode) must still call loop_driver.run_round"
    )
