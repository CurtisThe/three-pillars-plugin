"""Tests for posthoc_rows tier reasons: unavailable causes and FAIL runaway classes.

design: cheap-tier-local-routing 7.1 (detailed-design-posthoc.md, posthoc_rows; plan Task 7.1).
`tier_reasons` reads the `**Verdicts**` lines of a decisions.md `### [tier]` blocks; a row takes
its cause by ordinal (the n-th row of its task, rung and outcome in file order, tagged by
`load`), and a FAIL is paired to its verdict by the `gen-stats local_requests=A/B` flag of its
dispatch line first. Discovery, merge, time and measure are in test_posthoc_rows.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FIX = HERE / "fixtures" / "posthoc"
DECISIONS = FIX / "repo" / "three-pillars-docs" / "tp-designs" / "fixture-design" / "decisions.md"
pytestmark = pytest.mark.skipif(not DECISIONS.is_file(), reason="no posthoc fixture in this tree")

import posthoc_rows  # noqa: E402

LM = "local-medium"


def _fixture_text() -> str:
    return DECISIONS.read_text(encoding="utf-8")


def _fixture_rows() -> dict:
    rows = posthoc_rows.load(FIX / "repo", roots=[FIX / "repo"], env={"XDG_STATE_HOME": str(FIX)})
    return {r.get("attempt_key"): r for r in rows}


def _block(task, verdicts, dispatch=()) -> str:
    head = f"### [tier] {task} — done\n**Tier path**: {LM}\n**Verdicts**: {verdicts}\n**Red-at-base**: n/a\n"
    return head + "".join(f"{line}\n" for line in dispatch)


def _fail_row(ordinal=1, served=None, task="3.1", rung=LM) -> dict:
    row = {"task_id": task, "rung": rung, "outcome": "FAIL", "ordinal": ordinal}
    if served:
        row["served"] = {"local_requests": served[0], "turns": served[1]}
    return row


def _dispatch(task, outcome, stats=None, stuck=None, rung=LM) -> list[str]:
    lines = [f"[dispatch] task {task} → tp-task-worker-{rung} (haiku, medium, routed/ok) — retry: {outcome}"]
    if stuck:
        lines.append(f"stuck: {stuck}")
    lines.append(f"flag: gen-stats local_requests={stats[0]}/{stats[1]} n_gen_max=1 n_gen_p50=1 at_cap=0"
                 if stats else "flag: gen-stats unavailable")
    return lines


def test_tier_reasons_over_the_fixture_blocks_names_both_unavailable_causes():
    assert posthoc_rows.tier_reasons(_fixture_text()) == {
        ("1.4", LM, 1): "orphan-holds-gpu",
        ("1.4", LM, 2): "local-busy",
        ("2.1", "local-xhigh", 1): "orphan-holds-gpu",
    }


def test_the_nth_unavailable_row_takes_the_nth_verdict_of_its_task_and_rung():
    reasons = posthoc_rows.tier_reasons(_fixture_text())
    rows = _fixture_rows()
    got = {k: posthoc_rows.unavailable_reason(rows[k], reasons)
           for k in ("ea772ea51f8c0e7e", "712d4a2af6c5a337", "c2fd0b125d673f4f")}
    assert got == {"ea772ea51f8c0e7e": "orphan-holds-gpu", "712d4a2af6c5a337": "local-busy",
                   "c2fd0b125d673f4f": "orphan-holds-gpu"}
    assert [rows[k]["ordinal"] for k in ("ea772ea51f8c0e7e", "712d4a2af6c5a337", "c2fd0b125d673f4f")] == [1, 2, 1]


def test_a_row_with_its_own_fallback_keeps_it_and_an_unmatched_row_is_unrecorded():
    reasons = {("1.4", LM, 1): "orphan-holds-gpu"}
    base = {"task_id": "1.4", "rung": LM, "outcome": "unavailable", "ordinal": 1}
    assert posthoc_rows.unavailable_reason(base, reasons) == "orphan-holds-gpu"
    assert posthoc_rows.unavailable_reason(dict(base, fallback="local-busy-measure"), reasons) == "local-busy-measure"
    assert posthoc_rows.unavailable_reason(dict(base, fallback=None), reasons) == "orphan-holds-gpu"
    assert posthoc_rows.unavailable_reason(dict(base, ordinal=2), reasons) == "unrecorded"
    assert posthoc_rows.unavailable_reason(dict(base, task_id="9.9"), reasons) == "unrecorded"
    assert posthoc_rows.unavailable_reason(base, {}) == "unrecorded"


def test_ordinals_continue_across_blocks_and_an_unavailable_without_a_reason_is_skipped():
    text = (_block("2.1", f"{LM} unavailable (local-busy); {LM} unavailable; {LM} PASS")
            + "\n" + _block("2.1", f"{LM} unavailable (orphan-holds-gpu)")
            + "\n" + _block("2.2", f"sonnet-xhigh unavailable (refuse)"))
    assert posthoc_rows.tier_reasons(text) == {
        ("2.1", LM, 1): "local-busy", ("2.1", LM, 3): "orphan-holds-gpu", ("2.2", "sonnet-xhigh", 1): "refuse"}


def test_a_fail_reason_with_nested_parentheses_and_semicolons_does_not_split_the_verdicts():
    verdicts = (f"{LM} FAIL (post-pass: a; b (c) d; local-medium is slow); "
                f"{LM} unavailable (local-busy); sonnet-medium PASS-WITH-NOTES (kept)")
    text = _block("4.1", verdicts)
    assert posthoc_rows.tier_reasons(text) == {("4.1", LM, 1): "local-busy"}


@pytest.mark.parametrize("cause, expected", [
    ("runaway: generation client-reset mid-response", "reset"),
    ("runaway: generation client-reset idle", "reset"),
    ("runaway: generation stop_reason=max_tokens", "generation"),
    ("runaway: wall-clock 1203s >= 1200s", "wall-clock"),
    ("runaway: wall-clock 1213s ≥ 1200s", "wall-clock"),
    ("runaway: something new", "runaway-other"),
    ("runaway: generation of another sort", "runaway-other"),
    ("post-pass: _diff_hunks raises on a hunk-less diff block", "fail"),
    ("the test still failed", "fail"),
])
def test_fail_reason_classes(cause, expected):
    text = _block("3.1", f"{LM} FAIL ({cause})")
    assert posthoc_rows.fail_reason(_fail_row(), text) == expected


def test_a_fail_with_no_verdict_to_read_is_plain_fail():
    text = _block("3.1", f"{LM} FAIL (runaway: wall-clock 1203s >= 1200s)")
    assert posthoc_rows.fail_reason(_fail_row(task="7.7"), text) == "fail"
    assert posthoc_rows.fail_reason(_fail_row(rung="sonnet-medium"), text) == "fail"
    assert posthoc_rows.fail_reason(_fail_row(), "") == "fail"
    assert posthoc_rows.fail_reason(_fail_row(), _block("3.1", f"{LM} FAIL")) == "fail"


def test_the_fixture_fail_rows_are_paired_by_their_gen_stats_not_by_position():
    """Review-prep's second FAIL attempt is not in the excerpt, so row 7 is the 2nd FAIL row but the 3rd verdict."""
    rows, text = _fixture_rows(), _fixture_text()
    assert rows["4d1bcfefbc362a03"]["ordinal"] == 1 and rows["1d644010b9d47cf0"]["ordinal"] == 2
    assert posthoc_rows.fail_reason(rows["4d1bcfefbc362a03"], text) == "fail"
    assert posthoc_rows.fail_reason(rows["1d644010b9d47cf0"], text) == "reset"


