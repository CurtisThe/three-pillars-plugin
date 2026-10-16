"""Resolved PR-loop stop continues: `limits(config, state)` overlays the recorded extension.

design: fable-first-stops (Task 2.4). Terminal states come from `round_budget.tick`, the
grant from `budget_extension.grant` (what `finalizer_cli apply` writes), then tick again.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "_shared"))
import budget_extension as be  # noqa: E402
import finalizer_ruling as fr  # noqa: E402
import round_budget as rb  # noqa: E402

SCHEMA = json.loads((HERE.parent / "schemas" / "iterate-state.v1.json").read_text(encoding="utf-8"))
URL = "https://github.com/acme/widgets/pull/42"
NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
BLOCK = {"blocking": 1, "reproduced": 1}
# keep-the-pin: the asserted 6→8 extension numbers predate the review-weight cap of 3.
# keep-the-pin: the growth-lines terminal below diffs 200 lines, under the 300 floor.
CAP6 = {"pdw": {"guards": {"round_cap": 6, "growth_floor_lines": 0}}}


def base(**extra):
    return {"phase": "awaiting-review", "iteration": 0, "max_iterations": 6,
            "max_wall_clock_sec": 14400, "started_at": NOW.isoformat(), "transitions": [],
            **extra}


def tick(state, head="h1", tally=BLOCK, cfg=CAP6, numstat=None, pr=URL, ordinal=None):
    return rb.tick(state, head_sha=head, pr_url=pr, tally=tally, review_base="main",
                   config=cfg, now=NOW, ordinal=ordinal, numstat_fn=numstat)


def valid(state):
    Draft202012Validator(SCHEMA).validate(state)


def big(n):
    return lambda a, b: [("src/x.py", n, 0)]


def terminal(signal):
    """A terminal state for `signal`, built by `tick`."""
    if signal == "round-cap":
        st, phase, _ = tick(base(iteration=5, budget_pr_url=URL))
    elif signal == "wall-clock":
        st, phase, _ = tick(base(budget_pr_url=URL, budget_active_elapsed_sec=15000))
    else:
        seed = base(budget_pr_url=URL, budget_baseline_head="h0", original_diff_lines=100,
                    budget_baseline_split={"test_added": 0, "code_added": 100})
        st, phase, _ = tick(seed, numstat=big(200), tally={})
    assert st["termination_reason"] == signal and phase == rb.TERMINAL_PHASE[signal]
    return st


def grant(state):
    out, res = be.grant(state, state["termination_reason"], rb.limits(CAP6), "k1", "T0")
    assert res is not None
    return out


@pytest.mark.parametrize("signal", ["round-cap", "wall-clock", "growth-lines"])
def test_recorded_grant_lifts_on_next_tick(signal):
    granted = grant(terminal(signal))
    valid(granted)
    growth = signal == "growth-lines"
    st, phase, _ = tick(granted, numstat=big(200) if growth else None,
                        tally={} if growth else BLOCK)
    assert phase is None and st["phase"] == "awaiting-review"
    assert st["transitions"][-1]["note"] == f"[budget-lifted] {signal}"
    valid(st)


def test_without_grant_the_terminal_holds():
    _, phase, detail = tick(terminal("round-cap"))
    assert phase == "budget-exhausted" and detail["signal"] == "round-cap"


def test_same_signal_past_the_extension_is_a_fresh_terminal():
    st, phase, _ = tick(grant(terminal("round-cap")))
    assert phase is None and st["iteration"] == 7
    st2, phase2, detail = tick(st, head="h2")
    assert (phase2, detail["signal"], detail["limit"]) == ("budget-exhausted", "round-cap", 8)
    assert st2["termination_reason"] == "round-cap"


def test_pr_key_reset_clears_the_extension():
    granted = grant(terminal("round-cap"))
    other = "https://github.com/acme/widgets/pull/43"
    st, phase, detail = tick(granted, pr=other)
    assert st["budget_extensions"] is None and st["phase"] == "awaiting-review"
    assert detail["round_cap"] == 6 and phase is None
    valid(st)


def test_limits_without_state_is_unchanged():
    assert rb.limits(None) == rb.DEFAULTS
    assert rb.limits({"pdw": {"guards": {"round_cap": 9}}})["round_cap"] == 9
    granted = grant(terminal("round-cap"))
    assert rb.limits(CAP6, granted)["round_cap"] == 8
    assert rb.limits({"pdw": {"guards": {"round_cap": 20}}}, granted)["round_cap"] == 20


def test_finalizer_apply_then_tick_lifts(tmp_path, capsys, monkeypatch):
    import finalizer_cli as cli
    monkeypatch.chdir(tmp_path)
    cap6 = tmp_path / "cap6.json"
    cap6.write_text(json.dumps(CAP6), encoding="utf-8")
    path = tmp_path / "iterate-state.json"
    path.write_text(json.dumps(terminal("round-cap")), encoding="utf-8")
    detail = {"iteration": 6, "round_cap": 6, "signal": "round-cap", "measured": 6, "limit": 6,
              "holding": ["round-cap"]}
    stop = json.dumps({"source": "pr-iterate", "signal": "round-cap", "target": URL,
                       "head": "a1" * 20, "detail": detail})
    reply = tmp_path / "reply.txt"
    reply.write_text("```json\n" + json.dumps({
        "outcome": "resolved", "actions": ["fix"], "diagnosis": "d", "reasoning": "r (vision.md)",
        "demoted": [], "blocked": [], **fr.EMPTY_RULING}) + "\n```\n", encoding="utf-8")
    seams = {"comment_fn": lambda u, b: True, "label_fn": lambda u, lb: True,
             "resolve_fn": lambda a: f"three-pillars:{a}",
             "pr_state_fn": lambda u: {"state": "OPEN", "headRefOid": "b2" * 20},
             "is_ancestor_fn": lambda a, b: True, "now": 1_800_000_000.0}
    common = ["--stop", stop, "--ledger", str(tmp_path / "l.json")]
    assert cli.main(["prepare", *common], **seams) == 0
    rc = cli.main(["apply", *common, "--reply", str(reply), "--decisions",
                   str(tmp_path / "d.md"), "--state", str(path), "--config", str(cap6)], **seams)
    capsys.readouterr()
    assert rc == 0
    written = json.loads(path.read_text(encoding="utf-8"))
    valid(written)
    out, phase, _ = tick(written)
    assert phase is None and out["transitions"][-1]["note"] == "[budget-lifted] round-cap"
