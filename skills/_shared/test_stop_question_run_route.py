"""test_stop_question_run_route.py — the Stop hook's run route names the no-card route.

design: followups-1024 2.4 (Behavior 10) — a run's Stop-hook reason names `ruling_cli.py ask`
then `ruling_cli.py wait --id`, never a card; the seat's reason still names `/tp-escalate`
and never a ruling command. Oracle: example.
test-fragility.md: the assertions go through the route the reason names, never a full sentence.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from test_stop_question_hook import DOC, RUN, SEAT, _base, _reason, _stop, _worktree  # noqa: E402


def test_a_run_reason_names_the_ruling_cli_route_without_a_card(tmp_path):
    wt = _worktree(tmp_path, _base(tmp_path))
    out, rc = _stop(wt, RUN)
    assert rc == 0
    reason = _reason(out)
    for part in (DOC, "ruling_cli.py ask", "ruling_cli.py wait --id"):
        assert part in reason


def test_the_seat_reason_still_names_tp_escalate_and_no_ruling_cli(tmp_path):
    base = _base(tmp_path)
    out, rc = _stop(base, SEAT)
    assert rc == 0
    reason = _reason(out)
    assert "/tp-escalate" in reason
    assert "ruling_cli.py" not in reason
