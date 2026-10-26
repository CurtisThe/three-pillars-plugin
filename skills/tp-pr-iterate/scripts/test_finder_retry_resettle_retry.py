"""A first attempt settled `unparseable`, re-settled `capped` with next `retry`: retry accepts it.

The parse-lift mark exists only while the entry's final state is `unparseable` or
`uncovered`; every other outcome/next-step pair clears it (one write point in
`finder_retry.settle`), so no third re-settle path can leave a stale mark behind.
"""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import finder_retry as fr  # noqa: E402

DIFF = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,2 @@\n x\n+y\n"
        "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1,1 +1,2 @@\n x\n+y\n")


def _round(tmp_path, max_segments=4):
    """One first-attempt Strata segment entry with the keys `round_scratch.prepare` writes."""
    (tmp_path / "edge-s1").mkdir()
    e = {"name": "edge-s1", "advisory": True, "model": "local", "role": "finder", "attempt": 1,
         "prompt": "review", "reply_path": str(tmp_path / "edge-s1" / "reply.md"),
         "exec_dir": str(tmp_path / "exec-edge-s1"), "tree_dir": None,
         "segment": {"angle": "edge", "id": "s1", "files": ["a.py", "b.py"], "lines": 4,
                     "fraction": 1.0, "max_segments": max_segments, "of": 1}}
    (tmp_path / "angles.json").write_text(
        json.dumps({"base": "base1", "head": "head1", "angles": [e]}), encoding="utf-8")
    return tmp_path / "edge-s1" / "reply.md"


def _entry(tmp_path):
    return json.loads((tmp_path / "angles.json").read_text(encoding="utf-8"))["angles"][0]


def test_retry_after_unparseable_then_capped_settle(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "nocfg"))
    reply = _round(tmp_path)
    # the first spawn answers prose: settled `unparseable` and marked
    reply.write_text("I checked and found nothing.\n", encoding="utf-8")
    assert fr.settle(tmp_path, "edge-s1")["outcome"] == "unparseable"
    assert _entry(tmp_path)["unparseable"] == fr.UNCOVERED_MARK
    # its respawn is stopped by the caps watch with nothing on disk -> next `retry`
    reply.write_text("", encoding="utf-8")
    out = fr.settle(tmp_path, "edge-s1", capped=True)
    assert out["outcome"] == "capped" and out["next"] == "retry"
    assert "unparseable" not in _entry(tmp_path)
    # the driver acts on `next`: retry must accept the unmarked first attempt
    r = fr.retry(tmp_path, "edge-s1", diff_text=DIFF)
    assert not r.get("exit"), r
    assert r["next"] == "retry" and r["halves"] == ["edge-s1a", "edge-s1b"]


def test_uncovered_after_unparseable_settle_keeps_the_mark(tmp_path, monkeypatch):
    """The one state that keeps the mark on a re-settle: capped with no transition left."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "nocfg"))
    reply = _round(tmp_path, max_segments=1)  # budget allows no retry at all
    reply.write_text("I checked and found nothing.\n", encoding="utf-8")
    assert fr.settle(tmp_path, "edge-s1")["outcome"] == "unparseable"
    reply.write_text("", encoding="utf-8")
    out = fr.settle(tmp_path, "edge-s1", capped=True)
    assert out["outcome"] == "capped" and out["next"] == "uncovered"
    after = _entry(tmp_path)
    assert after["unparseable"] == fr.UNCOVERED_MARK
    assert after["telemetry"]["outcome"] == "capped"
