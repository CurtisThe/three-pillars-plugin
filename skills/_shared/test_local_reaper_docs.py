"""test_local_reaper_docs.py — `local-reaper.md`, the main-thread reaper protocol
(m44-orphan-reaper Task 3.1).

A nested `tp-worker` cannot stop its own runaway local attempt (the harness
refuses its `TaskStop`), so only a main thread stops it: the full-design
orchestrator through a background `attempt_reaper.py watch` loop, the
interactive dispatcher through its own `TaskStop` plus a phase-end sweep. Both
record the stop with `attempt_watchdog.py stopped`; the tp-worker only
orphan-marks. Pinned by token, not prose (the style of
`test_consumer_offers_handoffs.py`).
"""
from __future__ import annotations

from pathlib import Path

_SHARED = Path(__file__).resolve().parent
_DOC = _SHARED / "local-reaper.md"
MAX_LINES = 120


def _doc() -> str:
    return _DOC.read_text(encoding="utf-8")


def _section(name: str) -> str:
    """Body of the `## <name>` section, up to the next `## ` heading."""
    out, inside, found = [], False, False
    for line in _doc().splitlines():
        if line.startswith("## "):
            inside = line[3:].startswith(name)
            found = found or inside
            continue
        if inside:
            out.append(line)
    assert found, f"missing section: ## {name}"
    return "\n".join(out)


def test_doc_is_short():
    assert len(_doc().splitlines()) <= MAX_LINES


def test_full_design_dispatches_the_worker_in_background_under_local_only():
    body = _section("Full-design")
    assert "run_in_background=True" in body
    assert "`--local` only" in body


def test_full_design_watch_call():
    body = _section("Full-design")
    for token in (
        "attempt_reaper.py watch --dir",
        "--worker-agent-id",
        "--for",
        "timeout 7200000",
        "ladder_files.py paths --slug",
    ):
        assert token in body, token


def test_full_design_stops_records_and_sweeps():
    body = _section("Full-design")
    for token in (
        "TaskStop(",
        "attempt_watchdog.py stopped --state",
        "attempt_reaper.py sweep",
        "Tier 3.5",
    ):
        assert token in body, token


def test_full_design_worktree_path_source_order():
    body = _section("Full-design")
    assert "agent_meta.worktreePath" in body
    first = body.index("worker_root.py open")
    second = body.index("missing-worktree")
    assert first < second
    assert ".claude/worktrees/agent-<id>" not in body


def test_interactive_records_its_own_stop():
    body = _section("Interactive")
    assert "TaskStop(" in body
    assert "--result ok" in body
    assert "attempt_watchdog.py stopped --state" in body


def test_interactive_retries_taskstop_once_after_orphan_mark():
    body = _section("Interactive")
    assert "orphan-mark" in body
    assert "once" in body


def test_interactive_sweeps_at_phase_end_and_on_env_error():
    body = _section("Interactive")
    for token in ("attempt_reaper.py sweep", "phase end", "before step 6", "env-error"):
        assert token in body, token


def test_worker_never_records_a_stop():
    text = _doc()
    assert "never calls `attempt_watchdog.py stopped`" in text
    assert "only orphan-marks" in text


def test_fail_open_rule_is_one_decisions_line():
    body = _section("Fail-open")
    for token in (
        "one decisions line",
        "`watch`",
        "`sweep`",
        "`stopped`",
        "`TaskStop`",
        "no-router",
        "never blocks",
    ):
        assert token in body, token


def test_backstop_names_the_stopped_agents_file():
    body = _section("Backstop")
    for token in ("stopped-agents", "STOPPED-AGENT", "no-router", "every result"):
        assert token in body, token


def test_cost_rule_is_one_background_call():
    body = _section("Cost rule")
    for token in (
        "seat ruling 2026-10-02",
        "**background**",
        "run_in_background",
        "Monitor",
        "--for",
        "never a foreground",
        "zero turns",
        "relaunch",
    ):
        assert token in body, token


def test_full_design_hand_back_only_on_completion_notification():
    """Audit M1: `worker_done` alone relaunches `watch`; only the completion
    notification triggers the hand-back sweep, which first stops the watch."""
    body = _section("Full-design")
    for token in ("never the hand-back trigger", "**completion notification** is the only trigger",
                  "Stop the\n   still-running background `watch`"):
        assert token in body, token


def test_stop_and_record_names_the_reap_target_agent():
    """Audit m1: W is shared per task, so `stopped` takes the target's agent id
    and `backstop` is logged from its printed JSON."""
    text = _doc()
    assert "stopped --state <W> --agent-id <agent_id> --result" in text
    assert '"w_reused": true' in text
    assert "never a re-read of W" in text
    assert text.count("--agent-id <agent") >= 4
