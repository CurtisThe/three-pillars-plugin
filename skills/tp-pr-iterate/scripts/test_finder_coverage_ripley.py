"""Task 1.7: the merge runs the cap step itself — Ripley's regression (Behavior 8).

design: finder-cap-coverage

Ripley's round had segment slots with a zero-byte `reply.md`, no sidecar, no
`spawn.json` and no `put-capped` or `settle` run: the driver skipped the documented
cap step. `finder_segments.py merge` now settles every such entry itself with
`finder_retry.settle(R, name, capped=True, final=True)` before computing anything,
whatever the driver did or skipped. Each one ends `partial` or `capped`, never
outcome `unparseable`, and no `rung`/`attempt` transition is written (the serial
loop is over). Anything already final — delivered, a clean `{"findings": []}`, or
already settled — is left untouched.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import agent_caps  # noqa: E402
import finder_coverage as fc  # noqa: E402
import finder_round as fr_round  # noqa: E402
import finder_retry as fr  # noqa: E402
import finder_segments as fs  # noqa: E402

GROUPS = {"s1": ["f1.py", "f2.py", "f3.py"], "s2": ["f4.py", "f5.py", "f6.py"],
          "s3": ["f7.py"], "s4": ["f8.py", "f9.py", "f10.py"]}


def _entry(rd, sid, *, attempt=1, **kw):
    """One segment manifest entry over `GROUPS[sid]`, plus its slot dir on disk."""
    name = f"correctness-{sid}"
    (rd / name).mkdir(parents=True, exist_ok=True)
    return {"name": name, "role": "finder", "model": "local", "advisory": True,
            "prompt": "p", "attempt": attempt,
            "reply_path": str(rd / name / "reply.md"),
            "segment": {"angle": "correctness", "id": sid, "files": list(GROUPS[sid]),
                        "lines": 100, "fraction": 0.5, "max_segments": 4}, **kw}


def _write_manifest(rd, entries):
    (rd / "angles.json").write_text(json.dumps({"angles": entries}, indent=2) + "\n",
                                    encoding="utf-8")


def _manifest(rd):
    return json.loads((rd / "angles.json").read_text(encoding="utf-8"))


def _entry_map(rd):
    return {e["name"]: e for e in _manifest(rd)["angles"]}


def _put_capped(rd, sid, text=""):
    """The real cap writer, exactly as the driver would run it."""
    path = rd / f"correctness-{sid}" / "reply.md"
    argv = ["put-capped", "--reply-path", str(path)]
    if text:
        argv += ["--partial", text]
    assert agent_caps.main(argv) == 0


def _sidecar(rd, sid, objs):
    path = rd / f"correctness-{sid}" / "reply.md"
    for obj in objs:
        assert agent_caps.main(["put-partial", "--reply-path", str(path),
                                "--finding", json.dumps(obj)]) == 0


def _spawn(rd, sid, agent_id):
    assert agent_caps.main(["spawned", "--slot-root", str(rd), "--slot",
                            f"correctness-{sid}", "--agent-id", agent_id,
                            "--started", "0"]) == 0


def _transcript(cfg_dir, agent_id, texts):
    recs = [{"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": t}]}} for t in texts]
    d = Path(cfg_dir) / "projects" / "p" / "s" / "subagents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"agent-{agent_id}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")


def _reply(rd, sid, text):
    (rd / f"correctness-{sid}" / "reply.md").write_text(text, encoding="utf-8")


def _empty_reply(rd, sid):
    """Ripley's slot: a zero-byte reply, no sidecar, no `spawn.json`."""
    (rd / f"correctness-{sid}" / "reply.md").write_text("", encoding="utf-8")


def _ripley_round(rd):
    """s1 delivered, s2 Ripley's empty slot, s3 the same but marked by the real
    `mark-unparseable` CLI (what Ripley's driver did), s4 two sidecar lines, no reply."""
    entries = [_entry(rd, sid) for sid in ("s1", "s2", "s3", "s4")]
    _reply(rd, "s1", json.dumps({"findings": []}))
    _empty_reply(rd, "s2")
    _empty_reply(rd, "s3")
    _sidecar(rd, "s4", [{"file": "f8.py", "line": 12, "summary": "claim list never cleared"},
                        {"file": "f9.py", "line": 44, "summary": "token read off the wrong row"}])
    _write_manifest(rd, entries)
    assert fr_round.main(["mark-unparseable", "--round-dir", str(rd),
                          "--angle", "correctness-s3"]) == 0
    return entries


