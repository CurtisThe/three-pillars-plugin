"""Tests for design_run_command.py — shared design-run command builder + pretrust."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import design_run_command as drc  # noqa: E402


def test_marker():
    assert drc.MARKER == "TP_DESIGN_RUN"


def test_resolve_config_dir_set():
    assert drc.resolve_config_dir({"CLAUDE_CONFIG_DIR": "/p/x"}) == ("/p/x", None)


def test_resolve_config_dir_unset_warns():
    cfg, warn = drc.resolve_config_dir({})
    assert cfg is None
    assert isinstance(warn, str) and "CLAUDE_CONFIG_DIR" in warn


def test_env_prefix_quotes():
    assert drc.env_prefix("/p/my prof") == "TP_DESIGN_RUN=1 CLAUDE_CONFIG_DIR='/p/my prof' "
    assert drc.env_prefix(None) == "TP_DESIGN_RUN=1 "


def test_slash_command():
    assert drc.slash_command("foo") == "/tp-run-full-design foo"
    assert (
        drc.slash_command("foo", mode="build", skip_design=True)
        == "/tp-run-full-design foo --mode build --skip-design"
    )


@pytest.mark.parametrize("bad", ["Foo", "foo bar", "foo;rm", "", "../x"])
def test_slash_command_bad_slug(bad):
    with pytest.raises(ValueError):
        drc.slash_command(bad)


def test_window_command():
    assert drc.window_command("foo", "/w t/foo", config_dir="/p") == (
        "cd '/w t/foo' && TP_DESIGN_RUN=1 CLAUDE_CONFIG_DIR=/p "
        "claude --model opus '/tp-run-full-design foo'; exec bash"
    )


def test_slash_command_local_appends_flag():
    assert drc.slash_command("foo", local=True) == "/tp-run-full-design foo --local"
    assert drc.slash_command("foo", mode="build", skip_design=True, local=True) == (
        "/tp-run-full-design foo --mode build --skip-design --local")
    assert drc.slash_command("foo") == "/tp-run-full-design foo"


def test_window_command_forwards_local():
    cmd = drc.window_command("foo", "/w/foo", config_dir="/p", local=True)
    assert cmd.endswith("claude --model opus '/tp-run-full-design foo --local'; exec bash")
    assert "--local" not in drc.window_command("foo", "/w/foo", config_dir="/p")


@pytest.mark.parametrize("model", ["fable", "FABLE", "claude-fable-1"])
def test_window_command_rejects_fable(model):
    with pytest.raises(ValueError):
        drc.window_command("foo", "/w/foo", model=model)


def test_claude_json_path():
    assert drc.claude_json_path("/p") == os.path.join("/p", ".claude.json")
    assert drc.claude_json_path(None, home="/h") == os.path.join("/h", ".claude.json")


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_pretrust_merges(tmp_path):
    cfg = tmp_path / "p"
    cfg.mkdir()
    other = {"hasTrustDialogAccepted": True, "allowedTools": ["x"]}
    orig = {"numStartups": 7, "theme": "dark", "projects": {"/other": other}}
    _write(cfg / ".claude.json", orig)
    wt = str(tmp_path / "w" / "foo")
    out = drc.pretrust(wt, str(cfg))
    assert out == str(cfg / ".claude.json")
    data = json.loads((cfg / ".claude.json").read_text(encoding="utf-8"))
    assert data["projects"][wt]["hasTrustDialogAccepted"] is True
    assert data["numStartups"] == 7 and data["theme"] == "dark"
    assert data["projects"]["/other"] == other


def test_pretrust_preserves_existing_project_keys(tmp_path):
    cfg = tmp_path / "p"
    cfg.mkdir()
    wt = str(tmp_path / "w" / "foo")
    _write(cfg / ".claude.json", {"projects": {wt: {"history": [1, 2], "hasTrustDialogAccepted": False}}})
    drc.pretrust(wt, str(cfg))
    entry = json.loads((cfg / ".claude.json").read_text(encoding="utf-8"))["projects"][wt]
    assert entry == {"history": [1, 2], "hasTrustDialogAccepted": True}


def test_pretrust_creates_missing_file(tmp_path):
    cfg = tmp_path / "p"
    cfg.mkdir()
    wt = str(tmp_path / "w" / "foo")
    drc.pretrust(wt, str(cfg))
    data = json.loads((cfg / ".claude.json").read_text(encoding="utf-8"))
    assert data == {"projects": {wt: {"hasTrustDialogAccepted": True}}}


def test_pretrust_normalises_path(tmp_path, monkeypatch):
    cfg = tmp_path / "p"
    cfg.mkdir()
    monkeypatch.chdir(tmp_path)
    drc.pretrust("w/foo/../foo", str(cfg))
    data = json.loads((cfg / ".claude.json").read_text(encoding="utf-8"))
    assert os.path.abspath("w/foo") in data["projects"]


def test_pretrust_atomic_replace(tmp_path, monkeypatch):
    cfg = tmp_path / "p"
    cfg.mkdir()
    calls = []
    real_replace = os.replace

    def spy(src, dst):
        calls.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(drc.os, "replace", spy)
    drc.pretrust(str(tmp_path / "w"), str(cfg))
    assert len(calls) == 1
    src, dst = calls[0]
    assert os.path.dirname(src) == str(cfg)
    assert dst == str(cfg / ".claude.json")
    assert sorted(os.listdir(cfg)) == [".claude.json", ".claude.json.tp-pretrust.lock"]


def test_pretrust_default_profile_uses_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    drc.pretrust(str(tmp_path / "w"), None)
    assert (tmp_path / ".claude.json").is_file()


def test_pretrust_shell_line():
    mod = shlex.quote(os.path.abspath(drc.__file__))
    assert drc.pretrust_shell_line("/w t/foo", "/p") == (
        f"python3 {mod} pretrust '/w t/foo' --config-dir /p"
    )
    assert drc.pretrust_shell_line("/w/foo", None) == f"python3 {mod} pretrust /w/foo"


def test_cli_pretrust(tmp_path):
    wt = str(tmp_path / "w" / "foo")
    rc = drc.main(["pretrust", wt, "--config-dir", str(tmp_path)])
    assert rc == 0
    data = json.loads((tmp_path / ".claude.json").read_text(encoding="utf-8"))
    assert data["projects"][wt]["hasTrustDialogAccepted"] is True


def test_pretrust_concurrent_writers_keep_all_entries(tmp_path):
    cfg = tmp_path / "p"
    cfg.mkdir()
    mod = os.path.abspath(drc.__file__)
    wts = [str(tmp_path / "wt" / f"candidate-{i}") for i in range(12)]
    procs = [
        subprocess.Popen([sys.executable, mod, "pretrust", wt, "--config-dir", str(cfg)],
                         stdout=subprocess.DEVNULL)
        for wt in wts
    ]
    assert [p.wait() for p in procs] == [0] * len(wts)
    data = json.loads((cfg / ".claude.json").read_text(encoding="utf-8"))
    assert sorted(data["projects"]) == sorted(wts)
