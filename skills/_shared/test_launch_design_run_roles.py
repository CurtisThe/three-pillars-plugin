"""End to end through `launch_design_run.main` with a fake launcher on PATH (launch-role-precedence 1.5).

The seat's own launcher export must never reach a design run: whatever the seat env holds, the run
gets the explicit `run` role, a command that unsets every launcher name and assigns no profile, and
the worktree's own route profile for the pretrust. The tmux stub and the fixture repo are
`test_launch_design_run.py`'s `rig`; the launcher is a fake tree whose `claude-which` answers the
route profile `aris` (and the profile of any leaked `CLAUDE_CONFIG_DIR`, so a failed scrub shows).
"""
from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import design_run_command as drc  # noqa: E402
import design_run_window_env as dwe  # noqa: E402
import launch_design_run as ldr  # noqa: E402
import launcher_export_fixture as fx  # noqa: E402
import run_scratch  # noqa: E402
from test_launch_design_run import rig  # noqa: F401,E402

REAL_PAIRS = run_scratch.env_pairs  # the rig masks the pairs; the scratch test below restores them

WHICH = """#!/bin/sh
if [ -n "$CLAUDE_CONFIG_DIR" ]; then p=$(basename "$CLAUDE_CONFIG_DIR"); else p=aris; fi
printf 'profile: %s\\nbackend: direct\\neffective: direct\\n' "$p"
"""


def fake_launcher(tmp_path, run=True):
    """A launcher tree whose `claude` is first on the returned PATH dir; `run=False` lacks `RUN`."""
    home = tmp_path / "launcher"
    (home / "bin").mkdir(parents=True)
    (home / "lib" / "launcher").mkdir(parents=True)
    for name, text in (("claude", "#!/bin/sh\nexit 0\n"), ("claude-which", WHICH)):
        (home / "bin" / name).write_text(text, encoding="utf-8")
        (home / "bin" / name).chmod(0o755)
    (home / "lib" / "launcher" / "plan.py").write_text("", encoding="utf-8")
    role = 'SEAT = "seat"\n' + ('RUN = "run"\n' if run else "")
    (home / "lib" / "launcher" / "role.py").write_text(role, encoding="utf-8")
    pdir = tmp_path / "pathdir"
    pdir.mkdir(exist_ok=True)
    (pdir / "claude").symlink_to(home / "bin" / "claude")
    return str(pdir)


def seat_envs(cfg_dir):
    """The four launching envs the design names; `cfg_dir` is the seat's profile dir."""
    seat = {**fx.DIRECT_EXPORT, "CLAUDE_CONFIG_DIR": cfg_dir}
    return {
        "seat-export": seat,
        "no-launcher-env": {},
        "only-config-dir": {"CLAUDE_CONFIG_DIR": cfg_dir},
        "leftovers": {**seat, "CLAUDE_LAUNCHER_FORCE_BACKEND": "claude",
                      "CLAUDE_LAUNCHER_ROLE": "seat"},
    }


SEATS = sorted(seat_envs("x"))


def launch_env(rig_, tmp_path, seat, path_dir=None):
    """The rig's TMUX/PATH with `path_dir` (the fake launcher) first, then the seat's export."""
    env = {k: v for k, v in rig_["env"].items() if k != "CLAUDE_CONFIG_DIR"}
    if path_dir:
        env["PATH"] = path_dir + os.pathsep + env["PATH"]
    env["HOME"] = str(tmp_path / "home")
    env.update(seat)
    return env


def launch(rig_, env, *argv, capsys=None):
    """Run `main`; with `capsys`, `(rc, last stdout line, stderr)`, else just rc."""
    rc = ldr.main(["foo", *argv], env=env, cwd=rig_["repo"], help_probe=lambda e: "")
    if capsys is None:
        return rc
    cap = capsys.readouterr()
    return rc, cap.out.strip().splitlines()[-1], cap.err


def is_unset(words, name):
    return any(a == "-u" and b == name for a, b in zip(words, words[1:]))


