"""The base-sync window carries the design-run marker and the run's scratch pairs (run-scratch-in-fence N1).

The window runs `/tp-merge-from-main` with the create fence active (`TP_DESIGN_RUN=1`),
so it must also redirect its temp files into the run dir, on the Strata branch and on
the Sonnet branch alike.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import base_sync_window as bsw  # noqa: E402
import run_scratch  # noqa: E402


def _which(found):
    return lambda name: "/usr/local/bin/" + name if found else None


def _check(cmd, worktree):
    assert "TP_DESIGN_RUN=1" in cmd
    for name, value in run_scratch.env_pairs(worktree):
        assert "%s=%s" % (name, value) in cmd, name
    # The env words come before the session command, after the pre-trust step.
    assert cmd.index("TP_DESIGN_RUN=1") < cmd.index("/tp-merge-from-main")


def test_sonnet_window_has_the_marker_and_scratch_pairs(tmp_path):
    cmd, _notes = bsw.window_command("foo", str(tmp_path), local=False, which=_which(False))
    _check(cmd, str(tmp_path))


def test_strata_window_has_the_marker_and_scratch_pairs(tmp_path):
    cmd, _notes = bsw.window_command("foo", str(tmp_path), local=True, which=_which(True))
    assert "claude-strata" in cmd
    _check(cmd, str(tmp_path))
    assert cmd.index("TP_DESIGN_RUN=1") < cmd.index("claude-strata")
