"""Task 1.9: `split_segment` halves one capped segment at file, then hunk, boundaries.

design: finder-cap-coverage (Behaviors 2) — the retry re-plan needs a segment cut in
two. Rows come from `finder_segments.parse_diff`; the function reads no manifest and
touches no filesystem.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import finder_retry as fr  # noqa: E402
import finder_segments as fs  # noqa: E402


def _file(path, n, hunks=1, start_step=100):
    """A diff for one file: `n` added lines spread over `hunks` new-side hunks."""
    out = [f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}"]
    per = n // hunks
    for h in range(hunks):
        out.append(f"@@ -{h * start_step + 1},0 +{h * start_step + 1},{per} @@")
        out += [f"+line {i}" for i in range(per)]
    return "\n".join(out)


def _rows(*files):
    return fs.parse_diff("\n".join(files) + "\n")


def _seg(*paths):
    return {"files": list(paths), "lines": 0, "ranges": None}


def test_multi_file_segment_splits_at_file_boundaries_balanced_by_lines():
    rows = _rows(_file("a.py", 100), _file("b.py", 80), _file("c.py", 60), _file("d.py", 40))
    got = fr.split_segment(_seg("a.py", "b.py", "c.py", "d.py"), rows)
    assert got is not None
    half_a, half_b = got
    assert [half_a["lines"], half_b["lines"]] == [140, 140]
    assert sorted(half_a["files"] + half_b["files"]) == ["a.py", "b.py", "c.py", "d.py"]
    assert half_a["ranges"] is None and half_b["ranges"] is None
    assert set(half_a["files"]).isdisjoint(half_b["files"])


def test_one_file_two_hunks_splits_at_hunk_boundaries_with_ranges():
    rows = _rows(_file("big.py", 60, hunks=3))
    got = fr.split_segment(_seg("big.py"), rows)
    assert got is not None
    half_a, half_b = got
    assert half_a["files"] == half_b["files"] == ["big.py"]
    assert half_a["ranges"] and half_b["ranges"]
    assert half_a["ranges"][1] < half_b["ranges"][0]  # ordered, disjoint
    spans = [(h["start"], h["end"]) for h in fs.parse_diff(_file("big.py", 60, hunks=3))[0]["hunks"]]
    assert half_a["ranges"][0] == spans[0][0]  # the halves together span every hunk
    assert half_b["ranges"][1] == spans[-1][1]
    # each half is one contiguous run of the file's hunks, and the runs partition them
    def run(rng):
        return [s for s in spans if rng[0] <= s[0] <= rng[1]]
    assert run(half_a["ranges"]) + run(half_b["ranges"]) == spans
    assert run(half_a["ranges"]) and run(half_b["ranges"])
    assert half_a["lines"] + half_b["lines"] == 60


def test_one_file_one_hunk_is_unsplittable():
    rows = _rows(_file("one.py", 900))
    assert fr.split_segment(_seg("one.py"), rows) is None


def test_rows_outside_the_segment_are_ignored():
    rows = _rows(_file("a.py", 100), _file("b.py", 80), _file("stray.py", 5000))
    plain = fr.split_segment(_seg("a.py", "b.py"), _rows(_file("a.py", 100), _file("b.py", 80)))
    with_stray = fr.split_segment(_seg("a.py", "b.py"), rows)
    assert with_stray == plain
    assert sum(h["lines"] for h in with_stray) == 180


def _planned_segments(diff, max_lines):
    """The segment blocks the real round preparation writes: `plan_segments` then
    `expand_angles`, over one Strata finder."""
    plan = fs.plan_segments(diff, {"max_lines": max_lines, "max_files": 10, "max_segments": 4})
    assert plan["engaged"]
    finder = {"name": "edge", "role": "finder", "model": "local", "advisory": True, "prompt": "p"}
    return [e["segment"] for e in fs.expand_angles([finder], plan, base="B", head="H", whole="w")]


def test_hunk_range_segment_splits_only_its_own_hunks():
    """A capped range segment of an oversized file halves ITS hunks, never the whole file's:
    each half is smaller than the parent and stays inside the parent's range."""
    diff = _file("big.py", 1500, hunks=6, start_step=500) + "\n"
    rows = fs.parse_diff(diff)
    segs = _planned_segments(diff, 600)
    assert len(segs) > 1 and all(s["ranges"] for s in segs)
    for parent in segs:
        got = fr.split_segment(parent, rows)
        assert got is not None
        for half in got:
            assert half["lines"] < parent["lines"]
            assert parent["ranges"][0] <= half["ranges"][0] <= half["ranges"][1] <= parent["ranges"][1]
        assert got[0]["lines"] + got[1]["lines"] == parent["lines"]


def test_hunk_range_segment_with_one_hunk_is_unsplittable():
    diff = _file("big.py", 1500, hunks=6, start_step=500) + "\n"
    rows = fs.parse_diff(diff)
    for parent in _planned_segments(diff, 300):  # one 250-line hunk per segment
        assert fr.split_segment(parent, rows) is None