def test_a_gen_stats_match_wins_over_the_ordinal():
    verdicts = f"{LM} FAIL (post-pass: x); {LM} FAIL (runaway: wall-clock 1203s >= 1200s)"
    dispatch = _dispatch("3.1", "FAIL", stats=(3, 2)) + _dispatch("3.1", "FAIL", stats=(9, 8))
    text = _block("3.1", verdicts, dispatch)
    assert posthoc_rows.fail_reason(_fail_row(ordinal=1, served=(9, 8)), text) == "wall-clock"
    assert posthoc_rows.fail_reason(_fail_row(ordinal=2, served=(3, 2)), text) == "fail"


def test_without_gen_stats_the_ordinal_picks_the_verdict_and_a_sole_verdict_needs_none():
    two = _block("3.1", f"{LM} FAIL (runaway: wall-clock 1203s >= 1200s); {LM} FAIL (runaway: generation stop_reason=x)",
                 _dispatch("3.1", "FAIL") + _dispatch("3.1", "FAIL"))
    assert posthoc_rows.fail_reason(_fail_row(ordinal=1), two) == "wall-clock"
    assert posthoc_rows.fail_reason(_fail_row(ordinal=2), two) == "generation"
    assert posthoc_rows.fail_reason(_fail_row(ordinal=3), two) == "fail"
    one = _block("3.1", f"sonnet-medium PASS; {LM} FAIL (runaway: generation client-reset mid-response)")
    row = {k: v for k, v in _fail_row().items() if k != "ordinal"}
    assert posthoc_rows.fail_reason(row, one) == "reset"
    assert posthoc_rows.fail_reason(row, two) == "fail"  # two verdicts and no way to choose: never guessed


def test_only_a_fail_verdict_of_the_rows_own_rung_counts():
    text = _block("3.1", f"sonnet-medium FAIL (runaway: wall-clock 1203s >= 1200s); {LM} FAIL (post-pass: y)")
    assert posthoc_rows.fail_reason(_fail_row(), text) == "fail"
    assert posthoc_rows.fail_reason(_fail_row(rung="sonnet-medium"), text) == "wall-clock"
