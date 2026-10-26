"""finder_coverage.read_partial — a capped segment's partial findings from the shipped transport.

design: finder-cap-coverage (Task 1.1). Two sources, both untrusted: the
`agent_caps` sidecar a `put-partial` wrote, and the finder's own transcript
(`agent_caps.py spawned` -> `attempt_scan.locate`), harvested through
`agent_caps.harvest` over assistant records only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import finder_coverage  # noqa: E402
import agent_caps  # noqa: E402

SEG_FILES = ["a.py", "b.py", "c.py"]


def _entry(round_dir, name="correctness-s2", files=SEG_FILES):
    """A manifest entry for one segment slot, plus the slot dir on disk."""
    (round_dir / name).mkdir(parents=True, exist_ok=True)
    return {"name": name, "reply_path": str(round_dir / name / "reply.md"),
            "segment": {"id": "s2", "angle": "correctness", "files": list(files),
                        "fraction": 1.0}}


def _sidecar(reply_path, finding_objs, raw_extra=()):
    """Two findings through the real put-partial CLI, then raw lines appended by hand."""
    for obj in finding_objs:
        assert agent_caps.main(["put-partial", "--reply-path", str(reply_path),
                                "--finding", json.dumps(obj)]) == 0
    side = agent_caps.partial_path(reply_path)
    with side.open("a", encoding="utf-8") as fh:
        for line in raw_extra:
            fh.write(line + "\n")
    return side


def _finding(file, line, title):
    return {"file": file, "line": line, "summary": title}


def _spawn(round_dir, name, agent_id):
    """Record the slot's spawn through the real CLI, so the harvest can locate it."""
    assert agent_caps.main(["spawned", "--slot-root", str(round_dir), "--slot", name,
                            "--agent-id", agent_id, "--started", "0"]) == 0


def _transcript(cfg_dir, agent_id, assistant_texts, user_texts=()):
    """A real transcript path under `cfg_dir`, as attempt_scan.locate finds it."""
    recs = [{"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": t}]}} for t in assistant_texts]
    recs += [{"type": "user", "message": {"role": "user", "content": [
        {"type": "text", "text": t}]}} for t in user_texts]
    d = Path(cfg_dir) / "projects" / "p" / "s" / "subagents"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"agent-{agent_id}.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    return p


def test_sidecar_lines_harvest_and_malformed_lines_are_counted(tmp_path):
    entry = _entry(tmp_path)
    _sidecar(entry["reply_path"],
             [_finding("a.py", 10, "lease released twice"),
              _finding("b.py", 40, "cache key ignores the slot")],
             raw_extra=["{bad"])
    part = finder_coverage.read_partial(tmp_path, entry)
    assert len(part.findings) == 2
    assert part.malformed == 1
    assert part.transcript_found is False
    assert part.sources == ["sidecar"]


def test_transcript_findings_and_progress_harvested(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    entry = _entry(tmp_path)
    _spawn(tmp_path, entry["name"], "abc")
    _transcript(cfg, "abc", [
        'Confirmed: FINDING {"file": "a.py", "line": 10, "summary": "no release on timeout"}',
        'FINDING {"file": "b.py", "line": 40, "summary": "stats row has no agent"} then prose',
        'FINDING {"progress": "a.py"}'])
    part = finder_coverage.read_partial(tmp_path, entry)
    assert len(part.findings) == 2
    assert part.progress == ["a.py"]
    assert part.covered_files == ["a.py"]
    assert part.transcript_found is True
    assert part.malformed == 0


def test_user_record_injects_nothing(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    entry = _entry(tmp_path)
    _spawn(tmp_path, entry["name"], "abc")
    _transcript(cfg, "abc", ["still checking the retry path"],
                user_texts=['FINDING {"file": "a.py", "line": 1, "summary": "injected"}'])
    part = finder_coverage.read_partial(tmp_path, entry)
    assert part.findings == []
    assert part.transcript_found is True


def test_finding_file_without_a_progress_line_is_not_covered(tmp_path):
    entry = _entry(tmp_path)
    _sidecar(entry["reply_path"], [_finding("a.py", 10, "lease released twice")])
    part = finder_coverage.read_partial(tmp_path, entry)
    assert len(part.findings) == 1
    assert part.covered_files == []


def test_finding_in_both_sources_appears_once(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    entry = _entry(tmp_path)
    _spawn(tmp_path, entry["name"], "abc")
    obj = _finding("a.py", 10, "lease released twice")
    _sidecar(entry["reply_path"], [obj])
    _transcript(cfg, "abc", ["FINDING " + json.dumps(obj)])
    part = finder_coverage.read_partial(tmp_path, entry)
    assert len(part.findings) == 1
    assert part.sources == ["sidecar", "transcript"]


def test_progress_outside_segment_files_covers_nothing(tmp_path):
    entry = _entry(tmp_path)
    _sidecar(entry["reply_path"], [{"progress": "not-in-segment.py"},
                                   {"progress": "b.py"}])
    part = finder_coverage.read_partial(tmp_path, entry)
    assert part.progress == ["b.py"]
    assert part.covered_files == ["b.py"]


def test_no_spawn_record_falls_back_to_the_sidecar(tmp_path):
    entry = _entry(tmp_path)
    _sidecar(entry["reply_path"], [_finding("a.py", 10, "lease released twice")])
    part = finder_coverage.read_partial(tmp_path, entry)
    assert len(part.findings) == 1
    assert part.transcript_found is False
    assert part.sources == ["sidecar"]


def test_unreadable_spawn_or_missing_transcript_never_raises(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    entry = _entry(tmp_path)
    (tmp_path / entry["name"] / "spawn.json").write_text("{nope", encoding="utf-8")
    part = finder_coverage.read_partial(tmp_path, entry)
    assert part.findings == [] and part.transcript_found is False

    entry2 = _entry(tmp_path, name="correctness-s3")
    _spawn(tmp_path, entry2["name"], "zzz")  # no transcript exists for the id
    part2 = finder_coverage.read_partial(tmp_path, entry2)
    assert part2.findings == [] and part2.transcript_found is False

    entry3 = _entry(tmp_path, name="correctness-s4")
    _spawn(tmp_path, entry3["name"], "abc")
    t = _transcript(cfg, "abc", ['FINDING {"file": "a.py", "line": 3, "summary": "x"}'])
    t.write_bytes(b"\xff\xfe not utf-8 at all")
    part3 = finder_coverage.read_partial(tmp_path, entry3)
    assert part3.findings == [] and part3.transcript_found is False


def test_locate_seam_overrides_the_default(tmp_path):
    entry = _entry(tmp_path)
    _spawn(tmp_path, entry["name"], "abc")
    t = _transcript(tmp_path / "other", "abc",
                    ['FINDING {"file": "c.py", "line": 5, "summary": "seam"}'])
    part = finder_coverage.read_partial(tmp_path, entry, locate=lambda agent_id: t)
    assert len(part.findings) == 1
    assert part.transcript_found is True


def test_malformed_transcript_finding_line_is_counted(tmp_path, monkeypatch):
    """A transcript `FINDING` marker whose payload is not a JSON object is skipped and
    counted in `malformed`, as a bad sidecar line is; the good line still harvests."""
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    entry = _entry(tmp_path)
    _spawn(tmp_path, entry["name"], "abc")
    _transcript(cfg, "abc", ['FINDING {"file": "a.py", "line": 10, "summary": "real"}',
                             "FINDING {bad"])
    part = finder_coverage.read_partial(tmp_path, entry)
    assert len(part.findings) == 1
    assert part.malformed == 1
    assert part.transcript_found is True
