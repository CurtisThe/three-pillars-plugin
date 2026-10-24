"""inner_pytest.py — run a child pytest isolated from the calling pytest.

design: local-sized-tasks

Use this in a test that runs pytest inside pytest. The child ignores the
caller's ini, addopts, xdist workers and basetemp, so it is deterministic under
`-n 4` and under a PYTEST_ADDOPTS in the environment.

Sibling helpers: `clean_git_env` (`git_env.py`, dev-only) scrubs git env for
child git calls; `attempt_fixture.commit_pair` builds a red/green commit pair.
Stdlib only.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _clean_env(env):
    out = {
        k: v for k, v in os.environ.items()
        if k not in ("PYTEST_ADDOPTS", "PYTEST_CURRENT_TEST")
        and not k.startswith("PYTEST_XDIST_")
    }
    out.update(env or {})
    return out


def inner_pytest(tmp, args=(), *, env=None, timeout=300) -> subprocess.CompletedProcess:
    tmp = Path(tmp)
    ini = tmp / "pytest.ini"
    if not ini.exists():
        ini.write_text("[pytest]\n")
    basetemp = tmp.parent / (tmp.name + "-basetemp")
    cmd = [
        sys.executable, "-m", "pytest", "-c", str(ini), "--rootdir", str(tmp),
        "-p", "no:xdist", "-p", "no:cacheprovider",
        "--basetemp", str(basetemp), "-q", *args,
    ]
    return subprocess.run(
        cmd, cwd=tmp, capture_output=True, text=True,
        env=_clean_env(env), timeout=timeout,
    )
