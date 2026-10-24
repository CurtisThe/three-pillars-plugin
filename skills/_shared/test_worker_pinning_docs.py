"""Doc pins: a tp-worker without harness isolation is pinned to its WORKTREE by prompt and check.

design: classifier-no-verdict-nested-writes (Task 1.3)
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_tp_worker_pins_every_command_and_path_to_the_worktree():
    text = _read("agents/tp-worker.md")
    for token in ("WORKTREE:", "cd <WORKTREE> &&", "absolute", "worker_root.py verify"):
        assert token in text, token


def test_tp_worker_no_longer_assumes_harness_isolation():
    assert 'under `isolation="worktree"`' not in _read("agents/tp-worker.md")


def test_local_dispatch_does_not_call_the_tp_worker_isolated():
    assert "worktree-isolated `tp-worker`" not in _read("skills/_shared/local-dispatch.md")


def test_local_reaper_takes_the_worktree_path_from_open():
    text = _read("skills/_shared/local-reaper.md")
    item = text[text.index("5. **`agent_meta.worktreePath`**"):text.index("Inside the worker nothing changes")]
    assert "worker_root.py open" in item
    assert ".claude/worktrees" not in item


def test_the_bg_wait_follow_up_runs_behind_the_worktree_prefix():
    text = _read("agents/tp-worker.md")
    assert "cd <WORKTREE> && python3 <TP>/skills/_shared/bg_wait.py --marker <M>" in text
