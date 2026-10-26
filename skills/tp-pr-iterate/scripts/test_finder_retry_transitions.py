"""finder_retry.settle — every capped transition, budget first.

design: finder-cap-coverage (Task 1.4), Behavior 2: on a `capped` outcome `settle`
answers `retry` / `sonnet` / `uncovered` from the plan's budget-first rule against
`finder_retry.budget` and `retry_used`, writes the Sonnet rung, clears the stale
slot files, and marks every `uncovered` entry so the converge step never refuses
the round as `unparseable-review-angle`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import agent_caps_watch  # noqa: E402
import finder_round  # noqa: E402
import finder_retry  # noqa: E402
import finder_segments as fs  # noqa: E402

SEG_FILES = ["a.py", "b.py", "c.py"]


def _seg(angle="correctness", sid="s2", **kw):
    return {"angle": angle, "id": sid, "of": 2, "files": list(SEG_FILES),
            "fraction": 1.0, "lines": 400, **kw}


def _entry(round_dir, name, seg, **kw):
    return {"name": name, "role": "finder", "model": "local", "advisory": True,
            "reply_path": str(round_dir / name / "reply.md"), "segment": seg, **kw}


def _manifest(round_dir, entries):
    """Write `angles.json` from segment entry dicts, creating each slot dir."""
    for e in entries:
        (round_dir / e["name"]).mkdir(parents=True, exist_ok=True)
    (round_dir / "angles.json").write_text(
        json.dumps({"angles": entries}, indent=2) + "\n", encoding="utf-8")
    return entries


def _read_entry(round_dir, name):
    man = json.loads((round_dir / "angles.json").read_text(encoding="utf-8"))
    return next(e for e in man["angles"] if e["name"] == name)


def _spawned_slot(round_dir, name):
    """A live slot: `spawn.json` from the real recorder, a non-stopped `caps.json`."""
    agent_caps_watch.record_spawn(round_dir, name, "abc", 0.0)
    (round_dir / name / "caps.json").write_text(
        json.dumps({"warned": True, "stopped": False}) + "\n", encoding="utf-8")


def test_half_capped_answers_sonnet_and_clears_the_slot(tmp_path):
    half = _entry(tmp_path, "correctness-s2a", _seg(sid="s2a", retry_of="correctness-s2"),
                  attempt=2, dispatch_model="strata")
    _manifest(tmp_path, [half])
    _spawned_slot(tmp_path, half["name"])
    assert [s["slot"] for s in agent_caps_watch.running(tmp_path)] == [half["name"]]
    out = finder_retry.settle(tmp_path, half["name"], capped=True)
    assert out["outcome"] == "capped" and out["next"] == "sonnet"
    after = _read_entry(tmp_path, half["name"])
    assert after["rung"] == "sonnet-xhigh" and after["attempt"] == 3
    for name in ("reply.md", "caps.json", "spawn.json"):
        assert not (tmp_path / half["name"] / name).exists()
    assert agent_caps_watch.running(tmp_path) == []
    tel = after["telemetry"]
    assert tel["elapsed_s"] is None and tel["covered_files"] == []


def test_sonnet_capped_again_is_uncovered_and_marked(tmp_path):
    half = _entry(tmp_path, "correctness-s2a", _seg(sid="s2a", retry_of="correctness-s2"),
                  attempt=2, dispatch_model="strata")
    _manifest(tmp_path, [half])
    _spawned_slot(tmp_path, half["name"])
    assert finder_retry.settle(tmp_path, half["name"], capped=True)["next"] == "sonnet"
    out = finder_retry.settle(tmp_path, half["name"], capped=True)
    assert out["outcome"] == "capped" and out["next"] == "uncovered"
    after = _read_entry(tmp_path, half["name"])
    assert after["unparseable"] == "re-covered-by-opus-check"
    assert after["telemetry"]["outcome"] == "capped"
    assert finder_round.parse_required({"angles": [after]}) == []
    assert finder_retry.retry_used({"angles": [after]}, "correctness") == 2


def test_capped_first_attempt_with_budget_free_answers_retry(tmp_path):
    e = _entry(tmp_path, "correctness-s1", _seg(sid="s1"))
    _manifest(tmp_path, [e])
    out = finder_retry.settle(tmp_path, e["name"], capped=True)
    assert out["outcome"] == "capped" and out["next"] == "retry"
    after = _read_entry(tmp_path, e["name"])
    assert "rung" not in after and "attempt" not in after
    assert "unparseable" not in after


def test_capped_first_attempt_is_strata_whatever_dispatch_model_says(tmp_path):
    e = _entry(tmp_path, "correctness-s1", _seg(sid="s1"), dispatch_model="sonnet")
    _manifest(tmp_path, [e])
    out = finder_retry.settle(tmp_path, e["name"], capped=True)
    assert out["next"] == "retry"
    assert "rung" not in _read_entry(tmp_path, e["name"])


def test_budget_exhausted_answers_uncovered_and_marks(tmp_path):
    a = _entry(tmp_path, "correctness-s1", _seg(sid="s1", max_segments=2), attempt=3)
    b = _entry(tmp_path, "correctness-s2", _seg(sid="s2", max_segments=2))
    _manifest(tmp_path, [a, b])
    man = {"angles": [a, b]}
    assert finder_retry.budget(man, "correctness") == 2
    assert finder_retry.retry_used(man, "correctness") == 2
    out = finder_retry.settle(tmp_path, b["name"], capped=True)
    assert out["outcome"] == "capped" and out["next"] == "uncovered"
    after = _read_entry(tmp_path, b["name"])
    assert after["unparseable"] == "re-covered-by-opus-check"
    assert after["telemetry"]["outcome"] == "capped"
    assert "rung" not in after


def test_final_on_a_capped_first_attempt_answers_uncovered(tmp_path):
    e = _entry(tmp_path, "correctness-s1", _seg(sid="s1"))
    _manifest(tmp_path, [e])
    out = finder_retry.settle(tmp_path, e["name"], capped=True, final=True)
    assert out["outcome"] == "capped" and out["next"] == "uncovered"
    after = _read_entry(tmp_path, e["name"])
    assert after["unparseable"] == "re-covered-by-opus-check"
    assert "rung" not in after


def test_budget_reads_segment_blocks_else_defaults(tmp_path):
    e = _entry(tmp_path, "correctness-s1", _seg(sid="s1"))
    assert finder_retry.budget({"angles": [e]}, "correctness") == fs.DEFAULTS["max_segments"]
    assert finder_retry.budget({"angles": []}, "correctness") == fs.DEFAULTS["max_segments"]


def test_retry_used_sums_attempt_minus_one_over_the_angle(tmp_path):
    a = _entry(tmp_path, "correctness-s1", _seg(sid="s1"), attempt=2)
    b = _entry(tmp_path, "correctness-s2", _seg(sid="s2"))
    c = _entry(tmp_path, "security-s1", _seg(angle="security", sid="s1"), attempt=3)
    man = {"angles": [a, b, c]}
    assert finder_retry.retry_used(man, "correctness") == 1
    assert finder_retry.retry_used(man, "security") == 2
    assert finder_retry.retry_used(man, "nope") == 0


def _capped_half_with_strata_time(round_dir):
    """A half settled capped with the Strata run's 900 s, then a delivered Sonnet reply."""
    half = _entry(round_dir, "correctness-s2a", _seg(sid="s2a", retry_of="correctness-s2"),
                  attempt=2)
    _manifest(round_dir, [half])
    out = finder_retry.settle(round_dir, half["name"], capped=True, elapsed_s=900)
    assert out["next"] == "sonnet"
    tel = _read_entry(round_dir, half["name"])["telemetry"]
    assert tel["elapsed_s"] is None and tel["covered_files"] == []
    assert tel["strata_elapsed_s"] == 900
    (round_dir / half["name"] / "reply.md").write_text(
        json.dumps({"findings": []}) + "\n", encoding="utf-8")
    return half["name"]


def test_sonnet_rung_never_carries_the_strata_elapsed_time_via_settle(tmp_path):
    name = _capped_half_with_strata_time(tmp_path)
    assert finder_retry.settle(tmp_path, name)["outcome"] == "delivered"
    after = _read_entry(tmp_path, name)
    assert after["rung"] == "sonnet-xhigh"
    assert after["telemetry"]["elapsed_s"] is None
    assert after["telemetry"]["strata_elapsed_s"] == 900


def test_sonnet_rung_never_carries_the_strata_elapsed_time_via_the_merge(tmp_path):
    import finder_coverage  # noqa: PLC0415

    name = _capped_half_with_strata_time(tmp_path)
    assert finder_coverage.merge_round(tmp_path) == 0
    merged = json.loads((tmp_path / "opus-check" / fs.MERGED).read_text(encoding="utf-8"))
    row = next(r for r in merged["segments"] if r["id"] == "s2a")
    assert row["rung"] == "sonnet-xhigh" and row["outcome"] == "delivered"
    assert row["elapsed_s"] is None
    assert _read_entry(tmp_path, name)["telemetry"]["elapsed_s"] is None
