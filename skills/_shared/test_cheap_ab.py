"""Tests for cheap_ab.py — the cheap-tier A/B harness over dispatch telemetry.

design: cheap-tier-offload (Tasks 3.4, 3.5). Synthetic ndjson under a tmp
`three-pillars-docs/`, in both `tp-designs/` and `completed-tp-designs/`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_ab as ab  # noqa: E402


def _row(slot, rung, ok=True, *, pair=None, tokens=1000, **extra) -> dict:
    row = {"role": "drafter", "slot": slot, "rung": rung, "oracle": "pass" if ok else "fail",
           "tokens": tokens, **extra}
    if pair is not None:
        row["ab_pair"] = pair
    return row


def _pair(slot, pid, cheap_ok=True, opus_ok=True, *, cheap_tokens=1000, opus_tokens=4000):
    return [_row(slot, "sonnet-medium", cheap_ok, pair=pid, tokens=cheap_tokens),
            _row(slot, "opus-medium", opus_ok, pair=pid, tokens=opus_tokens)]


def _write(root: Path, rel: str, lines: list) -> None:
    path = root / "three-pillars-docs" / rel / "dispatch-telemetry.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join((x if isinstance(x, str) else json.dumps(x)) + "\n" for x in lines),
                    encoding="utf-8")


# --- Task 3.4: rows, arms, summary, verdict ---------------------------------------------


def test_load_rows_reads_live_and_archived_designs(tmp_path):
    _write(tmp_path, "tp-designs/a", [_row("handoff", "sonnet-medium"), "{not json",
                                      {"role": "task", "rung": "sonnet-xhigh"}])
    _write(tmp_path, "completed-tp-designs/b", [_row("handoff", "opus-medium"), "[1]", ""])
    rows, malformed = ab.load_rows(tmp_path)
    assert sorted(r["rung"] for r in rows) == ["opus-medium", "sonnet-medium"]
    assert malformed == 2  # the bad JSON and the non-object; a blank line is not counted


def test_load_rows_with_no_docs_dir(tmp_path):
    assert ab.load_rows(tmp_path) == ([], 0)


def test_arm():
    assert ab.arm({"rung": "opus-xhigh"}) == "opus" and ab.arm({"rung": "opus"}) == "opus"
    for rung in ("sonnet-medium", "local-xhigh", "code", None):
        assert ab.arm({"rung": rung}) == "cheap"


def test_summarize_rates_complete_pairs_only():
    rows = (_pair("handoff", "p1") + _pair("handoff", "p2", cheap_ok=False)
            + [_row("handoff", "sonnet-medium")]                       # plain on: unpaired
            + [_row("handoff", "sonnet-medium", pair="half")]          # half pair
            + [_row("handoff", "opus-medium", pair="dup"), _row("handoff", "opus-medium",
                                                                  pair="dup")])  # not one per arm
    s = ab.summarize(rows)["handoff"]
    assert s["unpaired_on"] == 1
    assert s["cheap"] == {"n": 2, "pass": 1, "rate": 0.5, "tokens": 2000}
    assert s["opus"] == {"n": 2, "pass": 2, "rate": 1.0, "tokens": 8000}


def test_summarize_null_token_arm_counts_for_rate_not_tokens():
    rows = _pair("handoff", "p1") + _pair("handoff", "p2", opus_tokens=None)
    s = ab.summarize(rows)["handoff"]
    assert (s["cheap"]["n"], s["opus"]["n"]) == (2, 2)
    assert (s["cheap"]["tokens"], s["opus"]["tokens"]) == (1000, 4000)


def test_summarize_alt_rows_are_rated_per_arm():
    rows = [_row("runbook", "code", pair="alt:runbook", tokens=None),
            _row("runbook", "code", False, pair="alt:runbook", tokens=None),
            _row("runbook", "opus-xhigh", pair="alt:runbook", tokens=9000)]
    s = ab.summarize(rows)["runbook"]
    assert s["cheap"] == {"n": 2, "pass": 1, "rate": 0.5, "tokens": 0}
    assert s["opus"] == {"n": 1, "pass": 1, "rate": 1.0, "tokens": 9000}
    assert s["unpaired_on"] == 0


def test_summarize_empty_arm_has_no_rate():
    s = ab.summarize([_row("handoff", "sonnet-medium")])["handoff"]
    assert s["cheap"] == {"n": 0, "pass": 0, "rate": None, "tokens": 0}


def test_flip_verdict():
    even = _pair("handoff", "p1") + _pair("handoff", "p2")
    lower = _pair("handoff", "p1") + _pair("handoff", "p2", cheap_ok=False)
    assert ab.flip_verdict(ab.summarize(even), "task")[0] == "exempt"
    assert ab.flip_verdict(ab.summarize(_pair("handoff", "p1")), "handoff")[0] == "insufficient"
    assert ab.flip_verdict({}, "handoff")[0] == "insufficient"
    assert ab.flip_verdict(ab.summarize(lower), "handoff")[0] == "hold"
    verdict, reason = ab.flip_verdict(ab.summarize(even), "handoff")
    assert verdict == "flip" and "1.0" in reason


def test_no_flip_when_the_opus_arm_never_passes():
    # 0.00 vs 0.00 is not "at least as often": with no Opus baseline there is no evidence
    both_fail = (_pair("handoff", "p1", cheap_ok=False, opus_ok=False)
                 + _pair("handoff", "p2", cheap_ok=False, opus_ok=False))
    verdict, reason = ab.flip_verdict(ab.summarize(both_fail), "handoff")
    assert verdict == "hold" and "never passed" in reason


def test_summarize_skips_a_row_whose_oracle_is_not_pass_or_fail():
    odd = [_row("handoff", "sonnet-medium", pair="p3", oracle="ok"),
           _row("handoff", "opus-medium", pair="p3")]
    s = ab.summarize(_pair("handoff", "p1") + odd)["handoff"]
    assert (s["cheap"]["n"], s["opus"]["n"]) == (1, 1)  # p3 is a half pair now


# --- Task 3.5: budget + CLI -------------------------------------------------------------


def test_budget():
    assert ab.UNKNOWN_ROW_TOKENS == 200_000
    assert ab.budget([]) == {"spent": 0, "left": 8_000_000, "exhausted": False}
    rows = _pair("handoff", "p1", cheap_tokens=3_000_000, opus_tokens=4_999_999)
    assert ab.budget(rows) == {"spent": 7_999_999, "left": 1, "exhausted": False}
    edge = rows + [_row("handoff", "sonnet-medium", pair="p2", tokens=1)]
    assert ab.budget(edge) == {"spent": 8_000_000, "left": 0, "exhausted": True}
    # A null-token row is charged 200k; a plain `on` row (no ab_pair) is not charged.
    nulls = [_row("handoff", "opus-medium", pair="p3", tokens=None),
             _row("handoff", "sonnet-medium", tokens=5_000_000)]
    assert ab.budget(nulls)["spent"] == 200_000
    # A `code` row ran no model: charged 0, so 41 of them never exhaust the cap.
    code = [_row("runbook", "code", pair="alt:runbook", tokens=None) for _ in range(41)]
    assert ab.budget(code) == {"spent": 0, "left": 8_000_000, "exhausted": False}
    assert ab.budget(rows, cap=100)["exhausted"] is True


def test_alt_arm():
    alt = [_row("runbook", "code", pair="alt:runbook", tokens=None)]
    other = [_row("handoff", "sonnet-medium", pair="alt:handoff"),
             _row("runbook", "code", tokens=None)]  # plain on: not an alternation row
    assert ab.alt_arm([], "runbook") == "cheap"
    assert ab.alt_arm(alt + other, "runbook") == "opus"
    assert ab.alt_arm(alt * 2 + other, "runbook") == "cheap"


def _run(capsys, *argv: str) -> tuple[int, str]:
    code = ab.main(list(argv))
    return code, capsys.readouterr().out


def test_cli(tmp_path, capsys):
    _write(tmp_path, "tp-designs/a", _pair("handoff", "p1") + _pair("handoff", "p2")
           + [{"role": "task", "rung": "sonnet-xhigh", "outcome": "landed"}, "{bad"])
    _write(tmp_path, "completed-tp-designs/b",
           [_row("runbook", "code", pair="alt:runbook", tokens=None)])
    code, out = _run(capsys, "report", "--root", str(tmp_path))
    assert code == 0
    assert "| slot |" in out and "| handoff |" in out and "flip" in out
    assert "| runbook |" in out and "insufficient" in out
    assert "task rows (information only): landed=1" in out and "malformed lines: 1" in out
    code, out = _run(capsys, "budget", "--root", str(tmp_path))
    assert code == 0 and json.loads(out) == {"spent": 10_000, "left": 7_990_000,
                                             "exhausted": False}
    code, out = _run(capsys, "alt-arm", "--slot", "runbook", "--root", str(tmp_path))
    assert (code, out.strip()) == (0, "opus")


def test_cli_budget_exits_0_when_exhausted(tmp_path, capsys):
    _write(tmp_path, "tp-designs/a", _pair("handoff", "p1", cheap_tokens=4_000_000,
                                           opus_tokens=4_000_000))
    code, out = _run(capsys, "budget", "--root", str(tmp_path))
    assert code == 0 and json.loads(out)["exhausted"] is True


# --- Task 7.2: the edit column ---------------------------------------------------------


def test_report_edit_column(tmp_path):
    """Each prose slot row shows the reviewed drafts' mean edit ratio; unreviewed never count."""
    import prose_oracle as po

    _write(tmp_path, "tp-designs/a", _pair("handoff", "p1") + _pair("docs_draft", "p2")
           + [_row("runbook", "code", pair="alt:runbook", tokens=None)])
    design = tmp_path / "three-pillars-docs" / "tp-designs" / "a"
    po.save_draft(design, "handoff", "## Phase\nold\n", "## Phase\nnew\n", reviewed=True)
    po.save_draft(design, "docs_draft", "same", "same", reviewed=False)
    out = ab.report(tmp_path)
    assert "| edit ratio |" in out.splitlines()[0]
    ratio = po.edit_ratio("## Phase\nold\n", "## Phase\nnew\n")
    rows = {line.split(" | ")[0].strip("| "): line for line in out.splitlines()[2:]
            if line.startswith("| ")}
    assert f"| {ratio:.2f} (n=1) |" in rows["handoff"]
    assert "| - (n=0) |" in rows["docs_draft"]
    assert "| - (n=0) |" in rows["runbook"]


# --- PR #191 review r1: pair ids are per ndjson file -----------------------------------


def test_same_pair_id_in_two_designs_keeps_both_pairs(tmp_path):
    for design in ("a", "b"):
        _write(tmp_path, f"tp-designs/{design}", _pair("handoff", "1"))
    rows, _ = ab.load_rows(tmp_path)
    s = ab.summarize(rows)["handoff"]
    assert (s["cheap"]["n"], s["opus"]["n"]) == (2, 2), s
    one = ab.summarize(_pair("handoff", "1") + _pair("handoff", "1"))["handoff"]
    assert (one["cheap"]["n"], one["opus"]["n"]) == (0, 0)  # untagged rows still group
