"""Tests for child_spawn.py — the `probe` subcommand.

strata-session-isolation task 3.3 (design §B8, detailed-design §CLI `probe`): `probe [--run R]`
answers one JSON line — `{"mode": "child"|"in-process", "why": …}` — exiting 0 for `child` and 4 for
`in-process`. The `why` is the FIRST unmet prerequisite in the design's order (`TP_CHILD_SPAWN=0`,
no claude CLI on `PATH`, no `timeout`, no `/proc`, a router without `release_session`), so a site
reading the line gets one actionable reason instead of a list. On an all-pass it runs
`sweep --stale` for this repo (reaping any past-deadline leftover of a crashed run) before its
smoke verdict, and the answer is cached in that run's `probe.json`, so a run pays for the checks
once — a second `probe` in the same run reads the cache and sweeps no second time.

Every prerequisite is monkeypatched on its own module (`shutil.which`, `child_proc.has_proc`,
`child_slot.can_release_session`, and `child_spawn.cmd_sweep`), so no test starts a process at all:
no `claude`, no router, no GPU job, and nothing named for a kill tool to match. Each test builds a
real tmp repo with `attempt_fixture`'s scrubbed git env BEFORE patching, and passes it as `--root`
with a fixed `--run`, so its `probe.json` lands inside that repo and never the ambient one.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_proc  # noqa: E402
import child_slot  # noqa: E402
import child_spawn  # noqa: E402
import child_state  # noqa: E402
from attempt_fixture import commit, git  # noqa: E402

RUN = "probe0123"
ALL_OK = ("claude", "timeout")


def _repo(tmp_path: Path) -> Path:
    """A real tmp repo with one commit, on branch `main`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"README.md": "demo\n"}, "base")
    return repo


def _probe(monkeypatch, repo: Path, capsys, *, ok=ALL_OK, has_proc=True, can_release=True,
           spawn_off=False, claude_env=None) -> tuple[int, dict, list]:
    """Patch every prerequisite, run `probe`, return `(exit code, payload, sweep stale flags)`.

    `ok` is the set of names the fake `shutil.which` resolves; the other three checks answer
    whatever the test asks for. Both spawn env vars are cleared first, so a test opts in to
    `TP_CHILD_SPAWN` / `TP_CHILD_SPAWN_CLAUDE` instead of inheriting the real environment.
    """
    calls: list = []
    monkeypatch.delenv("TP_CHILD_SPAWN", raising=False)
    monkeypatch.delenv("TP_CHILD_SPAWN_CLAUDE", raising=False)
    if spawn_off:
        monkeypatch.setenv("TP_CHILD_SPAWN", "0")
    if claude_env:
        monkeypatch.setenv("TP_CHILD_SPAWN_CLAUDE", claude_env)
    allowed = set(ok)
    monkeypatch.setattr(shutil, "which",
                        lambda name, *a, **k: f"/usr/bin/{name}" if name in allowed else None)
    monkeypatch.setattr(child_proc, "has_proc", lambda: has_proc)
    monkeypatch.setattr(child_slot, "can_release_session", lambda *a, **k: can_release)

    def fake_sweep(run=None, stale=False, root="."):
        calls.append(stale)
        return {"stopped": [], "gone": []}

    monkeypatch.setattr(child_spawn, "cmd_sweep", fake_sweep)
    code = child_spawn.main(["probe", "--run", RUN, "--root", str(repo)])
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines, "probe printed no JSON line"
    return code, json.loads(lines[-1]), calls


def _in_process(monkeypatch, tmp_path, capsys, why: str, **kw) -> None:
    """One reason: exit 4, `mode` in-process, and that exact `why`."""
    repo = _repo(tmp_path)
    code, res, calls = _probe(monkeypatch, repo, capsys, **kw)
    assert code == 4
    assert res["mode"] == "in-process"
    assert res["why"] == why
    assert calls == []  # a failed prerequisite never reaches the stale sweep


def test_off_env(monkeypatch, tmp_path, capsys) -> None:
    _in_process(monkeypatch, tmp_path, capsys, "off (TP_CHILD_SPAWN=0)", spawn_off=True)
    # the answer is cached either way, so the site's next probe reads it
    assert (child_state.run_dir(RUN, root=tmp_path / "repo") / "probe.json").exists()


def test_no_claude_cli(monkeypatch, tmp_path, capsys) -> None:
    _in_process(monkeypatch, tmp_path, capsys, "no claude CLI", ok=("timeout",))


def test_no_timeout(monkeypatch, tmp_path, capsys) -> None:
    _in_process(monkeypatch, tmp_path, capsys, "no timeout", ok=("claude",))


def test_no_proc(monkeypatch, tmp_path, capsys) -> None:
    _in_process(monkeypatch, tmp_path, capsys, "no /proc", has_proc=False)


def test_router_lacks_release_session(monkeypatch, tmp_path, capsys) -> None:
    _in_process(monkeypatch, tmp_path, capsys, "router lacks release_session", can_release=False)


def test_order_first_reason_wins(monkeypatch, tmp_path, capsys) -> None:
    # no claude AND no /proc: the CLI reason is the one the site sees
    _in_process(monkeypatch, tmp_path, capsys, "no claude CLI", ok=("timeout",), has_proc=False)


def test_all_present_is_child_and_sweeps_once(monkeypatch, tmp_path, capsys) -> None:
    repo = _repo(tmp_path)
    calls: list = []
    monkeypatch.delenv("TP_CHILD_SPAWN", raising=False)
    monkeypatch.setattr(shutil, "which",
                        lambda name, *a, **k: f"/usr/bin/{name}" if name in ("fake-claude",
                                                                             "timeout") else None)
    monkeypatch.setattr(child_proc, "has_proc", lambda: True)
    monkeypatch.setattr(child_slot, "can_release_session", lambda *a, **k: True)

    def fake_sweep(run=None, stale=False, root="."):
        calls.append(stale)
        return {"stopped": [], "gone": []}

    monkeypatch.setattr(child_spawn, "cmd_sweep", fake_sweep)
    # The smoke verdict (task 4.7) runs after the sweep on an all-pass; stub it so this test
    # starts no process and pins only what task 3.3 owns: mode, one sweep, the per-run cache.
    monkeypatch.setattr(child_spawn, "claude_version", lambda *a, **k: "9.9.9-test")
    monkeypatch.setattr(child_spawn, "cmd_smoke",
                        lambda *a, **k: {"ok": True, "why": "smoke passed",
                                         "claude_version": "9.9.9-test"})
    monkeypatch.setenv("TP_CHILD_SPAWN_CLAUDE", "fake-claude")

    for _ in range(2):  # the second probe reads probe.json instead of re-checking and re-sweeping
        code = child_spawn.main(["probe", "--run", RUN, "--root", str(repo)])
        line = capsys.readouterr().out.strip().splitlines()[-1]
        assert code == 0
        assert json.loads(line)["mode"] == "child"

    assert calls == [True]
    assert (child_state.run_dir(RUN, root=repo) / "probe.json").exists()
