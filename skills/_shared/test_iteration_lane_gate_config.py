"""test_iteration_lane_gate_config.py — Task 2.4: gate_command reads config first.

`iteration_lane.gate_command(repo_root)` now resolves, in order (consumer-repo-parity
H1):
  1. a declared `ci.gate_command` (non-empty string) → the `ci_gate_run.py` wrapper
     lane (runs the declared command, then stamps the head) — `source="config"`,
     `writes_stamp=True`;
  2. `scripts/ci-local.sh` (dev + existing adopters) — the unchanged behaviour;
  3. the discovered test command (`writes_stamp=False`).
`null` (offered and declined) and a missing key fall through 1→2→3.

Red pins (consumer-repo-parity 2.4):
  * `ci.gate_command: "make ci"` → command ends in `ci_gate_run.py`, lane `gate`,
    `writes_stamp=True`, source `config`;
  * `null` + `scripts/ci-local.sh` → the script (unchanged behaviour);
  * missing key, no script → the discovered test command, `writes_stamp=False`;
  * self-stamping command (decisions.md retry 2): a tmp repo declaring
    `ci.gate_command: "sh scripts/ci-local.sh"` whose script stamps by itself → STILL
    the wrapper lane; running the wrapper exits 0 and `pred_ci_local_stamp` PASSes on
    that head (the wrapper's second stamp write is harmless).

Git-backed tests build a real repo in `tmp_path` and scrub inherited `GIT_*` env
(same pattern as `test_ci_gate_run.py`). Stdlib only; config fixtures are schema-valid.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Ensure _shared/ is on sys.path for bare sibling imports.
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import ci_gate_run      # noqa: E402
import ci_local_stamp   # noqa: E402
from iteration_lane import gate_command, iteration_command  # noqa: E402

# The real ci_local_stamp.py the self-stamping script invokes (an absolute path so the
# temp-repo script finds the plugin's module regardless of its own working tree).
_STAMP_SCRIPT = _SHARED_DIR / "ci_local_stamp.py"

# The exact `--fast` guard marker iteration_lane looks for in scripts/ci-local.sh.
_FAST_GUARD_MARKER = '"${1:-}" = "--fast"'

# GIT_* scrubbed so the fixture repo's own identity wins over any inherited
# GIT_DIR / GIT_CONFIG_* (same pattern as test_ci_gate_run.py / fixtures/foreign_repo.py).
_CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _write_config(root: Path, config: dict) -> None:
    """Write a schema-valid `.three-pillars/config.json` under `root`."""
    cfg_dir = root / ".three-pillars"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )


def _write_ci_local(root: Path) -> None:
    """A `scripts/ci-local.sh` carrying the `--fast` guard (fast_lane_available → True)."""
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "ci-local.sh").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [ " + _FAST_GUARD_MARKER + " ]; then\n"
        "  echo fast\n"
        "  exit 0\n"
        "fi\n"
        "echo full\n"
    )


def _write_makefile(root: Path) -> None:
    """A discoverable `test:` target (discover_test_command → `make test`)."""
    (root / "Makefile").write_text("test:\n\tpython -m pytest\n")


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, check=True, env=_CLEAN_ENV,
    )
    return result.stdout.strip()


# --- (1) declared ci.gate_command → the ci_gate_run.py wrapper lane ----------

def test_declared_command_resolves_to_wrapper_lane(tmp_path):
    _write_config(tmp_path, {"schema_version": 1, "ci": {"gate_command": "make ci"}})
    r = gate_command(tmp_path)
    assert r.command.endswith("skills/_shared/ci_gate_run.py"), (
        f"a declared ci.gate_command must resolve to the ci_gate_run.py wrapper, "
        f"got {r.command!r}"
    )
    assert r.lane == "gate"
    assert r.writes_stamp is True
    assert r.source == "config"


# --- (2) null (offered and declined) falls through to ci-local.sh ------------

def test_null_command_falls_through_to_ci_local(tmp_path):
    _write_config(tmp_path, {"schema_version": 1, "ci": {"gate_command": None}})
    _write_ci_local(tmp_path)
    r = gate_command(tmp_path)
    assert r.command.endswith("scripts/ci-local.sh"), (
        f"null ci.gate_command must fall through to ci-local.sh, got {r.command!r}"
    )
    assert r.lane == "gate"
    assert r.writes_stamp is True
    assert r.source == "ci-local"


# --- (3) missing key + no script → the discovered test command --------------

def test_missing_key_no_script_degrades_to_discovered(tmp_path):
    _write_config(tmp_path, {"schema_version": 1, "ci": {"expects_github_checks": False}})
    _write_makefile(tmp_path)  # a discoverable `test:` target, no ci-local.sh
    r = gate_command(tmp_path)
    assert r.command == "make test", (
        f"missing key with no ci-local.sh must degrade to the discovered command, "
        f"got {r.command!r}"
    )
    assert r.writes_stamp is False, "a discovered fallback is NOT the stamp source"
    assert r.source == "discovered"


# --- (4) a self-stamping declared command still goes through the wrapper -----

def test_self_stamping_command_still_wraps_and_stamps(tmp_path, monkeypatch):
    """The dev-repo case (decisions.md retry 2): the declared command is
    `sh scripts/ci-local.sh`, which stamps by itself (as the dev script does). The
    seam must STILL choose the wrapper lane (no special case for self-stamping
    commands), and running the wrapper must exit 0 with `pred_ci_local_stamp` PASSing
    on the head — the wrapper's second stamp write is harmless."""
    # The declared command does `git rev-parse HEAD` inside the wrapper's shell, which
    # inherits the ambient env — scrub any inherited GIT_* so it targets THIS repo
    # (same posture as test_ci_gate_run.py's command-that-commits case).
    for var in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(var, raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "x.txt").write_text("seed\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t24@test.local")
    _git(root, "config", "user.name", "T24 Fixture")
    _write_config(root, {"schema_version": 1, "ci": {"gate_command": "sh scripts/ci-local.sh"}})
    # Self-stamping script (mirrors the dev repo's ci-local.sh stamp step).
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "ci-local.sh").write_text(
        "#!/bin/sh\n"
        f"python3 {_STAMP_SCRIPT} --write --expect-head \"$(git rev-parse HEAD)\" "
        "--start-dirty 0\n"
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    head = _git(root, "rev-parse", "HEAD")

    # The seam STILL picks the wrapper lane (source config) — no self-stamp special case.
    r = gate_command(root)
    assert r.command.endswith("skills/_shared/ci_gate_run.py")
    assert r.lane == "gate"
    assert r.writes_stamp is True
    assert r.source == "config"

    # Running the wrapper: the declared command self-stamps, then the wrapper re-stamps
    # the SAME head (the second write is harmless). Exit 0; the stamp PASSes on the head.
    rc = ci_gate_run.main(["--repo", str(root)])
    assert rc == 0
    result = ci_local_stamp.pred_ci_local_stamp(head, repo_root=str(root))
    assert result.verdict == ci_local_stamp.GateVerdict.PASS, result.detail


# --- the iteration lane never carries the stamp, even with config declared ----

def test_iteration_lane_never_wraps_the_stamp_even_with_config(tmp_path):
    _write_config(tmp_path, {"schema_version": 1, "ci": {"gate_command": "make ci"}})
    _write_makefile(tmp_path)
    for gran in ("task", "phase"):
        r = iteration_command(tmp_path, granularity=gran)
        assert r.writes_stamp is False, (
            f"the iteration lane ({gran}) must never carry the stamp, even when a "
            f"ci.gate_command is declared"
        )
