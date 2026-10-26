"""Task 1.13: the round tail prints the coverage line.

design: finder-cap-coverage (Behavior 3)

A passing `tail-check` prints `{"ok": true, "coverage": "<line>"}` with the line
`finder_coverage.coverage_line(R)` read from the round BEFORE `cleanup_round` runs —
so a closing round whose strip removes the merged file still prints the real line.
A failing `tail-check` still refuses with today's `tail-failed` payload and no
coverage figure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import finder_segments as fs  # noqa: E402
import round_scratch as rs  # noqa: E402


def _env(terminal=None):
    return {"schema": "tp-pr-iterate/round-tail/v1", "round": 1,
            "head_reviewed": "a" * 40, "head_after": "b" * 40,
            "tally": {"P": 0, "X": 0, "T": 0, "C": 0, "blocking": 0, "degraded": 0},
            "downgraded": 0, "notes": 0, "action": "noop", "fix_commit": None,
            "terminal": terminal, "converged": False,
            "budget": {"iteration": 1, "round_cap": 6, "signal": None, "holding": []},
            "finalizer_stop": None, "summary": "s"}


def _seg(name, sid, files):
    """A segment manifest entry (the shape `expand_angles` and `retry` write)."""
    return {"name": name, "model": "local", "role": "finder",
            "segment": {"angle": "correctness", "id": sid, "files": list(files),
                        "lines": 100, "fraction": 0.5}}


def _round(rd, entries, *, percent=None, uncovered=(), terminal=None, envelope=True):
    """A round dir with a valid tail envelope, `entries` in `angles.json`, and —
    when `percent` is given — a merged file carrying that coverage figure."""
    rd.mkdir(parents=True, exist_ok=True)
    if envelope:
        (rd / "tail").mkdir(parents=True)
        (rd / "tail" / "envelope.json").write_text(json.dumps(_env(terminal)),
                                                   encoding="utf-8")
    (rd / "angles.json").write_text(json.dumps({"angles": entries}), encoding="utf-8")
    if percent is not None:
        dest = rd / "opus-check"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / fs.MERGED).write_text(
            json.dumps({"coverage": {"fraction": percent / 100, "percent": percent,
                                     "files_changed": 10, "files_covered": percent // 10},
                        "uncovered_files": list(uncovered)}), encoding="utf-8")
    return rd


def test_tail_check_ok_prints_the_coverage_line(tmp_path, capsys):
    rd = _round(tmp_path / "r1", [_seg("correctness-s1", "s1", ["a.py"])],
                percent=70, uncovered=["x.py", "y.py", "z.py"])
    assert rs.main(["tail-check", "--round-dir", str(rd)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "ok": True, "coverage": "coverage 70%: 3 files reviewed only by the Opus check"}


def test_tail_check_ok_not_segmented(tmp_path, capsys):
    rd = _round(tmp_path / "r1", [{"name": "edge", "role": "finder"}])
    assert rs.main(["tail-check", "--round-dir", str(rd)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "ok": True, "coverage": "coverage n/a (not segmented)"}


def test_tail_check_ok_merge_not_run(tmp_path, capsys):
    rd = _round(tmp_path / "r1", [_seg("correctness-s1", "s1", ["a.py"])])
    assert rs.main(["tail-check", "--round-dir", str(rd)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "ok": True, "coverage": "coverage unknown (merge not run)"}


def test_coverage_is_read_before_the_closing_strip(tmp_path, capsys):
    # A closing terminal strips the round; the line still reads the merged file,
    # because the coverage figure is computed before `cleanup_round`.
    rd = _round(tmp_path / "r1", [_seg("correctness-s1", "s1", ["a.py"])],
                percent=70, uncovered=["x.py", "y.py", "z.py"], terminal="two-stable")
    assert rs.main(["tail-check", "--round-dir", str(rd)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "ok": True, "coverage": "coverage 70%: 3 files reviewed only by the Opus check"}


def test_tail_check_failed_still_refuses_with_todays_payload(tmp_path, capsys):
    rd = _round(tmp_path / "r1", [_seg("correctness-s1", "s1", ["a.py"])],
                percent=70, uncovered=["x.py"], envelope=False)
    assert rs.main(["tail-check", "--round-dir", str(rd)]) == 2
    out = capsys.readouterr().out.strip().splitlines()
    assert json.loads(out[-1]) == {"terminal": "needs-human-attention",
                                   "reason": "tail-failed"}
    assert '"ok"' not in "".join(out)
