"""Task 1.5: the coverage figure and per-segment telemetry in `segments-merged.json` (Behavior 3).

design: finder-cap-coverage

The merge writes today's `merged` and `uncovered_files` plus `coverage`, `segments`,
`budget_skips` and `retry_budget`. The coverage rule (plan): a file is covered when,
for EVERY segment of that angle that carries it, the segment is `delivered` or is
`partial` and named the file in its progress lines; a `skipped: "retried"` parent is
replaced by its halves and counts neither way; `percent` is the integer
`files_covered * 100 // files_changed`, never a float floor.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import finder_coverage as fc  # noqa: E402
import finder_retry as fr  # noqa: E402
import finder_segments as fs  # noqa: E402

COVERAGE_KEYS = {"fraction", "percent", "files_changed", "files_covered"}
SEGMENT_KEYS = {"id", "angle", "rung", "attempt", "lines", "files", "elapsed_s",
                "outcome", "sources", "transcript_found"}


def _file(path, n):
    return "\n".join([f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}",
                      f"@@ -1,0 +1,{n} @@"] + [f"+line {i}" for i in range(n)]) + "\n"


def _entry(name, angle, sid, files, outcome=None, covered=None, **kw):
    """A segment manifest entry; `outcome` writes the telemetry block `settle` writes."""
    e = {"name": name,
         "segment": {"angle": angle, "id": sid, "files": files, "lines": 100, "fraction": 0.5}}
    if outcome:
        e["telemetry"] = {"outcome": outcome, "covered_files": covered or [],
                          "sources": [], "transcript_found": False}
    return {**e, **kw}


def _round(tmp_path, manifest, replies=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "angles.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name, text in (replies or {}).items():
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
        (tmp_path / name / "reply.md").write_text(text, encoding="utf-8")
    return tmp_path


def _merged(tmp_path):
    return json.loads((tmp_path / "opus-check" / fs.MERGED).read_text(encoding="utf-8"))


def _delivered(name):
    return name, json.dumps({"findings": []})


# (a) 10 files in 4 segments: 3 delivered, 1 `partial` whose progress line names 1 of
# its 3 files (a finding names a second file — it stays uncovered) → 80%, 8 covered.
def _mixed_round(tmp_path, covered):
    # s1 f1-f3, s2 f4-f6, s3 f7, s4 f8-f10 — 10 files in 4 segments.
    groups = [["f1.py", "f2.py", "f3.py"], ["f4.py", "f5.py", "f6.py"], ["f7.py"],
              ["f8.py", "f9.py", "f10.py"]]
    entries = [_entry(f"edge-s{k}", "edge", f"s{k}", groups[k - 1], outcome="delivered")
               for k in (1, 2, 3)]
    entries.append(_entry("edge-s4", "edge", "s4", groups[3], outcome="partial",
                          covered=covered))
    manifest = {"angles": entries}
    replies = {e["name"]: json.dumps({"findings": []}) for e in entries[:3]}
    replies["edge-s4"] = json.dumps(
        {"findings": [{"file": "f9.py", "line_range": [3, 4], "summary": "partial take"}]})
    rd = _round(tmp_path, manifest, replies)
    assert fc.merge_round(rd) == 0
    return _merged(rd)


def test_partial_covers_only_progress_files_percent_80(tmp_path):
    out = _mixed_round(tmp_path / "with-progress", ["f8.py"])
    assert out["coverage"]["files_changed"] == 10
    assert out["coverage"]["files_covered"] == 8
    assert out["coverage"]["percent"] == 80
    assert out["coverage"]["fraction"] == 0.8
    assert out["uncovered_files"] == ["f10.py", "f9.py"]  # sorted()
    # the partial's finding still reaches the merged view
    assert any(f["file"] == "f9.py" for f in out["merged"]["edge"])


def test_partial_with_no_progress_line_percent_70(tmp_path):
    out = _mixed_round(tmp_path / "no-progress", [])
    assert out["coverage"]["files_covered"] == 7
    assert out["coverage"]["percent"] == 70
    assert out["coverage"]["fraction"] == 0.7


def test_merged_file_carries_every_key(tmp_path):
    out = _mixed_round(tmp_path / "shape", ["f8.py"])
    assert {"merged", "uncovered_files", "coverage", "segments", "budget_skips",
            "retry_budget"} <= set(out)
    assert COVERAGE_KEYS == set(out["coverage"])
    for row in out["segments"]:
        assert SEGMENT_KEYS == set(row)
    ids = {row["id"] for row in out["segments"]}
    assert ids == {"s1", "s2", "s3", "s4"}
    assert {r["angle"] for r in out["segments"]} == {"edge"}


# (b) a `budget_skips` row per `segment-budget` entry with its id and file count, and
# `expand_angles` over a plan with `max_segments: 2` writing 2 in every segment block.
def test_plan_segments_records_max_segments():
    diff = _file("m1.py", 500) + _file("m2.py", 500) + _file("m3.py", 500)
    plan = fs.plan_segments(diff, {"max_lines": 600, "max_files": 10, "max_segments": 2})
    assert plan["max_segments"] == 2


def _expanded():
    plan = {"engaged": True, "max_segments": 2,
            "segments": [
                {"id": "s1", "files": ["a.py"], "lines": 10, "ranges": None,
                 "status": "run", "fraction": 0.5},
                {"id": "s2", "files": ["b.py"], "lines": 10, "ranges": None,
                 "status": "run", "fraction": 0.5},
                {"id": "s3", "files": ["c.py", "d.py"], "lines": 10, "ranges": None,
                 "status": f"skipped ({fs.SKIP_BUDGET})", "fraction": 0.5}]}
    entries = [{"name": "edge", "role": "finder", "model": "local", "advisory": True,
                "prompt": "p"}]
    return [a for a in fs.expand_angles(entries, plan, base="B", head="H", whole="w")
            if a.get("segment")]


def test_expand_angles_records_max_segments_in_every_block():
    segs = _expanded()
    assert len(segs) == 3 and all(s["segment"]["max_segments"] == 2 for s in segs)
    assert fr.budget({"angles": segs}, "edge") == 2


def test_budget_skips_and_retry_budget_written(tmp_path):
    segs = _expanded()
    rd = _round(tmp_path, {"angles": segs},
                {s["name"]: json.dumps({"findings": []}) for s in segs
                 if not s.get("skipped")})
    assert fc.merge_round(rd) == 0
    out = _merged(rd)
    assert out["budget_skips"] == [{"id": "s3", "angle": "edge", "files": 2}]
    assert out["retry_budget"] == {"per_angle": 2, "used": {"edge": 0}}
    assert out["uncovered_files"] == ["c.py", "d.py"]


def test_retry_used_counts_attempt_minus_one(tmp_path):
    entries = [_entry("edge-s1", "edge", "s1", ["a.py"], outcome="delivered", attempt=2),
               _entry("edge-s2", "edge", "s2", ["b.py"], outcome="delivered", attempt=3),
               _entry("edge-s3", "edge", "s3", ["c.py"], outcome="delivered")]
    rd = _round(tmp_path, {"angles": entries},
                {e["name"]: json.dumps({"findings": []}) for e in entries})
    assert fc.merge_round(rd) == 0
    assert _merged(rd)["retry_budget"]["used"] == {"edge": 3}


# (c) a half marked `capped` after a Sonnet re-run → its files in `uncovered_files`.
def test_half_capped_again_on_sonnet_is_uncovered(tmp_path):
    e = _entry("edge-s1", "edge", "s1", ["a.py", "b.py"], outcome="capped",
               rung="sonnet-xhigh", attempt=3)
    rd = _round(tmp_path, {"angles": [e]}, {})
    assert fc.merge_round(rd) == 0
    out = _merged(rd)
    assert out["uncovered_files"] == ["a.py", "b.py"]
    row = out["segments"][0]
    assert row["outcome"] == "capped" and row["rung"] == "sonnet-xhigh"
    assert row["attempt"] == 3
    assert out["coverage"]["percent"] == 0


# (d) a hunk-split file in two range segments, one delivered and one `capped` → uncovered.
def test_hunk_split_file_uncovered_when_any_range_segment_capped(tmp_path):
    entries = [_entry("edge-s1", "edge", "s1", ["big.py"], outcome="delivered"),
               _entry("edge-s2", "edge", "s2", ["big.py"], outcome="capped")]
    rd = _round(tmp_path, {"angles": entries},
                {"edge-s1": json.dumps({"findings": []})})
    assert fc.merge_round(rd) == 0
    out = _merged(rd)
    assert out["uncovered_files"] == ["big.py"]
    assert out["coverage"] == {"fraction": 0.0, "percent": 0, "files_changed": 1,
                               "files_covered": 0}


# (e) a parent `skipped: "retried"` whose two halves both delivered leaves its files
# covered and counts its own entry only as `retried`.
def test_retried_parent_counts_neither_way(tmp_path):
    entries = [_entry("edge-s1", "edge", "s1", ["a.py"], skipped="retried"),
               _entry("edge-s1a", "edge", "s1", ["a.py"], outcome="delivered", attempt=2),
               _entry("edge-s1b", "edge", "s1", ["a.py"], outcome="delivered", attempt=2)]
    rd = _round(tmp_path, {"angles": entries},
                {e["name"]: json.dumps({"findings": []}) for e in entries[1:]})
    assert fc.merge_round(rd) == 0
    out = _merged(rd)
    assert out["uncovered_files"] == []
    assert out["coverage"] == {"fraction": 1.0, "percent": 100, "files_changed": 1,
                               "files_covered": 1}
    outcomes = {r["outcome"] for r in out["segments"]}
    assert "retried" in outcomes and "skipped" not in outcomes


# (f) 29 covered of 100 changed → percent 29 (a float floor of 0.29*100 gives 28).
def test_percent_is_integer_division_never_float_floor(tmp_path):
    files = [f"g{i}.py" for i in range(100)]
    entries = [_entry(f"edge-s{k + 1}", "edge", f"s{k + 1}", [files[k]],
                      outcome="delivered" if k < 29 else "capped") for k in range(100)]
    rd = _round(tmp_path, {"angles": entries},
                {e["name"]: json.dumps({"findings": []}) for e in entries[:29]})
    assert fc.merge_round(rd) == 0
    out = _merged(rd)
    assert out["coverage"]["files_changed"] == 100
    assert out["coverage"]["files_covered"] == 29
    assert out["coverage"]["percent"] == 29  # int(0.29 * 100) would print 28
    assert out["coverage"]["fraction"] == 0.29
    assert len(out["uncovered_files"]) == 71


# Task 1.6: an entry with NO telemetry is never `delivered` by default — only when its
# reply parses and is not placeholder-only (a `put-capped` reply is never delivered).
def test_no_telemetry_placeholder_reply_is_never_delivered(tmp_path):
    e = _entry("edge-s1", "edge", "s1", ["a.py"])
    rd = _round(tmp_path / "ph", {"angles": [e]},
                {"edge-s1": json.dumps({"findings": [{"capped": True, "text": ""}]})})
    assert fc.merge_round(rd) == 0
    out = _merged(rd)
    assert out["segments"][0]["outcome"] != "delivered"
    assert out["uncovered_files"] == ["a.py"]
    assert out["coverage"]["percent"] == 0


def test_no_telemetry_parsing_reply_is_delivered(tmp_path):
    e = _entry("edge-s1", "edge", "s1", ["a.py"])
    rd = _round(tmp_path / "ok", {"angles": [e]}, {"edge-s1": json.dumps({"findings": []})})
    assert fc.merge_round(rd) == 0
    out = _merged(rd)
    assert out["segments"][0]["outcome"] == "delivered"
    assert out["coverage"]["percent"] == 100


def test_round_with_no_segment_entries_writes_nothing(tmp_path):
    rd = _round(tmp_path, {"angles": [{"name": "edge", "role": "finder"}]}, {})
    assert fc.merge_round(rd) == 0
    assert not (tmp_path / "opus-check" / fs.MERGED).exists()


def test_planned_segments_carry_integer_lines_into_every_row(tmp_path):
    """The segment blocks `expand_angles` writes carry `lines`, so every first-attempt
    telemetry row the merge writes has an integer size, never `null`."""
    diff = "".join(_file(f"m{i}.py", 100) for i in range(12))
    plan = fs.plan_segments(diff, {"max_lines": 600, "max_files": 10, "max_segments": 4})
    finder = {"name": "edge", "role": "finder", "model": "local", "advisory": True, "prompt": "p"}
    segs = [a for a in fs.expand_angles([finder], plan, base="B", head="H", whole="w")
            if a.get("segment")]
    rd = _round(tmp_path, {"angles": segs},
                {segs[0]["name"]: json.dumps({"findings": []})})
    assert fc.merge_round(rd) == 0
    rows = _merged(rd)["segments"]
    assert len(rows) == len(segs) >= 2
    assert all(isinstance(r["lines"], int) and r["lines"] > 0 for r in rows)
    assert sum(r["lines"] for r in rows) == plan["lines"]
