"""test_ladder_sweep.py — stale ladder side files are cleared, live ones kept (seat G4).

design: run-throughput (PR #178 live check #2 item 3). A fixture repo's
`<git-common-dir>/tp-ladder/demo/` carries a prior run's C/P/F/S/W files (the live
check's `stale-ladder` shapes, scrubbed); `task_verify.py sweep` and `ladder_files.py
paths --fresh` must leave only files a live attempt or a still-running orphan owns.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import attempt_watchdog as aw  # noqa: E402
from attempt_fixture import DD, IDENTITY, git, make_seat  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402

CASES = json.loads((HERE / "fixtures" / "transcript_tail" / "tails.json")
                   .read_text(encoding="utf-8"))["cases"]
SIDES = (".check.json", ".scan.json", ".reply.txt", ".watch.json", ".poll.json")


def _run(script: str, cwd: Path, *args: str, cfg: Path) -> tuple[int, dict]:
    env = clean_git_env(**IDENTITY, CLAUDE_CONFIG_DIR=str(cfg))
    proc = subprocess.run([sys.executable, str(HERE / script), *args], cwd=str(cwd),
                          capture_output=True, text=True, env=env, timeout=120)
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else {})


def _ladder(wt: Path) -> Path:
    common = Path(git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    ldir = common / "tp-ladder" / "demo"
    ldir.mkdir(parents=True)
    return ldir


def _task_files(ldir: Path, task: str, *, agent: str, orphan: bool = False) -> None:
    (ldir / f"{task}.json").write_text(json.dumps({"task_id": task, "final": "done"}))
    for side in (".check.json", ".scan.json", ".poll.json"):
        (ldir / f"{task}{side}").write_text("{}\n")
    (ldir / f"{task}.reply.txt").write_text('{"claimed": "green"}\n')
    aw.arm(ldir / f"{task}.watch.json", attempt_id=f"demo/{task}-0bcad012", agent_id=agent,
           rung="local-medium", phase="1", router_log=None, now=0.0)
    if orphan:
        aw.mark_orphan(ldir / f"{task}.watch.json")


def _transcript(cfg: Path, agent: str, case: str) -> None:
    sub = cfg / "projects" / "proj" / "sess" / "subagents"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / f"agent-{agent}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in CASES[case]) + "\n", encoding="utf-8")


def _live_record(wt: Path, seat: Path, task: str) -> None:
    """An attempt record whose owner (the seat) is still a registered worktree."""
    common = Path(git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    rec_dir = common / "tp-attempts" / "demo"
    rec_dir.mkdir(parents=True, exist_ok=True)
    (rec_dir / f"{task}-live0001.json").write_text(json.dumps({
        "attempt_id": f"demo/{task}-live0001", "task_id": task, "status": "open",
        "owner": {"dispatcher_root": str(seat)}, "attempt_dir": "", "branch": ""}))


def _left(ldir: Path) -> set:
    return {p.name for p in ldir.iterdir()}


def test_sweep_clears_done_and_discarded_keeps_live_and_running_orphans(tmp_path):
    seat, wt = make_seat(tmp_path)
    cfg = tmp_path / "cfg"
    ldir = _ladder(wt)
    _task_files(ldir, "1.1", agent="a0000011")                  # done, prior run
    _task_files(ldir, "1.2", agent="a0000012")                  # another dispatcher's live attempt
    _task_files(ldir, "1.3", agent="a0000013", orphan=True)     # orphan, agent finished
    _task_files(ldir, "1.4", agent="a0000014", orphan=True)     # orphan, agent still running
    _transcript(cfg, "a0000013", "end_turn_trailing")
    _transcript(cfg, "a0000014", "mid_tool_call")
    _live_record(wt, seat, "1.2")
    (ldir / "stops.ndjson").write_text('{"v": 1}\n')            # the durable stop record (M3)

    rc, out = _run("task_verify.py", wt, "sweep", "--design-dir", DD, cfg=cfg)
    assert rc == 0
    assert _left(ldir) == ({f"1.{n}.json" for n in range(1, 5)}          # R never removed
                           | {f"1.2{s}" for s in SIDES} | {"1.4.watch.json", "stops.ndjson"})
    assert out["ladder"]["kept_orphans"] == [str(ldir / "1.4.watch.json")]
    assert str(ldir / "1.1.check.json") in out["ladder"]["removed"]

    # The orphans check the next phase-1 attempt runs no longer sees the finished one.
    orphans = aw.orphans(ldir, phase="1", config_dir=cfg)
    assert [o["attempt_id"] for o in orphans["orphans"]] == ["demo/1.4-0bcad012"]


def test_sweep_with_no_ladder_dir_is_empty(tmp_path):
    _seat, wt = make_seat(tmp_path)
    rc, out = _run("task_verify.py", wt, "sweep", "--design-dir", DD, cfg=tmp_path / "cfg")
    assert rc == 0 and out["ladder"] == {"removed": [], "kept_orphans": []}


def test_paths_fresh_clears_prior_attempt_side_files_only_for_that_task(tmp_path):
    _seat, wt = make_seat(tmp_path)
    cfg = tmp_path / "cfg"
    ldir = _ladder(wt)
    _task_files(ldir, "2.1", agent="a0000021")
    _task_files(ldir, "2.2", agent="a0000022")
    (ldir / "stops.ndjson").write_text('{"v": 1}\n')
    rc, out = _run("ladder_files.py", wt, "paths", "--slug", "demo", "--task", "2.1", "--fresh",
                   cfg=cfg)
    assert rc == 0 and out["dir"] == str(ldir)
    assert out["record"] == str(ldir / "2.1.json") and out["poll"] == str(ldir / "2.1.poll.json")
    assert _left(ldir) == {"2.1.json", "2.2.json", "stops.ndjson"} | {f"2.2{s}" for s in SIDES}
    assert sorted(out["cleared"]["removed"]) == sorted(str(ldir / f"2.1{s}") for s in SIDES)


def test_paths_creates_the_dir_and_refuses_a_path_slug(tmp_path):
    _seat, wt = make_seat(tmp_path)
    rc, out = _run("ladder_files.py", wt, "paths", "--slug", "demo", cfg=tmp_path / "cfg")
    assert rc == 0 and Path(out["dir"]).is_dir() and out["dir"].endswith("/tp-ladder/demo")
    rc, _ = _run("ladder_files.py", wt, "paths", "--slug", "../x", cfg=tmp_path / "cfg")
    assert rc == 2


def test_durable_stops_file_matches_no_side_suffix():
    import ladder_files
    import stopped_agents
    assert ladder_files.STOPS == stopped_agents.LADDER_STOPS
    assert ladder_files._task_of(ladder_files.STOPS) is None
