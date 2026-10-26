"""A half settled `unparseable`, re-settled `capped` into the Sonnet rung, keeps no stale mark."""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import finder_coverage as fc  # noqa: E402
import finder_retry as fr  # noqa: E402


def test_sonnet_rung_after_unparseable_settle_keeps_its_findings(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "nocfg"))
    (tmp_path / "edge-s1a").mkdir()
    e = {"name": "edge-s1a", "advisory": True, "model": "local", "role": "finder", "attempt": 2,
         "reply_path": str(tmp_path / "edge-s1a" / "reply.md"),
         "segment": {"angle": "edge", "id": "s1a", "files": ["a.py"], "lines": 100,
                     "fraction": 0.5, "max_segments": 4}}
    (tmp_path / "angles.json").write_text(json.dumps({"angles": [e]}), encoding="utf-8")
    reply = tmp_path / "edge-s1a" / "reply.md"
    # the half's first spawn answers prose: settled `unparseable` and marked
    reply.write_text("I checked and found nothing.\n", encoding="utf-8")
    assert fr.settle(tmp_path, "edge-s1a")["outcome"] == "unparseable"
    # its respawn is stopped by the caps watch with nothing on disk -> Sonnet rung
    reply.write_text("", encoding="utf-8")
    assert fr.settle(tmp_path, "edge-s1a", capped=True)["next"] == "sonnet"
    row = json.loads((tmp_path / "angles.json").read_text(encoding="utf-8"))["angles"][0]
    assert "unparseable" not in row
    # the Sonnet re-run delivers; the merge's cap step settles what the driver left
    reply.write_text(json.dumps({"findings": [{"file": "a.py", "line_range": [3, 4],
                                               "summary": "real bug"}]}), encoding="utf-8")
    assert fc.merge_round(tmp_path) == 0
    merged = json.loads((tmp_path / "opus-check" / "segments-merged.json")
                        .read_text(encoding="utf-8"))
    assert [f["file"] for f in merged["merged"].get("edge", [])] == ["a.py"]
