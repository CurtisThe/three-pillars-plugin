"""Tests for launcher_which: find the Homelab launcher and ask it for a folder's plan."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import launcher_export_fixture as fx  # noqa: E402
import launcher_which as lw  # noqa: E402

SCRUBBED = ("CLAUDE_CONFIG_DIR", "CLAUDE_LAUNCHER_ROLE", "CLAUDE_LAUNCHER_FORCE_BACKEND",
            "CLAUDE_LAUNCHER_FORCE_PROFILE", "CLAUDE_LAUNCHER_OWNED", "ANTHROPIC_BASE_URL",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL")


def _tree(tmp_path, run=True, plan=True):
    home = tmp_path / "launcher"
    (home / "bin").mkdir(parents=True)
    (home / "bin" / "claude").write_text("#!/bin/sh\n")
    (home / "bin" / "claude-which").write_text("#!/bin/sh\n")
    (home / "lib" / "launcher").mkdir(parents=True)
    if plan:
        (home / "lib" / "launcher" / "plan.py").write_text("")
    role = 'SEAT = "seat"\n' + ('RUN = "run"\n' if run else "")
    (home / "lib" / "launcher" / "role.py").write_text(role)
    return home


def _path_env(tmp_path, home):
    pdir = tmp_path / "pathdir"
    pdir.mkdir()
    (pdir / "claude").symlink_to(home / "bin" / "claude")
    return {"PATH": str(pdir)}


def test_launcher_home_found_via_symlink(tmp_path):
    home = _tree(tmp_path)
    assert lw.launcher_home(_path_env(tmp_path, home)) == home.resolve()


def test_launcher_home_plain_claude_is_none(tmp_path):
    home = _tree(tmp_path, plan=False)
    assert lw.launcher_home(_path_env(tmp_path, home)) is None


def test_launcher_home_absent_is_none(tmp_path):
    assert lw.launcher_home({"PATH": str(tmp_path)}) is None


def test_supports_run(tmp_path):
    assert lw.supports_run(_tree(tmp_path / "a", run=True)) is True
    assert lw.supports_run(_tree(tmp_path / "b", run=False)) is False


class _Done:
    def __init__(self, rc=0, out=""):
        self.returncode = rc
        self.stdout = out


def _runner(calls, result):
    def run(cmd, **kw):
        calls.append((cmd, kw))
        if isinstance(result, Exception):
            raise result
        return result
    return run


OUT = "profile: aris\nbackend: hybrid\neffective: hybrid\nnoise line\n"


def test_which_parses_and_scrubs(tmp_path):
    home = _tree(tmp_path)
    calls = []
    env = dict(fx.HYBRID_EXPORT, PATH="/usr/bin", CLAUDE_LAUNCHER_ROLE="run",
               CLAUDE_LAUNCHER_FORCE_BACKEND="strata", CLAUDE_LAUNCHER_FORCE_PROFILE="x",
               ANTHROPIC_AUTH_TOKEN="t")
    got = lw.which(tmp_path, env, runner=_runner(calls, _Done(0, OUT)), home=home)
    assert got == {"profile": "aris", "backend": "hybrid", "effective": "hybrid"}
    cmd, kw = calls[0]
    assert str(home / "bin" / "claude-which") in [str(c) for c in cmd]
    assert str(kw["cwd"]) == str(tmp_path)
    passed = kw["env"]
    for name in SCRUBBED + tuple(fx.HYBRID_EXPORT["CLAUDE_LAUNCHER_OWNED"].split()):
        assert name not in passed
    assert "ANTHROPIC_AUTH_TOKEN" not in passed
    assert passed["PATH"] == "/usr/bin"


@pytest.mark.parametrize("result", [
    _Done(1, OUT), OSError("boom"), subprocess.TimeoutExpired("x", 1)])
def test_which_failures_are_none(tmp_path, result):
    home = _tree(tmp_path)
    assert lw.which(tmp_path, {}, runner=_runner([], result), home=home) is None


def test_which_without_launcher_is_none(tmp_path):
    assert lw.which(tmp_path, {"PATH": str(tmp_path)}, runner=_runner([], _Done(0, OUT))) is None


def test_scrub_names_exported():
    assert "ANTHROPIC_AUTH_TOKEN" in lw.SCRUB_NAMES
    assert "ANTHROPIC_DEFAULT_OPUS_MODEL" in lw.SCRUB_NAMES
    assert "ANTHROPIC_DEFAULT_SONNET_MODEL" in lw.SCRUB_NAMES


def test_fixture_sanity():
    assert fx.DIRECT_EXPORT["CLAUDE_LAUNCHER_BACKEND"] == "direct"
    assert "ANTHROPIC_BASE_URL" in fx.HYBRID_EXPORT
    assert fx.HYBRID_EXPORT["CLAUDE_LAUNCHER_BACKEND"] == "hybrid"
    for exp in (fx.DIRECT_EXPORT, fx.HYBRID_EXPORT):
        assert "CLAUDE_LAUNCHER_ROLE" not in exp
        assert "CLAUDE_LAUNCHER_FORCE_BACKEND" not in exp
        owned = set(exp["CLAUDE_LAUNCHER_OWNED"].split())
        for k in exp:
            if k.startswith("CLAUDE_LAUNCHER_"):
                assert k in owned
