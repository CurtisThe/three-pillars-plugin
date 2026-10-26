"""finder_retry.settle — a finished segment finder becomes an outcome.

design: finder-cap-coverage (Task 1.3). Behaviors 1 and 7: the partial harvest
turns a capped segment's leftovers into a `partial` reply, a placeholder-only or
empty reply ends `capped`, and an uncapped non-empty reply that fails to parse
stays `unparseable`, never retried.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import agent_caps  # noqa: E402
import finder_round  # noqa: E402
import finder_retry  # noqa: E402
import finder_segments as fs  # noqa: E402
import review_merge  # noqa: E402

SEG_FILES = ["a.py", "b.py", "c.py"]


def _manifest(round_dir, name="correctness-s2", files=SEG_FILES, **entry_kw):
    """Write `angles.json` with one segment entry (plus the slot dir) and return it."""
    (round_dir / name).mkdir(parents=True, exist_ok=True)
    entry = {"name": name, "role": "finder", "model": "local", "advisory": True,
             "reply_path": str(round_dir / name / "reply.md"),
             "segment": {"angle": "correctness", "id": "s2", "of": 2, "files": list(files),
                         "fraction": 1.0, "lines": 400},
             **entry_kw}
    man = {"angles": [entry]}
    (round_dir / "angles.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    return man


def _entry(round_dir):
    return json.loads((round_dir / "angles.json").read_text(encoding="utf-8"))["angles"][0]


def _sidecar(reply_path, objs, raw_extra=()):
    """Findings through the real `put-partial` CLI, then raw lines appended by hand."""
    for obj in objs:
        assert agent_caps.main(["put-partial", "--reply-path", str(reply_path),
                                "--finding", json.dumps(obj)]) == 0
    with agent_caps.partial_path(reply_path).open("a", encoding="utf-8") as fh:
        for line in raw_extra:
            fh.write(line + "\n")


def _finding(file, line, summary):
    return {"file": file, "line": line, "summary": summary}


def _reply(round_dir, entry, text):
    Path(entry["reply_path"]).write_text(text, encoding="utf-8")


def test_outcomes_are_exported():
    assert finder_retry.OUTCOMES == ("delivered", "partial", "capped", "retried",
                                     "unparseable", "skipped")


def test_partial_findings_land_in_the_reply_marked_capped(tmp_path):
    _manifest(tmp_path)
    entry = _entry(tmp_path)
    _sidecar(entry["reply_path"],
             [_finding("a.py", 10, "lease released twice"),
              _finding("b.py", 40, "cache key ignores the slot")], raw_extra=["{bad"])
    out = finder_retry.settle(tmp_path, entry["name"], capped=True)
    assert out["outcome"] == "partial" and out["next"] == "none"
    assert not Path(entry["reply_path"]).read_text(encoding="utf-8").count('{"text"')
    findings, ok = review_merge.parse_codereview_result(
        Path(entry["reply_path"]).read_text(encoding="utf-8"))
    assert ok and len(findings) == 2
    assert all(f[agent_caps.CAP_FIELD] is True for f in findings)
    assert {f["summary"] for f in findings} == {"lease released twice",
                                                "cache key ignores the slot"}
    after = _entry(tmp_path)
    assert "unparseable" not in after
    merged = fs.merge_segment_replies({"angles": [after]},
                                      {after["name"]: findings})
    assert len(merged["correctness"]) == 2
    tel = after["telemetry"]
    assert tel["outcome"] == "partial" and tel["partial_malformed"] == 1
    assert tel["sources"] == ["sidecar"] and tel["transcript_found"] is False


def test_progress_only_reply_becomes_a_clean_empty_reply(tmp_path):
    _manifest(tmp_path)
    entry = _entry(tmp_path)
    _sidecar(entry["reply_path"], [{"progress": "b.py"}])
    out = finder_retry.settle(tmp_path, entry["name"], capped=True)
    assert out["outcome"] == "partial"
    assert out["covered_files"] == ["b.py"]
    assert json.loads(Path(entry["reply_path"]).read_text(encoding="utf-8")) == {"findings": []}
    assert _entry(tmp_path)["telemetry"]["covered_files"] == ["b.py"]


def test_placeholder_reply_never_reads_delivered(tmp_path):
    _manifest(tmp_path)
    entry = _entry(tmp_path)
    assert agent_caps.main(["put-capped", "--reply-path", entry["reply_path"]]) == 0
    out = finder_retry.settle(tmp_path, entry["name"], capped=False, final=True)
    assert out["outcome"] == "capped" and out["next"] == "uncovered"
    after = _entry(tmp_path)
    assert after["unparseable"] == "re-covered-by-opus-check"
    assert after["telemetry"]["outcome"] == "capped"
    assert [e["name"] for e in finder_round.parse_required({"angles": [after]})] == []


def test_clean_reply_is_delivered_and_covers_its_files(tmp_path):
    _manifest(tmp_path)
    entry = _entry(tmp_path)
    _reply(tmp_path, entry, json.dumps({"findings": []}) + "\n")
    out = finder_retry.settle(tmp_path, entry["name"], capped=False)
    assert out["outcome"] == "delivered" and out["next"] == "none"
    assert out["covered_files"] == SEG_FILES
    after = _entry(tmp_path)
    assert after["telemetry"]["outcome"] == "delivered"
    assert after["telemetry"]["covered_files"] == SEG_FILES
    assert Path(entry["reply_path"]).read_text(encoding="utf-8") == json.dumps(
        {"findings": []}) + "\n"


def test_uncapped_unparseable_reply_stays_unparseable(tmp_path):
    _manifest(tmp_path)
    entry = _entry(tmp_path)
    _reply(tmp_path, entry, "I checked the files and found nothing to report.\n")
    out = finder_retry.settle(tmp_path, entry["name"], capped=False)
    assert out["outcome"] == "unparseable" and out["next"] == "none"
    after = _entry(tmp_path)
    assert after["unparseable"] == "re-covered-by-opus-check"
    assert after["telemetry"]["outcome"] == "unparseable"


def test_caps_json_stopped_marks_the_call_capped(tmp_path):
    _manifest(tmp_path)
    entry = _entry(tmp_path)
    (tmp_path / entry["name"] / "caps.json").write_text(
        json.dumps({"warned": True, "stopped": True}) + "\n", encoding="utf-8")
    _sidecar(entry["reply_path"], [_finding("a.py", 3, "off by one")])
    out = finder_retry.settle(tmp_path, entry["name"])
    assert out["outcome"] == "partial"


def test_empty_reply_without_final_is_capped_and_unmarked(tmp_path):
    _manifest(tmp_path)
    entry = _entry(tmp_path)
    Path(entry["reply_path"]).write_text("", encoding="utf-8")
    out = finder_retry.settle(tmp_path, entry["name"], capped=True)
    assert out["outcome"] == "capped" and out["next"] == "retry"
    assert "unparseable" not in _entry(tmp_path)


def test_telemetry_written_in_one_manifest_write(tmp_path):
    _manifest(tmp_path, rung="sonnet-xhigh", attempt=2)
    entry = _entry(tmp_path)
    _sidecar(entry["reply_path"], [{"progress": "a.py"}])
    finder_retry.settle(tmp_path, entry["name"], capped=True, elapsed_s=1500.0)
    tel = _entry(tmp_path)["telemetry"]
    assert tel == {"rung": "sonnet-xhigh", "attempt": 2, "lines": 400, "files": 3,
                   "elapsed_s": 1500.0, "outcome": "partial", "covered_files": ["a.py"],
                   "partial_malformed": 0, "sources": ["sidecar"],
                   "transcript_found": False}


def test_existing_elapsed_and_covered_files_survive_a_bare_call(tmp_path):
    _manifest(tmp_path)
    entry = _entry(tmp_path)
    _reply(tmp_path, entry, json.dumps({"findings": []}) + "\n")
    finder_retry.settle(tmp_path, entry["name"], elapsed_s=120.0)
    Path(entry["reply_path"]).write_text("prose now, unparseable\n", encoding="utf-8")
    finder_retry.settle(tmp_path, entry["name"])
    tel = _entry(tmp_path)["telemetry"]
    assert tel["outcome"] == "unparseable"
    assert tel["elapsed_s"] == 120.0 and tel["covered_files"] == SEG_FILES


def test_settle_cli_prints_the_outcome(tmp_path, capsys):
    _manifest(tmp_path)
    entry = _entry(tmp_path)
    _reply(tmp_path, entry, json.dumps({"findings": []}) + "\n")
    assert finder_retry.main(["settle", "--round-dir", str(tmp_path),
                              "--angle", entry["name"], "--elapsed", "42", "--final"]) == 0
    out = json.loads(capsys.readouterr().out.strip())
    assert out == {"outcome": "delivered", "next": "none", "covered_files": SEG_FILES}


def test_settle_refuses_the_opus_check_and_an_unknown_angle(tmp_path, capsys):
    _manifest(tmp_path, name="opus-check")
    assert finder_retry.main(["settle", "--round-dir", str(tmp_path),
                              "--angle", "opus-check"]) == 2
    assert finder_retry.main(["settle", "--round-dir", str(tmp_path),
                              "--angle", "nope-s9"]) == 2
