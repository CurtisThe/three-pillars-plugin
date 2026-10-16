"""The autouse fixture in conftest.py unsets the launcher-session env for every test.

design: child-spawn-profile-inherit (known issues M63, L216)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

LEAK = {"CLAUDE_LAUNCHER_OWNED": "CLAUDE_CONFIG_DIR", "TP_LOCAL_MODE": "wait", "TP_LOCAL": "on"}
PROBE_FLAG = "HERMETIC_ENV_PROBE"


def test_probe_sees_no_launcher_env():
    """Runs inside the child pytest below; a plain run skips it."""
    if os.environ.get(PROBE_FLAG) != "1":
        pytest.skip("only meaningful inside test_launcher_env_is_unset_under_a_launcher_session")
    assert [k for k in LEAK if k in os.environ] == []


def test_launcher_env_is_unset_under_a_launcher_session():
    env = dict(os.environ, **LEAK, **{PROBE_FLAG: "1"})
    probe = Path(__file__).name + "::test_probe_sees_no_launcher_env"
    out = subprocess.run(
        [sys.executable, "-m", "pytest", probe, "-q", "-p", "no:cacheprovider"],
        cwd=str(Path(__file__).parent), env=env, capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "1 passed" in out.stdout
