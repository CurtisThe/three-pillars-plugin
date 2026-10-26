"""A segment re-settled `delivered` after an earlier `unparseable` settle keeps no stale mark."""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import finder_coverage as fc  # noqa: E402
import finder_retry as fr  # noqa: E402


def test_resettled_delivered_segment_keeps_its_findings(tmp_path):
    (tmp_path / "edge-s1").mkdir()
    e = {"name": "edge-s1", "advisory": True, "model": "local", "role": "finder",
         "reply_path": str(tmp_path / "edge-s1" / "reply.md"),
         "segment": {"angle": "edge", "id": "s1", "files": ["a.py"], "lines": 100,
                     "fraction": 0.5, "max_segments": 4}}
    (tmp_path / "angles.json").write_text(json.dumps({"angles": [e]}), encoding="utf-8")
    reply = tmp_path / "edge-s1" / "reply.md"
    # attempt 1: prose, not capped -> settled `unparseable` and marked
    reply.write_text("I checked and found nothing.\n", encoding="utf-8")
    assert fr.settle(tmp_path, "edge-s1")["outcome"] == "unparseable"
    # the respawn delivers a conforming reply; the driver settles it again
    reply.write_text(json.dumps({"findings": [{"file": "a.py", "line_range": [3, 4],
                                               "summary": "real bug"}]}), encoding="utf-8")
    assert fr.settle(tmp_path, "edge-s1")["outcome"] == "delivered"
    assert fc.merge_round(tmp_path) == 0
    row = json.loads((tmp_path / "angles.json").read_text(encoding="utf-8"))["angles"][0]
    assert "unparseable" not in row
    merged = json.loads((tmp_path / "opus-check" / "segments-merged.json")
                        .read_text(encoding="utf-8"))
    assert [f["file"] for f in merged["merged"].get("edge", [])] == ["a.py"]
