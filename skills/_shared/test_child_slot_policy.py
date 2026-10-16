"""test_child_slot_policy.py — the child session's busy-policy note and router capability.

design: strata-session-isolation (task 2.4)

A child session talks to the local router with its OWN session id, so the note the
lease wrote for ``$CLAUDE_CODE_SESSION_ID`` does not cover it: under ``wait`` a
request the router cannot admit would go upstream to Sonnet. ``child_slot.note_policy``
writes the same ``busy-policy.json`` entry keyed by the child, and
``child_slot.can_release_session`` answers whether the router install has the
``SlotOwner.release_session`` the release path needs. Every test drives a fake
``slot_owner`` module whose state path is under ``tmp_path`` (the
``test_local_lease*.py`` stub pattern) — nothing here reads or writes the live
router state. test-fragility.md: assertions are on the parsed policy file and the
returned booleans, never on the warning's wording beyond "one line, naming wait".
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import child_proc  # noqa: E402
import child_slot  # noqa: E402
import child_spawn  # noqa: E402
import local_lease  # noqa: E402
import router_busy_policy as rbp  # noqa: E402
import stopped_agents  # noqa: E402
from attempt_fixture import commit, git  # noqa: E402
from child_spawn_fixture import fake_inner_id, write_fake_claude  # noqa: E402

CHILD = "child-uuid-0001"
PARENT = "parent-session-0002"


def _fake_module(tmp_path, *, release_session=False):
    """A fake ``slot_owner`` module: its ``SlotOwner`` instance names a state path
    under ``tmp_path``, and carries ``release_session`` only when asked."""
    state = tmp_path / "router" / "slot-state.json"

    class Owner:
        def __init__(self):
            self.state_path = str(state)

    if release_session:
        def _release_session(self, endpoint, key):
            return True

        Owner.release_session = _release_session
    return types.SimpleNamespace(SlotOwner=Owner)


def _policy_of(tmp_path, module, child=CHILD) -> str:
    """The policy the note wrote for ``child``, read where the router reads it."""
    path = Path(rbp.path_for(module.SlotOwner().state_path))
    return json.loads(path.read_text(encoding="utf-8"))[child]["policy"]


def test_wait_policy_written_for_child(tmp_path, monkeypatch):
    """``TP_LOCAL_MODE=wait`` is the run's effective policy and lands under the child key."""
    module = _fake_module(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert child_slot.note_policy(CHILD, env={"TP_LOCAL_MODE": "wait"}, module=module) is True
    assert _policy_of(tmp_path, module) == "wait"


def test_fallback_default(tmp_path, monkeypatch):
    """No env and no repo config (empty cwd) -> the ``fallback`` default."""
    module = _fake_module(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert child_slot.note_policy(CHILD, env={}, module=module) is True
    assert _policy_of(tmp_path, module) == "fallback"


def test_override_wins(tmp_path, monkeypatch):
    """An explicit override beats the env and the config."""
    module = _fake_module(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert child_slot.note_policy(CHILD, override="wait", env={}, module=module) is True
    assert _policy_of(tmp_path, module) == "wait"


def test_not_written_warns_under_wait(tmp_path, monkeypatch, capsys):
    """No router module -> False, and under ``wait`` exactly one stderr line (the case where a
    refused request would silently go to Sonnet); under ``fallback`` silence."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(local_lease, "slot_owner_module", lambda which=shutil.which: None)
    assert child_slot.note_policy(CHILD, env={"TP_LOCAL_MODE": "wait"}, module=None) is False
    lines = [ln for ln in capsys.readouterr().err.splitlines() if ln.strip()]
    assert len(lines) == 1 and "wait" in lines[0]
    assert child_slot.note_policy(CHILD, env={}, module=None) is False
    assert capsys.readouterr().err == ""


def test_can_release_session(tmp_path):
    """The capability check follows the router module: method present -> True, absent or no
    router install -> False."""
    assert child_slot.can_release_session(
        module=_fake_module(tmp_path, release_session=True)) is True
    assert child_slot.can_release_session(module=_fake_module(tmp_path)) is False
    assert child_slot.can_release_session(which=lambda _name: None) is False


# --- task 5.1 (strata-spend-leaks): the child inherits the PARENT's recorded policy ---------
#
# The lease already recorded this run's policy keyed by the parent's ``CLAUDE_CODE_SESSION_ID``.
# Re-deriving the child's policy from the env and the repo config instead let a parent whose env no
# longer says what the run decided (the launcher's scrub, another folder's ``strata_spawn.busy``)
# record something else for the child — under ``wait`` the Sonnet leak this design closes. So the
# parent's entry wins when it exists, an explicit override still beats it, and the launch env
# carries the resolved policy as ``TP_LOCAL_MODE`` so the child never re-derives it on its own.


def _seed_parent(tmp_path, module, policy="fallback") -> None:
    """Write the parent session's entry exactly as the lease writes it."""
    assert rbp.record(module.SlotOwner().state_path, PARENT, policy) is True


def test_child_policy_follows_parent_record(tmp_path, monkeypatch):
    """No override: the parent's recorded policy beats the env this spawn sees."""
    module = _fake_module(tmp_path)
    _seed_parent(tmp_path, module)
    monkeypatch.chdir(tmp_path)
    env = {"TP_LOCAL_MODE": "wait", "CLAUDE_CODE_SESSION_ID": PARENT}
    assert child_slot.note_policy(CHILD, env=env, module=module) is True
    assert _policy_of(tmp_path, module) == "fallback"


def test_child_policy_override_wins(tmp_path, monkeypatch):
    """An explicit override still beats the parent's record and the env."""
    module = _fake_module(tmp_path)
    _seed_parent(tmp_path, module)
    monkeypatch.chdir(tmp_path)
    env = {"TP_LOCAL_MODE": "wait", "CLAUDE_CODE_SESSION_ID": PARENT}
    assert child_slot.note_policy(CHILD, override="wait", env=env, module=module) is True
    assert _policy_of(tmp_path, module) == "wait"


def test_parent_record_absent_uses_env(tmp_path, monkeypatch):
    """No entry for the parent key (or an unreadable policy file) -> today's env resolution."""
    module = _fake_module(tmp_path)
    monkeypatch.chdir(tmp_path)
    env = {"TP_LOCAL_MODE": "wait", "CLAUDE_CODE_SESSION_ID": PARENT}
    assert child_slot.note_policy(CHILD, env=env, module=module) is True
    assert _policy_of(tmp_path, module) == "wait"
    Path(rbp.path_for(module.SlotOwner().state_path)).write_text("{ not json", encoding="utf-8")
    assert child_slot.note_policy(CHILD, env=env, module=module) is True
    assert _policy_of(tmp_path, module) == "wait"


def test_resolved_policy_helper(tmp_path, monkeypatch):
    """``resolved_policy`` answers a policy from the closed set for every lookup, never raises."""
    monkeypatch.chdir(tmp_path)
    env = {"TP_LOCAL_MODE": "wait", "CLAUDE_CODE_SESSION_ID": PARENT}
    monkeypatch.setattr(local_lease, "slot_owner_module", lambda which=shutil.which: None)
    assert child_slot.resolved_policy(env=env, module=None) in rbp.POLICIES
    module = _fake_module(tmp_path)
    _seed_parent(tmp_path, module)
    assert child_slot.resolved_policy(env=env, module=module) == "fallback"
    assert child_slot.resolved_policy(override="wait", env=env, module=module) == "wait"


class _Spawn:
    """One real ``start`` against the fake claude, capturing the env handed to the launcher."""

    def __init__(self, monkeypatch, tmp_path: Path, module):
        self.tmp = tmp_path
        self.repo = tmp_path / "repo"
        self.wt = tmp_path / "wt"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        commit(self.repo, {"README.md": "demo\n"}, "base")
        git(self.repo, "worktree", "add", "-q", "-b", "wt", str(self.wt))
        self.launches: list = []

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", PARENT)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.setenv("TP_CHILD_SPAWN_CLAUDE", str(write_fake_claude(tmp_path / "bin")))
        monkeypatch.setenv("TP_CHILD_MAX_S", "600")
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "linger")
        monkeypatch.setenv("FAKE_SLEEP_S", "30")
        monkeypatch.setenv("TP_CHILD_RESOLVE_S", "20")
        monkeypatch.setenv("TP_LOCAL_MODE", "wait")
        monkeypatch.setattr(local_lease, "slot_owner_module", lambda which=shutil.which: module)
        monkeypatch.setattr(stopped_agents, "append", lambda *a, **k: "skipped")

        real_launch = child_proc.launch

        def launch(argv, cwd, out_path, env):
            rec = real_launch(argv, cwd, out_path, env)
            self.launches.append({"argv": argv, "cwd": cwd, "out_path": out_path,
                                  "env": env, "rec": rec})
            return rec

        monkeypatch.setattr(child_proc, "launch", launch)

    def prompt_file(self) -> Path:
        path = self.tmp / "prompt.md"
        path.write_text("Run `git status --porcelain` and report the output.\n", encoding="utf-8")
        return path

    def cleanup(self) -> None:
        """Signal only the group this test launched, then wait for it to be gone."""
        for entry in self.launches:
            info = entry["rec"]
            if "pid" not in info:
                continue
            pid, ticks = int(info["pid"]), int(info["start_ticks"] or 0)
            child_proc.stop_group(pid, int(info["pgid"]), ticks, grace_s=2)
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and child_proc.alive(pid, ticks):
                time.sleep(0.05)


def test_child_env_carries_resolved_policy(tmp_path, monkeypatch, capsys) -> None:
    """The env ``cmd_start`` hands ``child_proc.launch`` names the policy the note used."""
    module = _fake_module(tmp_path)
    _seed_parent(tmp_path, module)
    sp = _Spawn(monkeypatch, tmp_path, module)
    try:
        code = child_spawn.main(["start", "--site", "S51", "--agent-ref",
                                 "three-pillars:tp-runbook", "--model", "haiku",
                                 "--prompt-file", str(sp.prompt_file()), "--cwd", str(sp.wt),
                                 "--run", "start5101"])
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert len(lines) == 1, lines
        res = json.loads(lines[0])
        assert code == 0, res
        assert res["inner_agent_id"] == fake_inner_id(res["child_session"])
        assert len(sp.launches) == 1
        assert sp.launches[0]["env"].get("TP_LOCAL_MODE") == "fallback"
        assert _policy_of(tmp_path, module, res["child_session"]) == "fallback"
    finally:
        sp.cleanup()
