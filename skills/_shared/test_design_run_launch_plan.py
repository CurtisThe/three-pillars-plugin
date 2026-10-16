"""Tests for design_run_launch_plan.build: one pure plan for role, scrub and profile."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import design_run_launch_plan as lp  # noqa: E402
import design_run_window_env as dwe  # noqa: E402
import launcher_export_fixture as fx  # noqa: E402
from test_launcher_which import _path_env, _tree  # noqa: E402

SEATS = {"direct": fx.DIRECT_EXPORT, "hybrid": fx.HYBRID_EXPORT}


def _which(profile="aris"):
    return lambda cwd, env: {"profile": profile, "backend": "direct", "effective": "x"}


def _env(tmp_path, seat, run=True):
    home = _tree(tmp_path, run=run)
    return {**seat, **_path_env(tmp_path, home)}


def _build(env, tmp_path, cfg=None, direct=False, which=None, mode=None):
    return lp.build(env, cfg or {}, direct, mode, tmp_path / "wt",
                    home=tmp_path / "home", which=which or _which())


@pytest.mark.parametrize("seat", sorted(SEATS))
def test_launcher_uses_the_route_profile_never_the_seats(tmp_path, seat):
    env = _env(tmp_path, SEATS[seat])
    p = _build(env, tmp_path, direct=True)
    assert str(p.profile_dir).endswith(".claude-profiles/aris")
    assert "personal" not in str(p.profile_dir)
    assert p.command_config_dir is None
    assert p.backend_env == "CLAUDE_LAUNCHER_ROLE=run"
    assert "CLAUDE_CONFIG_DIR" in p.unset and "CLAUDE_LAUNCHER_OWNED" in p.unset
    assert p.extra_env == []


def test_config_key_direct_gives_run_role(tmp_path):
    p = _build(_env(tmp_path, fx.DIRECT_EXPORT), tmp_path, cfg={"design_run_backend": "direct"})
    assert p.backend_env == "CLAUDE_LAUNCHER_ROLE=run"


def test_route_has_no_role_but_keeps_the_scrub(tmp_path):
    p = _build(_env(tmp_path, fx.HYBRID_EXPORT), tmp_path)
    assert p.backend_env == "" and p.command_config_dir is None
    assert "ANTHROPIC_BASE_URL" in p.unset


def test_local_mode_is_exported(tmp_path):
    p = _build(_env(tmp_path, fx.DIRECT_EXPORT), tmp_path, mode="wait")
    assert p.extra_env == [("TP_LOCAL_MODE", "wait")]


def test_launcher_without_run_falls_back_to_seat_with_one_note(tmp_path):
    p = _build(_env(tmp_path, fx.DIRECT_EXPORT, run=False), tmp_path, direct=True)
    assert p.backend_env == "CLAUDE_LAUNCHER_ROLE=seat"
    assert len([n for n in p.notes if "run" in n and "seat" in n]) == 1


def test_failing_which_skips_pretrust_with_one_note(tmp_path):
    p = _build(_env(tmp_path, fx.DIRECT_EXPORT), tmp_path, which=lambda cwd, env: None)
    assert p.profile_dir is None
    assert len([n for n in p.notes if "pretrust" in n]) == 1


def test_no_launcher_on_path_is_todays_behaviour(tmp_path):
    env = {**fx.DIRECT_EXPORT, "PATH": str(tmp_path)}
    p = _build(env, tmp_path, direct=True, mode="fallback")
    assert p.command_config_dir == env["CLAUDE_CONFIG_DIR"]
    assert p.profile_dir == env["CLAUDE_CONFIG_DIR"]
    assert p.unset == dwe.plan(env, "fallback")[1]
    assert p.extra_env == dwe.plan(env, "fallback")[0]
    assert p.backend_env == ""
    assert any(n.startswith("W: no claude-launcher") for n in p.notes)


def test_plain_claude_script_is_not_a_launcher(tmp_path):
    home = _tree(tmp_path, plan=False)
    env = {**fx.DIRECT_EXPORT, **_path_env(tmp_path, home)}
    p = _build(env, tmp_path, direct=True)
    assert p.command_config_dir == env["CLAUDE_CONFIG_DIR"]
    assert p.unset == dwe.plan(env, None)[1]
    assert p.backend_env == ""
    assert sum(n.startswith("W: no claude-launcher") for n in p.notes) == 1
