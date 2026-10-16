"""A local finder round without rulings fails fast (one-cheap-engine 1.5, #243)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import finder_round  # noqa: E402
import role_engine  # noqa: E402

LOCAL = {"role_engines": {"review_finder": "local"}}
ANGLES = [{"name": n, "role": "confirmer", "model": "opus", "prompt": f"look at {n}"}
          for n in ("correctness", "security", "perf")]
SCRIPT = _HERE / "round_scratch.py"
PR = "https://github.com/o/r/pull/42"


@pytest.fixture(autouse=True)
def _run_follows_fixture(monkeypatch):
    """The retired `role_engines` fixtures stand in for a `--local` run."""
    monkeypatch.setattr(role_engine, "run_local", lambda cfg: bool((cfg or {}).get("role_engines")))

# Run the script with `role_engine.run_local` faked: the `role_engines` fixture stands
# in for a `--local` run (the real gate reads machine-global state).
DRIVER = (
    "import runpy, sys; sys.path.insert(0, sys.argv[1]); import role_engine; "
    "role_engine.run_local = lambda cfg: bool((cfg or {}).get('role_engines')); "
    "sys.argv = sys.argv[2:]; runpy.run_path(sys.argv[0], run_name='__main__')"
)
SHARED = str(Path(__file__).resolve().parents[2] / "_shared")


def _yes():
    return True


def _round(rulings):
    cfg = {**LOCAL, "review": {"angles": ANGLES}}
    return finder_round.round_angles(cfg, root=".", available=_yes, rulings_path=rulings)


def test_local_round_without_rulings_raises():
    with pytest.raises(ValueError, match="--rulings"):
        _round(None)


def test_prompt_never_says_rulings_at_none():
    for a in _round("/x/rulings.md"):
        assert "rulings at None" not in a["prompt"]
    with pytest.raises(ValueError):
        _round(None)


def test_prepare_refuses_without_rulings(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "tp-local"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps(LOCAL), encoding="utf-8")
    p = subprocess.run(
        [sys.executable, "-c", DRIVER, SHARED, str(SCRIPT), "prepare", "--root", str(tmp_path / "scratch"),
         "--pr-url", PR, "--base", "b0", "--head", "h1", "--state", str(tmp_path / "s.json"),
         "--log", str(tmp_path / "log.md"), "--config", str(cfg)],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60, env=env)
    assert p.returncode == 2, p.stdout + p.stderr
    out = json.loads(p.stdout.strip().splitlines()[-1])
    assert out["reason"] == "angles-invalid"
    assert "--rulings" in out["detail"]
