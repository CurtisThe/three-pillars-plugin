"""Hermetic tests for the `--direct` design-run window (design: main-thread-direct-backend 1.4, S4).

The fixture and the env-merging runner are `test_launch_design_run.py`'s, imported
unchanged — `--direct` rides the same stubbed tmux and fixture repo, and every
dry-run command is the last stdout line (what a caller takes as the command). The
role only means something to the Homelab launcher, so these put the fake launcher
of `test_launch_design_run_roles.py` first on PATH; the rig's own `claude` is plain
(launch-role-precedence 1.5: a direct run gets the `run` role, not the seat's).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_launch_design_run import _run, rig  # noqa: F401,E402
from test_launch_design_run_roles import fake_launcher  # noqa: E402

OWNED = "ANTHROPIC_BASE_URL,ANTHROPIC_DEFAULT_HAIKU_MODEL"


def _config(rig_, block):
    path = Path(rig_["repo"]) / ".three-pillars" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, **block}), encoding="utf-8")


def _last(rig_, capsys, argv, **env_over):
    """The dry-run command (last stdout line) for `argv` with env overrides."""
    assert _run(rig_, ["foo", *argv, "--dry-run"], **env_over) == 0
    return capsys.readouterr().out.strip().splitlines()[-1]


def _with_launcher(rig_, tmp_path):
    """PATH with the fake launcher (which knows the `run` role) ahead of the rig's."""
    return fake_launcher(tmp_path) + os.pathsep + rig_["env"]["PATH"]


def test_direct_puts_the_run_role_before_claude(rig, capsys, tmp_path):
    out = _last(rig, capsys, ["--direct"], CLAUDE_LAUNCHER_OWNED=OWNED,
                PATH=_with_launcher(rig, tmp_path))
    assert "CLAUDE_LAUNCHER_ROLE=run" in out and "CLAUDE_LAUNCHER_ROLE=seat" not in out
    assert out.index("CLAUDE_LAUNCHER_ROLE=run") < out.index("claude --model")


def test_direct_without_a_launcher_warns_once_and_launches_plain(rig, capsys):
    assert _run(rig, ["foo", "--direct", "--dry-run"]) == 0
    cap = capsys.readouterr()
    warns = [ln for ln in cap.err.splitlines() if ln.startswith("W:")]
    assert len(warns) == 1
    assert "CLAUDE_LAUNCHER_ROLE" not in cap.out


def test_no_flag_and_no_config_is_todays_command(rig, capsys):
    out = _last(rig, capsys, [], CLAUDE_LAUNCHER_OWNED=OWNED)
    assert "CLAUDE_LAUNCHER_ROLE" not in out


def test_config_direct_applies_without_the_flag(rig, capsys, tmp_path):
    _config(rig, {"design_run_backend": "direct"})
    out = _last(rig, capsys, [], CLAUDE_LAUNCHER_OWNED=OWNED, PATH=_with_launcher(rig, tmp_path))
    assert "CLAUDE_LAUNCHER_ROLE=run" in out
    assert out.index("CLAUDE_LAUNCHER_ROLE=run") < out.index("claude --model")


def test_config_route_is_todays_command(rig, capsys):
    _config(rig, {"design_run_backend": "route"})
    out = _last(rig, capsys, [], CLAUDE_LAUNCHER_OWNED=OWNED)
    assert "CLAUDE_LAUNCHER_ROLE" not in out


def test_a_bad_config_value_is_pruned_with_its_warning(rig, capsys):
    _config(rig, {"design_run_backend": "hybrid"})
    assert _run(rig, ["foo", "--dry-run"], CLAUDE_LAUNCHER_OWNED=OWNED) == 0
    cap = capsys.readouterr()
    assert "dropped design_run_backend" in cap.err
    assert "CLAUDE_LAUNCHER_ROLE" not in cap.out


def test_direct_keeps_local_in_the_slash_command(rig, capsys, tmp_path):
    out = _last(rig, capsys, ["--direct", "--local"], CLAUDE_LAUNCHER_OWNED=OWNED,
                PATH=_with_launcher(rig, tmp_path))
    assert out.endswith("'/tp-run-full-design foo --local'; exec bash")
    assert "CLAUDE_LAUNCHER_ROLE=run" in out


def test_the_run_role_sits_right_after_the_marker_with_no_profile_assigned(rig, capsys, tmp_path):
    out = _last(rig, capsys, ["--direct"], CLAUDE_LAUNCHER_OWNED=OWNED,
                PATH=_with_launcher(rig, tmp_path))
    assert "TP_DESIGN_RUN=1 CLAUDE_LAUNCHER_ROLE=run claude " in out
    assert "CLAUDE_CONFIG_DIR=" not in out
