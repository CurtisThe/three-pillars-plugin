"""Task 1.12: the proof digest prints coverage and budget skips.

design: finder-cap-coverage (Behaviors 3, 4, 5, 6)

`angles.digest_labels(manifest, counts, coverage)` posts the digest with what
`finder_coverage.coverage_line` read from the round: the Opus check's label carries the
coverage figure (under 80% it names the files only the check saw), a `segment-budget`
skip names its file count beside its segment id, a retried parent names its two halves
instead of falling into the `no local backend` catch-all, and a `capped` or `partial`
telemetry outcome reads ahead of the parse-lift mark's old `unparseable` suffix.
`coverage=None` — a caller that never computed a line — gives today's labels exactly,
and the label count is always the manifest's angle count: coverage never posts a
pseudo-angle.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import angles  # noqa: E402
import finder_coverage as fc  # noqa: E402
import finder_segments as fs  # noqa: E402

MARK = "re-covered-by-opus-check"
CHECK = {"name": "opus-check", "model": "opus", "role": "confirmer"}


def _seg(name, sid, files, **kw):
    """A segment manifest entry (the shape `expand_angles` and `retry` write)."""
    e = {"name": name, "model": "local", "role": "finder",
         "segment": {"angle": "correctness", "id": sid, "files": list(files), "lines": 100,
                     "fraction": 0.5}}
    return {**e, **kw}


def _round(rd, entries, *, percent=None, uncovered=()):
    """The round's `angles.json`, plus its merged file when `percent` is given."""
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "angles.json").write_text(json.dumps({"angles": entries}), encoding="utf-8")
    if percent is None:
        return rd
    dest = rd / "opus-check"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / fs.MERGED).write_text(
        json.dumps({"coverage": {"fraction": percent / 100, "percent": percent,
                                 "files_changed": 10, "files_covered": percent // 10},
                    "uncovered_files": list(uncovered)}), encoding="utf-8")
    return rd


def _digest(rd, entries, counts=None):
    """The posted labels, through the round dir's own coverage line."""
    labels = angles.digest_labels({"angles": entries}, counts or {},
                                  coverage=fc.coverage_line(rd))
    assert len(labels) == len(entries)  # never a pseudo-angle
    return [label for label, _count in labels]


# Behavior 4: under 80% the check label says how many files only the check reviewed.
def test_coverage_under_80_names_the_files_only_the_check_saw(tmp_path):
    entries = [_seg("correctness-s1", "s1", ["a.py"]), CHECK]
    rd = _round(tmp_path, entries, percent=70, uncovered=("x.py", "y.py", "z.py"))
    assert _digest(rd, entries) == [
        "correctness-s1[local/finder]",
        "opus-check[opus/confirmer] [coverage 70%: 3 files reviewed only by the "
        "Opus check]",
    ]


# Behavior 3: at or over 80% the figure is the whole line.
def test_coverage_at_or_over_80_is_just_the_percent(tmp_path):
    entries = [_seg("correctness-s1", "s1", ["a.py"]), CHECK]
    rd = _round(tmp_path, entries, percent=85)
    assert _digest(rd, entries) == [
        "correctness-s1[local/finder]",
        "opus-check[opus/confirmer] [coverage 85%]",
    ]


# Behavior 5: a budget skip is visible by segment id (in its name) and file count.
def test_segment_budget_skip_names_its_file_count(tmp_path):
    entries = [_seg("correctness-s5", "s5", [f"f{i}.py" for i in range(9)],
                    skipped="segment-budget"), CHECK]
    rd = _round(tmp_path, entries, percent=100)
    assert _digest(rd, entries, {"correctness-s5": 0}) == [
        "correctness-s5[local/finder] [skipped: segment budget, 9 files]",
        "opus-check[opus/confirmer] [coverage 100%]",
    ]


# Behavior 2: a retried parent never reads as the backend-absent catch-all.
def test_retried_parent_names_its_two_halves(tmp_path):
    entries = [_seg("correctness-s2", "s2", ["a.py", "b.py"], skipped="retried",
                    telemetry={"outcome": "retried"}), CHECK]
    rd = _round(tmp_path, entries, percent=100)
    assert _digest(rd, entries) == [
        "correctness-s2[local/finder] [retried: split into correctness-s2a, "
        "correctness-s2b]",
        "opus-check[opus/confirmer] [coverage 100%]",
    ]


# Behavior 1/3: a capped segment says so, not the parse-lift mark's old wording.
def test_capped_outcome_replaces_the_unparseable_suffix(tmp_path):
    entries = [_seg("correctness-s3", "s3", ["a.py"], unparseable=MARK,
                    telemetry={"outcome": "capped", "covered_files": []}), CHECK]
    rd = _round(tmp_path, entries, percent=50, uncovered=("a.py",))
    labels = _digest(rd, entries)
    assert labels[0] == "correctness-s3[local/finder] [capped: re-covered by opus-check]"
    assert "unparseable" not in labels[0]


# A `partial` segment names the files it covered against its whole.
def test_partial_outcome_names_covered_against_its_whole(tmp_path):
    entries = [_seg("correctness-s4", "s4", ["a.py", "b.py", "c.py"],
                    telemetry={"outcome": "partial", "covered_files": ["a.py"]}), CHECK]
    rd = _round(tmp_path, entries, percent=34, uncovered=("b.py", "c.py"))
    assert _digest(rd, entries) == [
        "correctness-s4[local/finder] [partial: 1 of 3 files]",
        "opus-check[opus/confirmer] [coverage 34%: 2 files reviewed only by the "
        "Opus check]",
    ]


# Backward compatible manifest: no telemetry, the mark alone keeps today's suffix.
def test_old_format_unparseable_entry_keeps_todays_suffix(tmp_path):
    entries = [_seg("correctness-s3", "s3", ["a.py"], unparseable=MARK), CHECK]
    rd = _round(tmp_path, entries, percent=50, uncovered=("a.py", "b.py"))
    assert _digest(rd, entries) == [
        "correctness-s3[local/finder] [unparseable: re-covered by opus-check]",
        "opus-check[opus/confirmer] [coverage 50%: 2 files reviewed only by the "
        "Opus check]",
    ]


# Behavior 6: under the limits / off Strata, today's labels plus the n/a line.
def test_unsegmented_round_is_todays_labels_plus_the_coverage_line(tmp_path):
    entries = [{"name": "correctness-leak", "model": "opus", "role": "confirmer"},
               {"name": "scan", "model": "local", "role": "finder"}, CHECK]
    rd = _round(tmp_path, entries)
    assert _digest(rd, entries) == [
        "correctness-leak[opus/confirmer]",
        "scan[local/finder]",
        "opus-check[opus/confirmer] [coverage n/a (not segmented)]",
    ]


# Behavior 3: a segmented round whose merge did not run never prints a percent.
def test_merge_not_run_and_merge_unreadable(tmp_path):
    entries = [_seg("correctness-s1", "s1", ["a.py"]), CHECK]
    rd = _round(tmp_path, entries)
    assert _digest(rd, entries)[1] == \
        "opus-check[opus/confirmer] [coverage unknown (merge not run)]"
    dest = tmp_path / "opus-check"
    dest.mkdir(exist_ok=True)
    (dest / fs.MERGED).write_text("{nope", encoding="utf-8")
    assert _digest(tmp_path, entries)[1] == \
        "opus-check[opus/confirmer] [coverage unknown (merge unreadable)]"


# A caller that passes no coverage line (today's call) gets today's labels exactly.
def test_coverage_none_gives_todays_labels_exactly(tmp_path):
    entries = [_seg("correctness-s3", "s3", ["a.py"], unparseable=MARK),
               {"name": "scan", "model": "qwen", "role": "finder",
                "skipped": "local backend absent"}, CHECK]
    _round(tmp_path, entries, percent=70, uncovered=("a.py",))
    assert angles.digest_labels({"angles": entries}, {"correctness-s3": 2}) == [
        ("correctness-s3[local/finder] [unparseable: re-covered by opus-check]", 2),
        ("scan[qwen/finder] [skipped: no local backend]", 0),
        ("opus-check[opus/confirmer]", 0),
    ]
