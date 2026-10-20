"""test_child_prompt_path.py — the child prompt an attempt opens sits inside its own worktree.

design: child-spawn-isolated-ladder-write (task 1.1)

An isolated ``--local`` worker cannot Write under the repo's git **common** dir — the harness
refuses that path — so ``task_verify.py open`` prints a ``child_prompt`` path inside the
attempt's own ``.tp-scratch/child-spawn/`` (already excluded through the shared
``info/exclude``), and ``child_spawn.py start --prompt-file`` accepts it with
``--cwd <attempt_dir>``. The two tests are the example and the differential: the printed path
behaves (in-tree, ignored, discardable), and a start from it records the **same** child state
as a start from the old ``<git-common-dir>/tp-ladder/<slug>/<id>.child-prompt.md``.

Real tmp repos only (``attempt_fixture``; the ambient repo is never read or touched, M23), and
the spawn goes through task 4.1's fake claude, so no live ``claude``, router or GPU job starts.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import child_spawn
import child_state
from attempt_fixture import DD, IDENTITY, SLUG, git, make_seat
from task_scope import _git_env as clean_git_env  # shipped scrub; git_env is dev-only
from test_child_spawn_start import _Spawn  # the fake-claude spawn rig, reaped in teardown

SCRIPT = str(Path(__file__).resolve().parent / "task_verify.py")
AGENT_REF = "three-pillars:tp-runbook"
MODEL = "haiku"
SITE = "S1"
TASK = "1.1"
PROMPT = "Run `git status --porcelain` and report the output.\n"
CHILD_SPAWN_SUBDIR = ".tp-scratch/child-spawn"
# The keys a start records identically from either prompt location.
SHARED_STATE_KEYS = ("cwd", "site", "agent_ref", "model", "state", "permission_mode",
                     "sandbox", "sandbox_state")


def cli(cwd: Path, *args: str) -> tuple[int, dict]:
    """One ``task_verify.py`` call against tmp repos; ``(exit code, its JSON)``."""
    proc = subprocess.run([sys.executable, SCRIPT, *args], cwd=str(cwd), capture_output=True,
                          text=True, env=clean_git_env(**IDENTITY), timeout=300)
    return proc.returncode, json.loads(proc.stdout)


def common_dir(repo: Path) -> Path:
    return Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()


def status(repo: Path) -> str:
    return git(repo, "status", "--porcelain", "-uall")


def open_one_attempt(tmp_path: Path) -> tuple[Path, dict]:
    """A ``make_seat`` repo with one attempt opened off its design worktree -> ``(wt, record)``."""
    _seat, wt = make_seat(tmp_path)
    code, att = cli(wt, "open", "--task", TASK, "--design-dir", DD, "--root", str(wt))
    assert code == 0, att
    return wt, att


def test_open_prints_child_prompt_inside_attempt(tmp_path: Path) -> None:
    """``open`` prints a ``child_prompt`` inside the attempt dir, ignored by git, discardable."""
    wt, att = open_one_attempt(tmp_path)
    adir = Path(att["attempt_dir"]).resolve()
    assert "child_prompt" in att, att
    child_prompt = Path(att["child_prompt"]).resolve()
    assert child_prompt.is_relative_to(adir)
    assert not child_prompt.is_relative_to(common_dir(wt))
    assert child_prompt.parent.is_dir()

    child_prompt.write_text(PROMPT, encoding="utf-8")
    assert status(adir) == ""
    assert status(wt) == ""

    code, res = cli(wt, "discard", "--attempt", att["attempt_id"], "--root", str(wt))
    assert code == 0, res
    assert not adir.exists()
    assert status(wt) == ""


def test_start_accepts_child_prompt_same_state(monkeypatch, tmp_path: Path) -> None:
    """A start from the printed path matches a start from the old ladder path, state for state."""
    _wt, att = open_one_attempt(tmp_path)
    adir = Path(att["attempt_dir"]).resolve()
    spawn = tmp_path / "spawn"  # _Spawn builds its own repo here, away from make_seat's
    spawn.mkdir()
    sp = _Spawn(monkeypatch, spawn)
    states: dict[str, dict] = {}
    try:
        in_tree = Path(att["child_prompt"])
        ladder = common_dir(adir) / "tp-ladder" / SLUG / f"{TASK}.child-prompt.md"
        for path in (in_tree, ladder):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(PROMPT, encoding="utf-8")
        for name, run in (("in_tree", "ptin0001"), ("ladder", "ptld0002")):
            prompt = in_tree if name == "in_tree" else ladder
            res = child_spawn.cmd_start(SITE, AGENT_REF, MODEL, str(prompt), cwd=str(adir),
                                        run=run)
            assert res["state"] == "running", res
            assert res["inner_agent_id"]
            states[name] = child_state.read(res["state_path"])
    finally:
        sp.cleanup()

    assert set(states["in_tree"]) == set(states["ladder"])
    for key in SHARED_STATE_KEYS:
        assert states["in_tree"][key] == states["ladder"][key], key
    for name in states:
        copy = Path(states[name]["prompt_path"])
        assert copy.is_relative_to(adir / CHILD_SPAWN_SUBDIR)
        assert copy.read_bytes() == PROMPT.encode("utf-8")
