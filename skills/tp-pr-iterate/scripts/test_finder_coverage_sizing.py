"""Task 1.11: first-attempt segment sizing honours an optional lines-per-cap figure.

design: finder-cap-coverage (Behavior 6, plan Task 1.11)

`review.strata_finder_lines_per_cap` (optional integer >= 1, no default) caps every
first-attempt segment's lines when it is set below `max_lines`. Absent, invalid
(`0`, `true`, `"x"`) or at or above `max_lines`, the plan is byte-equal to
`finder_segments.plan_segments(diff, cfg)` today. The engage threshold stays
`max_lines`/`max_files`, so a diff under the limits is still not engaged with any
figure. With the key set, `fraction` is the segment's lines over the figure.
Oracle: example — the 12 x 100-line diff below and the figures the plan names.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import finder_coverage as fc  # noqa: E402
import finder_segments as fs  # noqa: E402

CFG = {"max_lines": 600, "max_files": 10, "max_segments": 4}


def _file(path, n):
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -1,0 +1,{n} @@\n" + "\n".join(f"+line {i}" for i in range(n)))


def _diff(*files):
    return "\n".join(files) + "\n"


def _twelve():
    """12 files x 100 changed lines = the 1,200-line diff the Red names."""
    return _diff(*[_file(f"f{i}.py", 100) for i in range(12)])


def _config(figure=...):
    """The config the round carries: `false` under `strata_finder_segment`, the figure
    beside it (omitted when `figure` is `...`)."""
    review = {"strata_finder_segment": False}
    if figure is not ...:
        review["strata_finder_lines_per_cap"] = figure
    return {"review": review}


def test_lines_per_cap_caps_every_first_attempt_segment():
    plan = fc.plan_for_round(_twelve(), CFG, _config(300))
    assert plan["engaged"] and plan["segments"]
    assert all(s["lines"] <= 300 or len(s["files"]) == 1 and s["ranges"] is None
               for s in plan["segments"])
    assert [s["lines"] for s in plan["segments"]] == [300, 300, 300, 300]
    assert [s["fraction"] for s in plan["segments"]] == [1.0, 1.0, 1.0, 1.0]


def test_absent_figure_is_byte_equal_to_todays_plan():
    diff = _twelve()
    for config in (None, {}, _config()):
        assert fc.plan_for_round(diff, CFG, config) == fs.plan_segments(diff, CFG)


def test_figure_at_or_above_max_lines_is_byte_equal_to_todays_plan():
    diff = _twelve()
    for figure in (600, 900):
        assert fc.plan_for_round(diff, CFG, _config(figure)) == fs.plan_segments(diff, CFG)


def test_invalid_figure_is_byte_equal_to_todays_plan():
    diff = _twelve()
    for figure in (0, True, "x", None, 2.5, -300):
        assert fc.plan_for_round(diff, CFG, _config(figure)) == fs.plan_segments(diff, CFG)


def test_engage_threshold_stays_max_lines_and_max_files():
    small = _diff(*[_file(f"g{i}.py", 100) for i in range(5)])  # 500 lines, 5 files
    for figure in (10, 50, 300, 600, 0, True, "x"):
        plan = fc.plan_for_round(small, CFG, _config(figure))
        assert plan == fs.plan_segments(small, CFG)
        assert plan["engaged"] is False and plan["segments"] == []


def test_fraction_is_the_segments_lines_over_the_figure():
    plan = fc.plan_for_round(_twelve(), CFG, _config(500))
    assert [s["lines"] for s in plan["segments"]] == [500, 500, 200]
    assert [s["fraction"] for s in plan["segments"]] == [1.0, 1.0, 0.4]


def test_plan_for_round_never_mutates_the_cfg_it_is_given():
    cfg = copy.deepcopy(CFG)
    fc.plan_for_round(_twelve(), cfg, _config(300))
    assert cfg == CFG


def test_lines_per_cap_reads_the_key_from_the_config():
    assert fc.lines_per_cap(_config(300)) == 300
    assert fc.lines_per_cap(_config()) is None
    for figure in (0, True, "x", None, 2.5):
        assert fc.lines_per_cap(_config(figure)) is None
    for config in (None, {}, {"review": None}, {"review": []}):
        assert fc.lines_per_cap(config) is None


def test_schema_declares_the_key_with_no_default():
    schema = json.loads((_HERE.parents[1] / "_shared" / "repo-config.schema.json")
                        .read_text(encoding="utf-8"))
    key = schema["properties"]["review"]["properties"]["strata_finder_lines_per_cap"]
    assert key["type"] == "integer" and key["minimum"] == 1
    assert "default" not in key