def assigned(words, name):
    return [w for w in words if w.startswith(name + "=")]


def write_config(rig_, block):
    path = Path(rig_["repo"]) / ".three-pillars" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, **block}), encoding="utf-8")


@pytest.mark.parametrize("case", SEATS)
def test_a_direct_dry_run_is_the_run_role_with_nothing_from_the_seat(rig, tmp_path, capsys, case):
    env = launch_env(rig, tmp_path, seat_envs("/home/curtis/.claude-profiles/personal")[case],
                     fake_launcher(tmp_path))
    rc, line, _ = launch(rig, env, "--direct", "--dry-run", capsys=capsys)
    words = shlex.split(line)
    assert rc == 0
    assert "CLAUDE_LAUNCHER_ROLE=run" in words
    assert is_unset(words, "CLAUDE_CONFIG_DIR") and is_unset(words, "CLAUDE_LAUNCHER_FORCE_PROFILE")
    assert not assigned(words, "CLAUDE_CONFIG_DIR")
    assert not assigned(words, "CLAUDE_LAUNCHER_FORCE_PROFILE")
    assert all(is_unset(words, name) for name in env.get("CLAUDE_LAUNCHER_OWNED", "").split())
    assert "personal" not in line and "settings-a3823c6b" not in line


@pytest.mark.parametrize("case", SEATS)
def test_the_mcp_read_uses_the_route_profile_not_the_seats(rig, tmp_path, capsys, monkeypatch, case):
    seen = []
    monkeypatch.setattr(ldr.drm, "read_server_defs", lambda wt, cfg: seen.append(cfg) or {})
    env = launch_env(rig, tmp_path, seat_envs(rig["cfg"])[case], fake_launcher(tmp_path))
    assert launch(rig, env, "--direct", "--dry-run") == 0
    assert [str(p) for p in seen] == [str(tmp_path / "home" / ".claude-profiles" / "aris")]


@pytest.mark.parametrize("case", SEATS)
def test_a_real_launch_pretrusts_the_route_profile_and_spares_the_seats(rig, tmp_path, case):
    seat_json = Path(rig["cfg"]) / ".claude.json"
    before = seat_json.read_bytes()
    env = launch_env(rig, tmp_path, seat_envs(rig["cfg"])[case], fake_launcher(tmp_path))
    assert launch(rig, env, "--direct", "--wait", "0") == 0
    route_json = tmp_path / "home" / ".claude-profiles" / "aris" / ".claude.json"
    trusted = json.loads(route_json.read_text(encoding="utf-8"))["projects"][rig["wt"]]
    assert trusted["hasTrustDialogAccepted"] is True
    assert seat_json.read_bytes() == before
    logged = rig["log"].read_text(encoding="utf-8").splitlines()
    assert any("CLAUDE_LAUNCHER_ROLE=run" in ln and "TP_DESIGN_RUN=1" in ln for ln in logged)


def test_a_launcher_without_the_run_role_falls_back_to_seat_with_one_line(rig, tmp_path, capsys):
    env = launch_env(rig, tmp_path, fx.DIRECT_EXPORT, fake_launcher(tmp_path, run=False))
    rc, line, err = launch(rig, env, "--direct", "--dry-run", capsys=capsys)
    words = shlex.split(line)
    assert rc == 0
    assert "CLAUDE_LAUNCHER_ROLE=seat" in words and "CLAUDE_LAUNCHER_ROLE=run" not in words
    named = [ln for ln in err.splitlines() if "falling back" in ln]
    assert len(named) == 1 and "seat" in named[0]


