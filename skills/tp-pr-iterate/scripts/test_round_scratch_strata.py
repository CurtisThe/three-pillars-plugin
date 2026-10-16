"""round_scratch prepare --scope/--rulings under review_finder=local (local-role-routing 6.5).

The backend is made present by a fake `tp-local` executable on PATH; no router, no network.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "round_scratch.py"
PR = "https://github.com/o/r/pull/42"
LOCAL_CFG = {"role_engines": {"review_finder": "local"}}

# Run the script with `role_engine.run_local` faked: the `role_engines` fixture stands
# in for a `--local` run (the real gate reads machine-global state).
DRIVER = (
    "import runpy, sys; sys.path.insert(0, sys.argv[1]); import role_engine; "
    "role_engine.run_local = lambda cfg: bool((cfg or {}).get('role_engines')); "
    "sys.argv = sys.argv[2:]; runpy.run_path(sys.argv[0], run_name='__main__')"
)
SHARED = str(Path(__file__).resolve().parents[2] / "_shared")


def _env(tmp_path, backend):
    env = dict(os.environ)
    if backend:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        fake = bin_dir / "tp-local"
        fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake.chmod(0o755)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return env


def _prepare(tmp_path, *extra, cfg=None, backend=True):
    cfg_path = tmp_path / "cfg.json"
    if cfg is not None:
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    args = ["prepare", "--root", str(tmp_path / "scratch"), "--pr-url", PR, "--base", "b0",
            "--head", "h1", "--state", str(tmp_path / "s.json"),
            "--log", str(tmp_path / "log.md"), "--config", str(cfg_path), *extra]
    return subprocess.run([sys.executable, "-c", DRIVER, SHARED, str(SCRIPT), *args], cwd=str(tmp_path),
                          capture_output=True, text=True, timeout=60,
                          env=_env(tmp_path, backend))


def _manifest(p):
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads((Path(p.stdout.strip()) / "angles.json").read_text(encoding="utf-8"))


# The round plan appends the `security` confirmer to every round-1 manifest, so the
# manifest's last entry is the security lens and the Opus check sits beside it.
def test_local_scope_and_rulings_shape_the_manifest(tmp_path):
    m = _manifest(_prepare(tmp_path, "--scope", "edge-cases", "--rulings", "P",
                           cfg=LOCAL_CFG))
    es = m["angles"]
    assert es[-1]["name"] == "security"
    assert es[-2]["name"] == "opus-check"
    finders = es[:-2]
    assert all(e["model"] == "local" and e.get("advisory") is True for e in finders)
    assert all(e["dispatch_model"] for e in finders if not e.get("skipped"))
    assert [e.get("skipped") for e in finders] == ["out-of-scope", None, "out-of-scope"]
    assert "P" in finders[1]["prompt"]
    assert es[-2]["dispatch_model"] == "opus"
    assert not es[-2].get("advisory")
    assert es[-1]["dispatch_model"] == "opus" and not es[-1].get("advisory")


def test_unset_key_manifest_has_no_strata_fields(tmp_path):
    m = _manifest(_prepare(tmp_path, "--rulings", "R", cfg={}))
    assert [e["model"] for e in m["angles"]] == ["sonnet"] * 3 + ["opus", "opus"]
    assert all("dispatch_model" not in e or e["model"] != "local" for e in m["angles"])
    assert all("skipped" not in e for e in m["angles"])


def test_unknown_scope_is_angles_invalid(tmp_path):
    p = _prepare(tmp_path, "--scope", "no-such-angle", "--rulings", "P", cfg=LOCAL_CFG)
    assert p.returncode == 2
    assert json.loads(p.stdout)["reason"] == "angles-invalid"


def test_finder_dispatch_model_comes_from_the_config_pin(tmp_path):
    m = _manifest(_prepare(tmp_path, "--scope", "edge-cases", "--rulings", "P",
                           cfg=LOCAL_CFG))
    assert not (tmp_path / ".three-pillars" / "config.json").exists()
    finders = [e for e in m["angles"][:-2] if not e.get("skipped")]
    assert finders
    assert all(e["dispatch_model"] == "haiku" for e in finders)
