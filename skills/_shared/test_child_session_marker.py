"""test_child_session_marker.py — `child_spawn start` marks the `claude -p` child session.

design: seat-escalate-first 3.2 — a spawned child inherits `TP_DESIGN_RUN=1` and the run's
cwd, so the Stop hook could not tell it from the run. `child_spawn.cmd_start` sets
`TP_CHILD_SESSION=1` in the launch env (beside `TP_LOCAL_MODE`) and the hook returns nothing
under it. The rig is `test_child_slot_policy.py`'s fake router module and fake-claude spawn
(imported, not edited). test-fragility.md: assertions are on the env the launcher received
and on the two spellings of the name agreeing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import child_spawn  # noqa: E402
import child_spawn_ops  # noqa: E402
import stop_question_hook  # noqa: E402
from test_child_slot_policy import _Spawn, _fake_module, _seed_parent  # noqa: E402


def test_start_marks_the_child_session(tmp_path, monkeypatch, capsys) -> None:
    """The env `cmd_start` hands `child_proc.launch` carries `TP_CHILD_SESSION=1`."""
    module = _fake_module(tmp_path)
    _seed_parent(tmp_path, module)
    sp = _Spawn(monkeypatch, tmp_path, module)
    try:
        code = child_spawn.main(["start", "--site", "S32", "--agent-ref",
                                 "three-pillars:tp-runbook", "--model", "haiku",
                                 "--prompt-file", str(sp.prompt_file()), "--cwd", str(sp.wt),
                                 "--run", "marker3201"])
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert len(lines) == 1, lines
        assert code == 0, json.loads(lines[0])
        assert len(sp.launches) == 1
        assert sp.launches[0]["env"]["TP_CHILD_SESSION"] == "1"
        assert sp.launches[0]["env"].get("TP_LOCAL_MODE") == "fallback"  # the sibling key stays
    finally:
        sp.cleanup()


def test_the_marker_name_is_one_spelling_in_both_modules() -> None:
    """`child_spawn_ops` exports it and the hook mirrors it; they must never drift."""
    assert child_spawn_ops.CHILD_SESSION_ENV == stop_question_hook.CHILD_SESSION_ENV
    assert child_spawn_ops.CHILD_SESSION_ENV == "TP_CHILD_SESSION"


def test_child_env_itself_stays_unmarked() -> None:
    """The marker is set by `cmd_start` beside `TP_LOCAL_MODE`, not inside `child_env`."""
    assert "TP_CHILD_SESSION" not in child_spawn.child_env({"PATH": "/usr/bin"})