def _merged(rd):
    return json.loads((rd / "opus-check" / fs.MERGED).read_text(encoding="utf-8"))


def _settle_cli(rd, sid, *extra):
    """The driver's own settle call, through the real CLI."""
    r = subprocess.run([sys.executable, str(_HERE / "finder_retry.py"), "settle",
                        "--round-dir", str(rd), "--angle", f"correctness-{sid}", *extra],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# Ripley's case end to end through the real merge command line.
def test_ripley_merge_marks_empty_slots_capped_never_unparseable(tmp_path):
    rd = tmp_path
    _ripley_round(rd)
    before = _entry_map(rd)
    assert "unparseable" not in before["correctness-s2"]  # no mark-unparseable for s2
    assert fs.main(["merge", "--round-dir", str(rd)]) == 0

    rows = {r["id"]: r for r in _merged(rd)["segments"]}
    assert rows["s2"]["outcome"] == "capped" and rows["s3"]["outcome"] == "capped"
    assert rows["s1"]["outcome"] == "delivered" and rows["s4"]["outcome"] == "partial"

    entries = _entry_map(rd)
    for sid in ("s2", "s3"):
        e = entries[f"correctness-{sid}"]
        assert e["unparseable"] == fr.UNCOVERED_MARK  # the parse-lift mark
        assert e["telemetry"]["outcome"] == "capped"
        assert "rung" not in e and e["attempt"] == 1  # no transition, the loop is over
    names = {e["name"] for e in fr_round.parse_required(_manifest(rd))}
    assert "correctness-s2" not in names and "correctness-s3" not in names

    unc = _merged(rd)["uncovered_files"]
    assert unc == sorted(GROUPS["s2"] + GROUPS["s3"] + GROUPS["s4"])
    cov = _merged(rd)["coverage"]
    assert cov["files_changed"] == 10 and cov["files_covered"] == 3
    assert fc.coverage_line(rd) == f"coverage 30%: {len(unc)} files reviewed only by the Opus check"


def test_ripley_merge_harvests_sidecar_lines_into_a_partial(tmp_path):
    rd = tmp_path
    _ripley_round(rd)
    assert fs.main(["merge", "--round-dir", str(rd)]) == 0
    e = _entry_map(rd)["correctness-s4"]
    assert e["telemetry"]["outcome"] == "partial"
    assert "unparseable" not in e  # a partial is never lifted
    files = {f["file"] for f in _merged(rd)["merged"]["correctness"]}
    assert {"f8.py", "f9.py"} <= files


def test_ripley_merge_partial_variant_transcript_finding_lines(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    rd = tmp_path / "round"
    entries = [_entry(rd, sid) for sid in ("s1", "s2")]
    _reply(rd, "s1", json.dumps({"findings": []}))
    _empty_reply(rd, "s2")
    _spawn(rd, "s2", "abc123")
    _transcript(cfg, "abc123", [
        "FINDING " + json.dumps({"file": "f4.py", "line": 8, "summary": "claim leaked"}),
        "FINDING " + json.dumps({"file": "f5.py", "line": 30, "summary": "no ownership check"})])
    _write_manifest(rd, entries)
    assert fs.main(["merge", "--round-dir", str(rd)]) == 0
    e = _entry_map(rd)["correctness-s2"]
    assert e["telemetry"]["outcome"] == "partial" and e["telemetry"]["transcript_found"]
    assert "unparseable" not in e


def test_ripley_merge_placeholder_reply_from_put_capped_is_capped(tmp_path):
    rd = tmp_path
    entries = [_entry(rd, sid) for sid in ("s1", "s2")]
    _reply(rd, "s1", json.dumps({"findings": []}))
    _put_capped(rd, "s2")  # the real CLI: {"findings": [{"capped": true, "text": ""}]}
    _write_manifest(rd, entries)
    assert fs.main(["merge", "--round-dir", str(rd)]) == 0
    e = _entry_map(rd)["correctness-s2"]
    assert e["telemetry"]["outcome"] == "capped"
    assert e["unparseable"] == fr.UNCOVERED_MARK
    assert _merged(rd)["segments"][1]["outcome"] != "delivered"


def test_ripley_merge_leaves_a_clean_empty_reply_untouched(tmp_path):
    rd = tmp_path
    entries = [_entry(rd, sid) for sid in ("s1", "s2")]
    _reply(rd, "s1", json.dumps({"findings": []}))
    _empty_reply(rd, "s2")
    _write_manifest(rd, entries)
    assert fs.main(["merge", "--round-dir", str(rd)]) == 0
    s1 = _entry_map(rd)["correctness-s1"]
    assert "telemetry" not in s1 and "unparseable" not in s1
    row = {r["id"]: r for r in _merged(rd)["segments"]}["s1"]
    assert row["outcome"] == "delivered"
    assert _merged(rd)["uncovered_files"] == sorted(GROUPS["s2"])


def test_ripley_merge_keeps_what_the_driver_already_settled(tmp_path):
    rd = tmp_path
    _ripley_round(rd)
    _settle_cli(rd, "s2", "--capped", "--elapsed", "1500")
    _settle_cli(rd, "s4", "--elapsed", "120")
    settled = {k: dict(v) for k, v in _entry_map(rd).items()}
    settled = {k: json.loads(json.dumps(v)) for k, v in settled.items()}
    assert settled["correctness-s2"]["telemetry"]["elapsed_s"] == 1500.0
    assert settled["correctness-s4"]["telemetry"]["elapsed_s"] == 120.0

    assert fs.main(["merge", "--round-dir", str(rd)]) == 0
    after = _entry_map(rd)
    for name in ("correctness-s2", "correctness-s4"):
        assert after[name]["telemetry"]["outcome"] == settled[name]["telemetry"]["outcome"]
        assert after[name]["telemetry"]["elapsed_s"] == settled[name]["telemetry"]["elapsed_s"]
        assert after[name]["telemetry"]["covered_files"] == \
            settled[name]["telemetry"]["covered_files"]
        assert after[name].get("rung") == settled[name].get("rung")
        assert after[name]["attempt"] == settled[name]["attempt"]


def test_ripley_merge_is_idempotent(tmp_path):
    rd = tmp_path
    _ripley_round(rd)
    assert fs.main(["merge", "--round-dir", str(rd)]) == 0
    first_merged = (rd / "opus-check" / fs.MERGED).read_text(encoding="utf-8")
    first_manifest = (rd / "angles.json").read_text(encoding="utf-8")
    assert fs.main(["merge", "--round-dir", str(rd)]) == 0
    assert (rd / "opus-check" / fs.MERGED).read_text(encoding="utf-8") == first_merged
    assert (rd / "angles.json").read_text(encoding="utf-8") == first_manifest


# N1: a Sonnet re-run that delivered a parseable reply but whose settle the driver
# skipped must not stay outcome `capped` — the merge's settle lets the parse rule lift it.
def test_ripley_merge_lifts_an_unsettled_capped_entry_that_delivered(tmp_path):
    rd = tmp_path
    entries = [_entry(rd, "s1", rung="sonnet-xhigh", attempt=3)]
    entries[0]["telemetry"] = {"outcome": "capped", "covered_files": [], "sources": [],
                               "transcript_found": False}
    _reply(rd, "s1", json.dumps({"findings": [{"file": "f1.py", "line": 3,
                                               "summary": "claim list alias"}]}))
    _write_manifest(rd, entries)
    assert fs.main(["merge", "--round-dir", str(rd)]) == 0
    e = _entry_map(rd)["correctness-s1"]
    assert e["telemetry"]["outcome"] == "delivered"
    assert "unparseable" not in e
    assert _merged(rd)["coverage"]["percent"] == 100
