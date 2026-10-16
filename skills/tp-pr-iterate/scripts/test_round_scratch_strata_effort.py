"""test_round_scratch_strata_effort.py — a `local` manifest entry spawns the Strata variant.

design: strata-effort-every-call (Task 3.1)

`angles.entry_agent(round, angle)` is the per-entry selector behind the round manifest: a
`local` angle takes the Strata variant of the round's review agent (`-deep`/xhigh on round
1, `-medium` after), every other model keeps the base agent, so the Opus check and the
security lens are unchanged. `round_scratch.prepare` writes that agent and its resolved
`agent_ref` per entry, resolving each distinct name once against the plugin root.

Oracle: example — the exact agent names and reference suffixes against the real plugin
root, where `tp-review-confirmer-medium` ships (test-fragility).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import angles  # noqa: E402
import round_scratch as rs  # noqa: E402

SCRIPT = _HERE / "round_scratch.py"
PR = "https://github.com/o/r/pull/42"
LOCAL_CFG = {"role_engines": {"review_finder": "local"}}
DEEP, BASE, MEDIUM = ("tp-review-confirmer-deep", "tp-review-confirmer",
                      "tp-review-confirmer-medium")
SHARED = str(_HERE.parents[1] / "_shared")

# The DRIVER / fake-`tp-local` fixture pattern of test_round_scratch_strata.py: a
# `role_engines` config stands in for a `--local` run and the fake executable for its
# backend. No router, no network.
DRIVER = (
    "import runpy, sys; sys.path.insert(0, sys.argv[1]); import role_engine; "
    "role_engine.run_local = lambda cfg: bool((cfg or {}).get('role_engines')); "
    "sys.argv = sys.argv[2:]; runpy.run_path(sys.argv[0], run_name='__main__')"
)


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


def _cli_prepare(tmp_path, *extra, cfg=None, backend=True):
    cfg_path = tmp_path / "cfg.json"
    if cfg is not None:
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    args = ["prepare", "--root", str(tmp_path / "scratch"), "--pr-url", PR, "--base", "b0",
            "--head", "h1", "--state", str(tmp_path / "s.json"),
            "--log", str(tmp_path / "log.md"), "--config", str(cfg_path), *extra]
    return subprocess.run([sys.executable, "-c", DRIVER, SHARED, str(SCRIPT), *args],
                          cwd=str(tmp_path), capture_output=True, text=True, timeout=60,
                          env=_env(tmp_path, backend))


def _manifest(p):
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads((Path(p.stdout.strip()) / "angles.json").read_text(encoding="utf-8"))


# The angle set a local round runs (the shape `finder_round.round_angles` returns): local
# advisory finders — one out of scope — plus the Opus check.
LOCAL_ANGLES = [
    {"name": "correctness-leak", "role": "finder", "model": "local", "advisory": True,
     "prompt": "p1"},
    {"name": "test-quality", "role": "finder", "model": "local", "advisory": True,
     "prompt": "p2", "skipped": "out-of-scope"},
    {"name": "edge-cases", "role": "finder", "model": "local", "advisory": True,
     "prompt": "p3"},
    {"name": "opus-check", "role": "confirmer", "model": "opus", "prompt": "p4"},
]


def _prep(root, angle_list, config):
    return rs.prepare(root, PR, angle_list, base="b0", head="h1", effort="high",
                      state_path=str(root / "s.json"), log_path=str(root / "l.md"),
                      config=config)


def _entries(round_dir):
    return json.loads((round_dir / "angles.json").read_text(encoding="utf-8"))["angles"]


def _close(round_dir):
    """The tail envelope `prepare` reads to name the next round."""
    (round_dir / "tail").mkdir(exist_ok=True)
    (round_dir / "tail" / "envelope.json").write_text(json.dumps({"action": "fix"}),
                                                      encoding="utf-8")


# --- the selector ---------------------------------------------------------------------

def test_local_later_round_is_the_medium_variant():
    assert angles.entry_agent(2, {"model": "local"}) == MEDIUM


def test_local_round_one_stays_deep():
    assert angles.entry_agent(1, {"model": "local"}) == DEEP


def test_sonnet_angle_keeps_the_base_agent():
    assert angles.entry_agent(2, {"model": "sonnet"}) == BASE


def test_opus_angle_keeps_the_base_agent():
    assert angles.entry_agent(2, {"model": "opus"}) == BASE


# --- the manifest, round 1, through the CLI -------------------------------------------

def test_cli_round_one_local_entries_are_deep(tmp_path):
    m = _manifest(_cli_prepare(tmp_path, "--scope", "edge-cases", "--rulings", "P",
                               cfg=LOCAL_CFG))
    es = m["angles"]
    finders = [e for e in es if e["model"] == "local"]
    assert finders
    assert all(e["agent"] == DEEP and e["agent_ref"].endswith(f":{DEEP}") for e in finders)
    for name in ("opus-check", "security"):
        assert next(e for e in es if e["name"] == name)["agent"] == DEEP


# --- the manifest, later rounds -------------------------------------------------------

def test_round_two_local_entries_are_medium_and_the_check_stays_base(tmp_path):
    root = tmp_path / "proof"
    r1 = _prep(root, LOCAL_ANGLES, LOCAL_CFG)
    got1 = _entries(r1)
    assert [e["name"] for e in got1] == [a["name"] for a in LOCAL_ANGLES]
    assert all(e["agent"] == DEEP and e["agent_ref"].endswith(f":{DEEP}")
               for e in got1 if e["model"] == "local")
    _close(r1)
    r2 = _prep(root, LOCAL_ANGLES, LOCAL_CFG)
    assert r2 == root / "rounds" / "42" / "r2"
    got2 = _entries(r2)
    live = [e for e in got2 if e["model"] == "local" and not e.get("skipped")]
    assert live
    assert all(e["agent"] == MEDIUM and e["agent_ref"].endswith(f":{MEDIUM}") for e in live)
    check = next(e for e in got2 if e["name"] == "opus-check")
    assert check["agent"] == BASE and check["agent_ref"].endswith(f":{BASE}")


def test_round_two_sonnet_run_is_unchanged(tmp_path):
    angles_list = [{**a, "model": "sonnet"} if a["model"] == "local" else a
                   for a in LOCAL_ANGLES]
    root = tmp_path / "proof"
    _close(_prep(root, angles_list, {}))
    got = _entries(_prep(root, angles_list, {}))
    assert got
    assert all(e["agent"] == BASE and e["agent_ref"].endswith(f":{BASE}") for e in got)
