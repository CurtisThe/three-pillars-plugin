"""Tests for cheap_ab.py — the review-prep A/B spend (cheap-tier-review-prep Task 7.2).

`rp-draft:` rows (the review-prep drafter's `ab_pair` prefix) are charged by `budget`
but stay `unpaired_on` in `summarize`; an `ab_arm: base` row is never charged (the real
Opus angle runs anyway). Only the incremental spend draws on the 8M cap.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_ab as ab  # noqa: E402


def _row(**extra) -> dict:
    # A spawned drafter row carries its `agent`; `agent: null` is an inline row, which
    # `budget` charges the measured mean instead of `UNKNOWN_ROW_TOKENS` (#196).
    return {"slot": "review_slice", "rung": "local-medium", "agent": "tp-drafter",
            "oracle": "pass", "tokens": 1000, **extra}


def test_budget_charges_rp_draft_and_prep_rows():
    rows = [_row(ab_pair="rp-draft:12:1", tokens=1000),
            _row(ab_pair="rp-draft:12:2", ab_arm="prep", tokens=2000),
            _row(ab_pair="rp-draft:12:3", ab_arm="prep", tokens=None)]  # null -> UNKNOWN_ROW_TOKENS
    assert ab.budget(rows)["spent"] == 3000 + ab.UNKNOWN_ROW_TOKENS


def test_budget_skips_ab_arm_base_rows():
    rows = [_row(ab_pair="rp-draft:12:1", ab_arm="base", tokens=10_000),
            _row(ab_pair="rp-draft:12:2", ab_arm="base", tokens=None),
            _row(ab_pair="rp-draft:12:3", ab_arm="prep", tokens=1000)]
    assert ab.budget(rows) == {"spent": 1000, "left": 8_000_000 - 1000, "exhausted": False}


def test_budget_charges_legacy_ab_pair_rows_as_today():
    rows = [_row(rung="sonnet-medium", ab_pair="p1", tokens=3000),
            _row(rung="opus-medium", ab_pair="p1", tokens=4000),
            _row(tokens=5_000_000)]  # no ab_pair: not charged
    assert ab.budget(rows) == {"spent": 7000, "left": 8_000_000 - 7000, "exhausted": False}


def test_summarize_counts_rp_draft_rows_as_unpaired():
    rows = [_row(ab_pair="rp-draft:12:1"), _row(ab_pair="rp-draft:12:2")]
    s = ab.summarize(rows)["review_slice"]
    assert s["unpaired_on"] == 2
    assert s["cheap"] == {"n": 0, "pass": 0, "rate": None, "tokens": 0}
    assert s["opus"] == {"n": 0, "pass": 0, "rate": None, "tokens": 0}


def test_summarize_rp_draft_rows_do_not_touch_legacy_pairs():
    legacy = [_row(rung="sonnet-medium", ab_pair="p1", tokens=1000),
              _row(rung="opus-medium", ab_pair="p1", tokens=4000)]
    rows = legacy + [_row(ab_pair="rp-draft:12:1"), _row(ab_pair="rp-draft:12:2")]
    s = ab.summarize(rows)["review_slice"]
    assert (s["cheap"]["n"], s["cheap"]["rate"]) == (1, 1.0)
    assert (s["opus"]["n"], s["opus"]["rate"]) == (1, 1.0)
    assert s["unpaired_on"] == 2


# --- Task 7.3: review_prep_verdict and the flip_verdict delegation (D12) ---------------


def _pair(pr, ordinal, angle, shape, base_findings, prep_findings, base_tokens, prep_tokens,
          slot="review_slice"):
    """The two rows of one review-prep pair (`rp:<pr>:<ordinal>:<angle>`)."""
    def row(ab_arm, findings, tokens):
        return {"slot": slot, "rung": "opus", "oracle": "pass", "tokens": tokens,
                "ab_pair": f"rp:{pr}:{ordinal}:{angle}", "ab_arm": ab_arm,
                "shape": shape, "findings": findings}
    return [row("base", base_findings, base_tokens), row("prep", prep_findings, prep_tokens)]


def _findings(n, classes):
    return {"n": n, "classes": classes}


def test_review_prep_verdict_cases():
    f1 = _findings(1, [["a.py", "A"]])
    f2 = _findings(2, [["a.py", "A"], ["b.py", "B"]])
    # one PR (two pairs, same PR) -> insufficient
    rows = _pair(12, 1, "s1", "s1", f1, f1, 100, 90) + _pair(12, 2, "s2", "s2", f1, f1, 100, 90)
    verdict, reason = ab.review_prep_verdict(rows, "review_slice")
    assert verdict == "insufficient"
    assert "prs=1" in reason
    # two PRs of one shape -> insufficient
    rows = _pair(12, 1, "s1", "s1", f1, f1, 100, 90) + _pair(13, 1, "s1", "s1", f1, f1, 100, 90)
    verdict, reason = ab.review_prep_verdict(rows, "review_slice")
    assert verdict == "insufficient"
    assert "shapes=1" in reason
    # unequal findings over 2 PRs / 2 shapes -> hold, naming the pair and the diff
    rows = _pair(12, 1, "s1", "s1", f1, f2, 100, 200) + _pair(13, 1, "s2", "s2", f1, f1, 100, 90)
    verdict, reason = ab.review_prep_verdict(rows, "review_slice")
    assert verdict == "hold"
    assert "rp:12:1:s1" in reason and "n 1→2" in reason and "('b.py', 'B')" in reason
    # equal findings, prep tokens == base tokens -> hold
    rows = _pair(12, 1, "s1", "s1", f1, f1, 100, 100) + _pair(13, 1, "s2", "s2", f1, f1, 100, 100)
    verdict, reason = ab.review_prep_verdict(rows, "review_slice")
    assert verdict == "hold"
    assert "200 >= base tokens 200" in reason
    # equal findings, fewer prep tokens, two shapes -> flip
    rows = _pair(12, 1, "s1", "s1", f1, f1, 100, 80) + _pair(13, 1, "s2", "s2", f1, f1, 200, 150)
    verdict, reason = ab.review_prep_verdict(rows, "review_slice")
    assert verdict == "flip"
    assert "prep tokens 230 < base 300" in reason
    # repro_scaffold: no same-head pair — oracle accept rate, 3 pass + 1 fail -> insufficient
    rows = [dict(_row(slot="repro_scaffold", oracle="pass")) for _ in range(3)] + \
        [dict(_row(slot="repro_scaffold", oracle="fail"))]
    verdict, reason = ab.review_prep_verdict(rows, "repro_scaffold")
    assert verdict == "insufficient"
    assert "3/4" in reason
    # a half pair (one arm missing) and a pair missing `findings` are ignored
    half = _pair(12, 1, "s1", "s1", f1, f1, 100, 90)[:1]
    no_findings = [dict(r, findings=None) for r in _pair(13, 1, "s1", "s1", f1, f1, 100, 90)]
    verdict, reason = ab.review_prep_verdict(half + no_findings, "review_slice")
    assert verdict == "insufficient"
    assert "pairs=0" in reason


def test_flip_verdict_delegates(tmp_path):
    tmp = tmp_path
    f1 = _findings(1, [["a.py", "A"]])
    flip_rows = (_pair(12, 1, "s1", "s1", f1, f1, 100, 80)
                 + _pair(13, 1, "s2", "s2", f1, f1, 200, 150))
    summary = ab.summarize(flip_rows)
    expected = ab.review_prep_verdict(flip_rows, "review_slice")
    assert ab.flip_verdict(summary, "review_slice", flip_rows) == expected
    # `task` stays exempt
    assert ab.flip_verdict(summary, "task")[0] == "exempt"
    # a parent slot with legacy cheap/opus pairs keeps today's verdict (not delegated)
    legacy = ([_row(slot="handoff", rung="sonnet-medium", ab_pair="p1", tokens=100),
               _row(slot="handoff", rung="opus-medium", ab_pair="p1", tokens=100)]
              + [_row(slot="handoff", rung="sonnet-medium", ab_pair="p2", tokens=100),
                 _row(slot="handoff", rung="opus-medium", ab_pair="p2", tokens=100)])
    verdict, _ = ab.flip_verdict(ab.summarize(legacy), "handoff")
    assert verdict == "flip"
    # `report` passes its rows: the review_slice table row shows `flip`
    import json as _json
    design = tmp / "three-pillars-docs" / "tp-designs" / "d"
    design.mkdir(parents=True)
    (design / "dispatch-telemetry.ndjson").write_text(
        "\n".join(_json.dumps(r) for r in flip_rows) + "\n", encoding="utf-8")
    out = ab.report(tmp)
    lines = [line for line in out.splitlines() if line.startswith("| review_slice |")]
    assert lines and "flip" in lines[0]
