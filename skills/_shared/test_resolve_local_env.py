"""test_resolve_local_env.py — `TP_LOCAL` as an input to `resolve_local`.

design: design-run-launch-defaults (Behavior 1): flag > TP_LOCAL > repo key > off.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cheap_tier_default as ctd  # noqa: E402
import launch_design_run as ldr  # noqa: E402

BLOCK = {"enabled": True, "full_design": True}
NO_KEY = {"local_implement": dict(BLOCK)}
KEY_ON = {"local_implement": dict(BLOCK, default_run_flag="on")}


@pytest.fixture(autouse=True)
def gate_passes(monkeypatch):
    monkeypatch.setattr(
        ctd.lic, "load_capability",
        lambda path: {"nested": {"background_spawn_ok": True, "done_detected": True}})


def _local(cfg, env, **flags):
    return ctd.resolve_local(cfg, env=env, **flags)


def test_flags_beat_the_env():
    assert _local({}, {"TP_LOCAL": "off"}, local=True) is True
    assert _local(NO_KEY, {"TP_LOCAL": "on"}, no_local=True) is False


def test_env_on_needs_no_default_run_flag():
    assert _local(NO_KEY, {"TP_LOCAL": "on"}) is True


def test_env_beats_the_repo_key():
    assert _local(KEY_ON, {"TP_LOCAL": "off"}) is False


@pytest.mark.parametrize("value", ["garbage", "ON", " on", "on ", "1"])
def test_other_values_are_off_even_with_the_repo_key_on(value):
    assert _local(KEY_ON, {"TP_LOCAL": value}) is False


@pytest.mark.parametrize("env", [{}, {"TP_LOCAL": ""}])
def test_unset_or_empty_falls_through_to_the_repo_key(env):
    assert _local(KEY_ON, env) is True
    assert _local(NO_KEY, env) is False


@pytest.mark.parametrize("cfg", [
    {}, None, {"local_implement": None},
    {"local_implement": {"enabled": False, "full_design": True}},
    {"local_implement": {"enabled": True}},
])
def test_env_on_is_still_gated_by_the_block(cfg):
    assert _local(cfg, {"TP_LOCAL": "on"}) is False


def test_env_on_is_gated_by_the_capability(monkeypatch):
    monkeypatch.setattr(
        ctd.lic, "load_capability",
        lambda path: {"nested": {"background_spawn_ok": None, "done_detected": None}})
    assert _local(NO_KEY, {"TP_LOCAL": "on"}) is False


def test_default_env_is_os_environ(monkeypatch):
    monkeypatch.setenv("TP_LOCAL", "on")
    assert ctd.resolve_local(NO_KEY) is True
    monkeypatch.delenv("TP_LOCAL")
    assert ctd.resolve_local(NO_KEY) is False


def test_env_local_note():
    assert ctd.env_local_note(NO_KEY, {}) is None
    assert ctd.env_local_note(NO_KEY, {"TP_LOCAL": ""}) is None
    assert ctd.env_local_note(NO_KEY, {"TP_LOCAL": "on"}) is None
    assert ctd.env_local_note(NO_KEY, {"TP_LOCAL": "off"}).startswith("warning:")
    assert ctd.env_local_note(NO_KEY, {"TP_LOCAL": "garbage"}).startswith("warning:")
    for cfg in ({}, {"local_implement": {"enabled": False, "full_design": True}}):
        note = ctd.env_local_note(cfg, {"TP_LOCAL": "on"})
        assert note.startswith("warning:") and "TP_LOCAL" in note


def test_env_local_note_garbage_says_it_overrides_the_repo_default():
    note = ctd.env_local_note(NO_KEY, {"TP_LOCAL": "garbage"})
    assert "treated as off" in note and "overrides local_implement.default_run_flag" in note


def test_env_local_note_is_silent_when_an_explicit_flag_decides():
    for env in ({"TP_LOCAL": "garbage"}, {"TP_LOCAL": "on"}):
        assert ctd.env_local_note({}, env, local=True) is None
        assert ctd.env_local_note({}, env, no_local=True) is None


# --- launcher (dry-run, env injected) -----------------------------------------

def _dry_run(tmp_path, monkeypatch, capsys, cfg_json, tp_local):
    import json
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(var, raising=False)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], cwd=repo, check=True, capture_output=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "i"], cwd=repo,
                   check=True, capture_output=True)
    wt = tmp_path / "wt" / "foo"
    subprocess.run([*git, "worktree", "add", "-q", "-b", "tp/foo", str(wt)], cwd=repo,
                   check=True, capture_output=True)
    (repo / ".three-pillars").mkdir()
    (repo / ".three-pillars" / "config.json").write_text(json.dumps({"schema_version": 1, **cfg_json}), encoding="utf-8")
    env = {"PATH": os.environ.get("PATH", ""), "CLAUDE_CONFIG_DIR": str(tmp_path / "prof")}
    if tp_local is not None:
        env["TP_LOCAL"] = tp_local
    rc = ldr.main(["foo", "--no-cheap-tier", "--dry-run"], env=env, cwd=str(repo))
    cap = capsys.readouterr()
    assert rc == 0
    return cap.out.strip().splitlines()[-1], cap.err


def test_launcher_env_on_adds_local(tmp_path, monkeypatch, capsys):
    out, err = _dry_run(tmp_path, monkeypatch, capsys, NO_KEY, "on")
    assert out.endswith("'/tp-run-full-design foo --local'; exec bash")
    assert "TP_LOCAL" not in err


def test_launcher_garbage_warns_and_adds_nothing(tmp_path, monkeypatch, capsys):
    out, err = _dry_run(tmp_path, monkeypatch, capsys, KEY_ON, "garbage")
    assert out.endswith("'/tp-run-full-design foo'; exec bash")
    assert 'warning: TP_LOCAL="garbage"' in err
