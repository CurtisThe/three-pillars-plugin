"""Task 1.6: the merge unions partials, never defaults to covered, and one coverage line.

design: finder-cap-coverage (Behavior 1, Behavior 3)

A delivered or partial segment's reply findings are unioned with its
`finder_coverage.read_partial` findings, deduped by file:line, so a finder that sent
partials and then a final reply holding fewer loses none. An entry with no telemetry
counts `delivered` only if its reply parses and is not placeholder-only — never by
default. A round dir written before this change still merges, with `rung`/`attempt`/
`elapsed_s` `null`. `coverage_line(R)` reads the merged file and never prints a
percent without a readable one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import agent_caps  # noqa: E402
import finder_coverage as fc  # noqa: E402
import finder_segments as fs  # noqa: E402


def _entry(rd, name, sid, files, **kw):
    """A segment manifest entry plus its slot dir on disk (no telemetry: an entry
    written before this change, or one nobody settled)."""
    (rd / name).mkdir(parents=True, exist_ok=True)
    e = {"name": name, "reply_path": str(rd / name / "reply.md"),
         "segment": {"angle": "edge", "id": sid, "files": list(files), "lines": 100,
                     "fraction": 0.5}}
    return {**e, **kw}


def _round(rd, entries, replies=None):
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "angles.json").write_text(json.dumps({"angles": entries}), encoding="utf-8")
    for name, text in (replies or {}).items():
        (rd / name).mkdir(parents=True, exist_ok=True)
        (rd / name / "reply.md").write_text(text, encoding="utf-8")
    return rd


def _merged(rd):
    return json.loads((rd / "opus-check" / fs.MERGED).read_text(encoding="utf-8"))


def _sidecar(reply_path, objs):
    for obj in objs:
        assert agent_caps.main(["put-partial", "--reply-path", str(reply_path),
                                "--finding", json.dumps(obj)]) == 0


def _spawn(rd, name, agent_id):
    assert agent_caps.main(["spawned", "--slot-root", str(rd), "--slot", name,
                            "--agent-id", agent_id, "--started", "0"]) == 0


def _transcript(cfg_dir, agent_id, texts):
    recs = [{"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": t}]}} for t in texts]
    d = Path(cfg_dir) / "projects" / "p" / "s" / "subagents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"agent-{agent_id}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")


# (a) two sidecar lines plus a delivered final reply holding one of them → both merged.
def test_sidecar_partial_unioned_with_a_delivered_reply(tmp_path):
    e = _entry(tmp_path, "edge-s1", "s1", ["a.py", "b.py"])
    f1 = {"file": "a.py", "line": 10, "summary": "lease released twice"}
    f2 = {"file": "b.py", "line": 40, "summary": "stats row has no agent"}
    _sidecar(e["reply_path"], [f1, f2])
    _round(tmp_path, [e], {"edge-s1": json.dumps({"findings": [f1]})})
    assert fc.merge_round(tmp_path) == 0
    out = _merged(tmp_path)
    assert len(out["merged"]["edge"]) == 2
    assert {f["file"] for f in out["merged"]["edge"]} == {"a.py", "b.py"}
    assert out["coverage"]["percent"] == 100  # delivered: its reply parses


# (a) the same through two `FINDING` lines in the finder's transcript.
def test_transcript_partial_unioned_with_a_delivered_reply(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    e = _entry(tmp_path, "edge-s1", "s1", ["a.py", "b.py"])
    f1 = {"file": "a.py", "line": 10, "summary": "lease released twice"}
    f2 = {"file": "b.py", "line": 40, "summary": "stats row has no agent"}
    _spawn(tmp_path, "edge-s1", "abc")
    _transcript(cfg, "abc", ["FINDING " + json.dumps(f1), "FINDING " + json.dumps(f2)])
    _round(tmp_path, [e], {"edge-s1": json.dumps({"findings": [f1]})})
    assert fc.merge_round(tmp_path) == 0
    out = _merged(tmp_path)
    assert len(out["merged"]["edge"]) == 2
    assert {f["file"] for f in out["merged"]["edge"]} == {"a.py", "b.py"}


# (b) no telemetry, no sidecar, a prose reply: never covered by default.
def test_no_telemetry_prose_reply_is_not_covered(tmp_path):
    e = _entry(tmp_path, "edge-s1", "s1", ["a.py", "b.py"])
    _round(tmp_path, [e], {"edge-s1": "I read the diff and it looks fine to me."})
    assert fc.merge_round(tmp_path) == 0
    out = _merged(tmp_path)
    assert out["segments"][0]["outcome"] == "unparseable"
    assert out["uncovered_files"] == ["a.py", "b.py"]
    assert out["coverage"]["percent"] == 0


# (b) the same unsettled prose reply leaves the merge settled `unparseable` and marked,
# so converge never refuses the round on it and nobody marks a segment by hand.
def test_merge_settles_and_marks_an_unsettled_prose_reply(tmp_path):
    import finder_round  # noqa: PLC0415
    import finder_retry  # noqa: PLC0415

    e = _entry(tmp_path, "edge-s1", "s1", ["a.py", "b.py"])
    _round(tmp_path, [e], {"edge-s1": "I read the diff and it looks fine to me."})
    assert fc.merge_round(tmp_path) == 0
    man = json.loads((tmp_path / "angles.json").read_text(encoding="utf-8"))
    after = next(x for x in man["angles"] if x["name"] == "edge-s1")
    assert after["unparseable"] == finder_retry.UNCOVERED_MARK
    assert after["telemetry"]["outcome"] == "unparseable"
    assert "rung" not in after and "attempt" not in after  # never retried
    assert finder_round.parse_required(man) == []


# (c) an old-format manifest (no telemetry, one `unparseable` entry) still merges.
def test_old_format_manifest_merges_with_null_telemetry(tmp_path):
    entries = [_entry(tmp_path, "edge-s1", "s1", ["a.py"],
                      unparseable="re-covered-by-opus-check"),
               _entry(tmp_path, "edge-s2", "s2", ["b.py"])]
    _round(tmp_path, entries,
           {"edge-s1": "prose the old parser never read",
            "edge-s2": json.dumps({"findings": []})})
    assert fc.merge_round(tmp_path) == 0
    out = _merged(tmp_path)
    rows = {r["id"]: r for r in out["segments"]}
    assert rows["s1"]["outcome"] == "unparseable"
    for key in ("rung", "attempt", "elapsed_s"):
        assert rows["s1"][key] is None
    assert rows["s2"]["outcome"] == "delivered"
    assert out["uncovered_files"] == ["a.py"]
    assert out["coverage"]["percent"] == 50


# (d) the four `coverage_line` forms.
def test_coverage_line_not_segmented(tmp_path):
    _round(tmp_path, [{"name": "edge", "role": "finder"}])
    assert fc.coverage_line(tmp_path) == "coverage n/a (not segmented)"


def test_coverage_line_merge_not_run(tmp_path):
    _round(tmp_path, [_entry(tmp_path, "edge-s1", "s1", ["a.py"])])
    assert fc.coverage_line(tmp_path) == "coverage unknown (merge not run)"


def test_coverage_line_merge_unreadable(tmp_path):
    _round(tmp_path, [_entry(tmp_path, "edge-s1", "s1", ["a.py"])])
    (tmp_path / "opus-check").mkdir(parents=True, exist_ok=True)
    (tmp_path / "opus-check" / fs.MERGED).write_text("{nope", encoding="utf-8")
    assert fc.coverage_line(tmp_path) == "coverage unknown (merge unreadable)"


def _write_merged(tmp_path, percent, uncovered):
    (tmp_path / "opus-check").mkdir(parents=True, exist_ok=True)
    (tmp_path / "opus-check" / fs.MERGED).write_text(
        json.dumps({"coverage": {"fraction": percent / 100, "percent": percent,
                                 "files_changed": 10, "files_covered": percent // 10},
                    "uncovered_files": uncovered}), encoding="utf-8")


def test_coverage_line_percent_and_under_80(tmp_path):
    _round(tmp_path, [_entry(tmp_path, "edge-s1", "s1", ["a.py"])])
    _write_merged(tmp_path, 85, [])
    assert fc.coverage_line(tmp_path) == "coverage 85%"
    _write_merged(tmp_path, 70, ["x.py", "y.py", "z.py"])
    assert fc.coverage_line(tmp_path) == \
        "coverage 70%: 3 files reviewed only by the Opus check"
