"""test_ci_gate_run_env.py — ci_gate_run strips the design-run launcher env.

design: ci-local-speed (task 1.7, B6)

`ci_gate_run.gate_env(env)` returns a copy of `env` without the launcher's
route (every name the launcher owns, every `CLAUDE_LAUNCHER_*` name, and the
run names `TP_LOCAL`, `TP_LOCAL_MODE`, `TP_DESIGN_RUN`), but keeps the worker
cap `PYTEST_XDIST_AUTO_NUM_WORKERS` and the `PATH`/`HOME`/`TMPDIR` floor even
when the launcher lists them as owned. The gate command runs with that env.

Stdlib + pytest only.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import ci_gate_run  # noqa: E402
import launcher_export_fixture as fx  # noqa: E402


@pytest.fixture(autouse=True)
def _no_git_env(monkeypatch):
    for name in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(name)


def _git(cwd: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, check=True, env=env,
    )
    return result.stdout.strip()


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "x.txt").write_text("seed\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t17@test.local")
    _git(root, "config", "user.name", "T17 Fixture")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def test_gate_env_drops_launcher_and_run_names():
    env = {
        "CLAUDE_LAUNCHER_OWNED": "ANTHROPIC_BASE_URL CLAUDE_CONFIG_DIR PYTEST_XDIST_AUTO_NUM_WORKERS",
        "ANTHROPIC_BASE_URL": "u",
        "CLAUDE_CONFIG_DIR": "c",
        "PYTEST_XDIST_AUTO_NUM_WORKERS": "4",
        "CLAUDE_LAUNCHER_ROLE": "run",
        "CLAUDE_LAUNCHER_FORCE_BACKEND": "strata",
        "CLAUDE_LAUNCHER_NEW_KEY": "x",
        "TP_LOCAL": "on",
        "TP_LOCAL_MODE": "wait",
        "TP_DESIGN_RUN": "slug",
        "PATH": "p",
        "HOME": "h",
        "CI_LOCAL_MANIFEST_DIR": "m",
    }
    assert ci_gate_run.gate_env(env) == {
        "PYTEST_XDIST_AUTO_NUM_WORKERS": "4",
        "PATH": "p",
        "HOME": "h",
        "CI_LOCAL_MANIFEST_DIR": "m",
    }, "gate_env must drop every launcher and run name and keep only the floor and the worker cap"


def test_gate_env_never_strips_the_floor():
    env = {"CLAUDE_LAUNCHER_OWNED": "PATH HOME TMPDIR",
           "PATH": "p", "HOME": "h", "TMPDIR": "t"}
    assert ci_gate_run.gate_env(env) == {"PATH": "p", "HOME": "h", "TMPDIR": "t"}


@pytest.mark.parametrize("export", [fx.DIRECT_EXPORT, fx.HYBRID_EXPORT])
def test_gate_env_on_the_real_launcher_export(export):
    out = ci_gate_run.gate_env({**export, "PATH": "p"})
    assert out["PYTEST_XDIST_AUTO_NUM_WORKERS"] == "4"
    assert out["PATH"] == "p"
    for key in out:
        assert not key.startswith("CLAUDE_LAUNCHER_")
        assert not key.startswith("TP_LOCAL")
    assert "CLAUDE_CONFIG_DIR" not in out
    assert "ANTHROPIC_BASE_URL" not in out


def test_gate_env_without_launcher_names_is_unchanged():
    env = {"PATH": "p", "TP_OTHER": "1"}
    before = dict(env)
    assert ci_gate_run.gate_env(env) == before
    assert env == before


def test_gate_command_runs_without_launcher_env(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    names = ["CLAUDE_LAUNCHER_OWNED", "ANTHROPIC_BASE_URL", "CLAUDE_LAUNCHER_ROLE",
             "TP_LOCAL", "TP_LOCAL_MODE", "TP_DESIGN_RUN"]
    for name in names:
        monkeypatch.setenv(name, "ANTHROPIC_BASE_URL" if name == "CLAUDE_LAUNCHER_OWNED" else "v")
    out = tmp_path / "env.txt"
    rc = ci_gate_run.main(["--repo", str(repo), "--command", f'env > "{out}"'])
    assert rc == 0
    keys = {line.split("=", 1)[0]
            for line in out.read_text(encoding="utf-8").splitlines() if "=" in line}
    for name in names:
        assert name not in keys
    assert "PATH" in keys
