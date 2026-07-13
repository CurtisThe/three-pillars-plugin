"""Tests for sweep_orphan_branches.py — Option B post-run sweeper CLI.

Covers:
  (a) main() prints the deleted list as JSON and always exits 0.
  (b) a raising sweep_orphan_agent_branches is swallowed — the CLI still
      prints an empty deleted list and exits 0 (backstop contract).
  (c) --decisions-log is forwarded through to the helper unchanged.
  (d) an argparse usage error (unknown flag) degrades to exit 0 — the
      fail-open backstop must never make the orchestrator's exit non-zero.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from sweep_orphan_branches import main


def test_cli_prints_deleted_and_exits_zero(capsys):
    with patch(
        "sweep_orphan_branches.sweep_orphan_agent_branches",
        return_value=["worktree-agent-X"],
    ):
        rc = main([])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"deleted": ["worktree-agent-X"]}


def test_cli_fail_open_on_helper_error(capsys):
    with patch(
        "sweep_orphan_branches.sweep_orphan_agent_branches",
        side_effect=RuntimeError("boom"),
    ):
        rc = main([])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"deleted": []}


def test_cli_forwards_decisions_log_flag(tmp_path, capsys):
    log = tmp_path / "decisions.md"
    with patch(
        "sweep_orphan_branches.sweep_orphan_agent_branches", return_value=[]
    ) as sweep_mock:
        rc = main(["--decisions-log", str(log)])

    assert rc == 0
    sweep_mock.assert_called_once_with(decisions_log=log)


def test_cli_argparse_error_degrades_to_zero(capsys):
    # A usage error (unknown flag) must not make the orchestrator's exit
    # non-zero — the fail-open backstop degrades it to exit 0 with an empty
    # deleted list.
    rc = main(["--bogus-flag"])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"deleted": []}