@pytest.mark.parametrize("block", [{"design_run_backend": "route"}, {}])
def test_route_sets_no_role_but_still_scrubs(rig, tmp_path, capsys, block):
    write_config(rig, block)
    env = launch_env(rig, tmp_path, fx.HYBRID_EXPORT, fake_launcher(tmp_path))
    rc, line, _ = launch(rig, env, "--dry-run", capsys=capsys)
    words = shlex.split(line)
    assert rc == 0 and not assigned(words, "CLAUDE_LAUNCHER_ROLE")
    for name in ("CLAUDE_CONFIG_DIR", "ANTHROPIC_BASE_URL", "CLAUDE_LAUNCHER_OWNED"):
        assert is_unset(words, name)
    assert not assigned(words, "CLAUDE_CONFIG_DIR")


def test_the_repo_config_key_gives_the_run_role_without_the_flag(rig, tmp_path, capsys):
    write_config(rig, {"design_run_backend": "direct"})
    env = launch_env(rig, tmp_path, fx.DIRECT_EXPORT, fake_launcher(tmp_path))
    rc, line, _ = launch(rig, env, "--dry-run", capsys=capsys)
    assert rc == 0 and "CLAUDE_LAUNCHER_ROLE=run" in shlex.split(line)


def test_local_mode_rides_along_with_the_run_role(rig, tmp_path, capsys):
    env = launch_env(rig, tmp_path, fx.DIRECT_EXPORT, fake_launcher(tmp_path))
    rc, line, _ = launch(rig, env, "--direct", "--local-mode", "wait", "--dry-run", capsys=capsys)
    words = shlex.split(line)
    assert rc == 0 and "TP_LOCAL_MODE=wait" in words and "CLAUDE_LAUNCHER_ROLE=run" in words
    assert line.index("CLAUDE_LAUNCHER_ROLE=run") < line.index("claude --model")


def _plain_claude_path(tmp_path):
    pdir = tmp_path / "plainpath"
    pdir.mkdir()
    (pdir / "claude").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (pdir / "claude").chmod(0o755)
    return str(pdir)


@pytest.mark.parametrize("plain", [False, True], ids=["no-claude-on-path", "claude-not-a-launcher"])
def test_without_a_launcher_the_command_is_todays(rig, tmp_path, capsys, plain):
    env = launch_env(rig, tmp_path, fx.DIRECT_EXPORT)
    env["PATH"] = _plain_claude_path(tmp_path) if plain else str(tmp_path)
    rc, line, err = launch(rig, env, "--direct", "--dry-run", capsys=capsys)
    pins, unset = dwe.plan(env, None)[0], dwe.plan(env, None)[1]
    want = drc.window_command("foo", rig["wt"], config_dir=env["CLAUDE_CONFIG_DIR"],
                              extra_env=pins, unset=unset)
    assert rc == 0 and line == want
    assert "CLAUDE_LAUNCHER_ROLE" not in line
    assert len([ln for ln in err.splitlines() if ln.startswith("W:")]) == 1


@pytest.mark.parametrize("case", SEATS)
def test_the_run_command_carries_the_scratch_pairs_and_unsets_none_of_them(
        rig, tmp_path, capsys, monkeypatch, case):  # noqa: F811
    monkeypatch.setattr(run_scratch, "env_pairs", REAL_PAIRS)
    seat = dict(seat_envs(rig["cfg"])[case])
    seat["CLAUDE_LAUNCHER_OWNED"] = seat.get("CLAUDE_LAUNCHER_OWNED", "") + " TMPDIR TMP TEMP"
    env = launch_env(rig, tmp_path, seat, fake_launcher(tmp_path))
    rc, line, _ = launch(rig, env, "--direct", "--dry-run", capsys=capsys)
    words = shlex.split(line)
    run = run_scratch.run_dir(rig["wt"])
    assert rc == 0 and assigned(words, "TMPDIR") == [f"TMPDIR={run}"]
    assert assigned(words, "XDG_CACHE_HOME") == [f"XDG_CACHE_HOME={run}/cache"]
    assert words.index(f"TMPDIR={run}") > words.index("CLAUDE_LAUNCHER_ROLE=run")
    for name in ("TMPDIR", "TMP", "TEMP", *run_scratch.CACHE_VARS):
        assert not is_unset(words, name)
