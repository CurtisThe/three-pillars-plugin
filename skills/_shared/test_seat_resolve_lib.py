"""test_seat_resolve_lib.py — seat_resolve.sh helper split (design review-convergence, E2).

`seat_resolve.sh` is over its size budget; the helper functions move verbatim into
`skills/_shared/seat_resolve_lib.sh`, sourced by the script. These tests pin the seam:
the exact source line, the size bound, the helpers living in the lib (and nowhere else),
the grandfathered bash regression still passing, and the lib being git-env clean.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_SHARED_DIR = Path(__file__).resolve().parent
REPO_ROOT = _SHARED_DIR.parents[1]
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

SCRIPT = _SHARED_DIR / "seat_resolve.sh"
LIB = _SHARED_DIR / "seat_resolve_lib.sh"
SOURCE_LINE = '. "$(dirname "${BASH_SOURCE[0]}")/seat_resolve_lib.sh"'
HELPERS = ("_git", "_parse_worktrees", "_is_under_wt_dir", "_canon")


def _def_re(name: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(name)}\(\) \{{", re.M)


def test_script_sources_the_lib():
    lines = SCRIPT.read_text(encoding="utf-8").splitlines()
    assert SOURCE_LINE in lines


def test_script_is_within_size_budget():
    assert len(SCRIPT.read_text(encoding="utf-8").splitlines()) <= 440


def test_lib_defines_the_helpers_and_script_no_longer_does():
    assert LIB.is_file(), "skills/_shared/seat_resolve_lib.sh missing"
    lib_text = LIB.read_text(encoding="utf-8")
    script_text = SCRIPT.read_text(encoding="utf-8")
    for name in HELPERS:
        assert _def_re(name).search(lib_text), f"{name} not defined in the lib"
        assert not _def_re(name).search(script_text), f"{name} still defined in seat_resolve.sh"


def test_grandfathered_shell_regression_still_passes(tmp_path):
    env = dict(os.environ, TMPDIR=str(tmp_path))
    r = subprocess.run(["bash", "skills/_shared/test_seat_resolve.sh"],
                       cwd=str(REPO_ROOT), env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert re.search(r"Results: \d+ passed, 0 failed", r.stdout), r.stdout


def test_lib_is_git_env_clean():
    # git_env_check is dev-only; a shipped test reaches it through importorskip
    # (the form the inv-45 tier_guard accepts).
    git_env_check = pytest.importorskip("git_env_check")
    hits = git_env_check.scan_shell(LIB.read_text(encoding="utf-8"))
    assert hits == [], hits
