"""Task 7.3: the agent_caps CLI exposes spawned/watch over any slot root.

design: review-convergence (Task 7.3), detailed-design-caps.md §The watch loop.
The CLI is driven with the real clock, so `--started` is relative to
`time.time()`. Assertions are on parsed verdict/slot fields only
(skills/_shared/test-fragility.md). `--once` is always passed: the loop without
it never exits.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_caps  # noqa: E402

HARD = 1500  # agent_caps._DEFAULT.hard_s


def lines(capsys):
    out = capsys.readouterr().out
    return [json.loads(l) for l in out.splitlines() if l.startswith("{")]


def spawned(root, slot, agent_id, started, role="review_finder"):
    return agent_caps.main(["spawned", "--slot-root", str(root), "--slot", slot,
                            "--agent-id", agent_id, "--started", str(started),
                            "--role", role])


def watch(root, role="review_finder"):
    return agent_caps.main(["watch", "--slot-root", str(root), "--role", role,
                            "--once"])


def test_council_run_dir_wrap_up_then_stop(tmp_path, capsys):
    root = tmp_path / "council-run"
    assert spawned(root, "feynman", "m-feynman", time.time() - 1000,
                   "council_member") == 0
    capsys.readouterr()
    assert watch(root, "council_member") == 0
    got = lines(capsys)
    assert [g["verdict"] for g in got] == ["wrap-up"]
    assert got[0]["slot"] == "feynman"
    assert spawned(root, "ada", "m-ada", time.time() - (HARD + 100),
                   "council_member") == 0
    capsys.readouterr()
    assert watch(root, "council_member") == 0
    assert [(g["verdict"], g["slot"]) for g in lines(capsys)] == [("stop", "ada")]
    assert watch(root, "council_member") == 0  # feynman's wrap-up was already warned
    assert lines(capsys) == []


def test_per_phase_scratch_root_default_role(tmp_path, capsys):
    root = tmp_path / "phase-check" / "finder"
    assert spawned(root, "s1", "a1", time.time() - (HARD + 10)) == 0
    capsys.readouterr()
    assert watch(root) == 0
    assert [(g["verdict"], g["slot"]) for g in lines(capsys)] == [("stop", "s1")]


def test_existing_subcommands_unaffected(capsys):
    assert agent_caps.main(["budget-line"]) == 0
    assert "Budget:" in capsys.readouterr().out
