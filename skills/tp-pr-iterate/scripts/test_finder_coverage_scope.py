"""Task 1.8: the Opus check prompt names every uncovered file (Behavior 4).

design: finder-cap-coverage

Whenever `uncovered_files` is non-empty, the `opus-check` entry's prompt in
`angles.json` gains one block between the `<!-- uncovered-files -->` markers naming
every uncovered path — at ANY coverage, because the check's scope only grows
(design §Constraints). Re-running the merge replaces the block, never duplicates it.
With no uncovered file the check prompt is byte-unchanged. A `partial` segment's
unfinished files and a `capped` segment's whole segment reach the check exactly as an
`unparseable` segment's files do today.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import finder_coverage as fc  # noqa: E402
import finder_round as fr  # noqa: E402
import finder_segments as fs  # noqa: E402

BLOCK = re.compile(r"<!-- uncovered-files -->.*?<!-- /uncovered-files -->", re.DOTALL)


def _entry(name, sid, files, outcome=None, covered=None):
    e = {"name": name, "role": "finder", "model": "local", "advisory": True,
         "prompt": f"review {sid}",
         "segment": {"angle": "edge", "id": sid, "files": files, "lines": 100,
                     "fraction": 0.5}}
    if outcome:
        e["telemetry"] = {"outcome": outcome, "covered_files": covered or [],
                          "sources": [], "transcript_found": False}
    return e


def _check_prompt(manifest):
    for e in manifest["angles"]:
        if e["name"] == fr.CHECK_NAME:
            return e["prompt"]
    raise AssertionError("no opus-check entry in the manifest")


def _mixed_round(tmp_path, covered):
    """10 files in 4 segments; s4 is `partial` (a finding names f9.py).

    `covered` is the partial's progress lines: ["f8.py"] leaves f9/f10 uncovered (80%),
    [] leaves f8/f9/f10 uncovered (70%)."""
    groups = [["f1.py", "f2.py", "f3.py"], ["f4.py", "f5.py", "f6.py"], ["f7.py"],
              ["f8.py", "f9.py", "f10.py"]]
    entries = [_entry(f"edge-s{k}", f"s{k}", groups[k - 1], outcome="delivered")
               for k in (1, 2, 3)]
    entries.append(_entry("edge-s4", "s4", groups[3], outcome="partial", covered=covered))
    entries.append(fr.check_angle("/x/rulings.md"))
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "angles.json").write_text(json.dumps({"angles": entries}), encoding="utf-8")
    for e in entries[:3]:
        (tmp_path / e["name"]).mkdir(exist_ok=True)
        (tmp_path / e["name"] / "reply.md").write_text(json.dumps({"findings": []}),
                                                       encoding="utf-8")
    (tmp_path / "edge-s4").mkdir(exist_ok=True)
    (tmp_path / "edge-s4" / "reply.md").write_text(
        json.dumps({"findings": [{"file": "f9.py", "line_range": [3, 4],
                                  "summary": "partial take"}]}), encoding="utf-8")
    return tmp_path


def _manifest(tmp_path):
    return json.loads((tmp_path / "angles.json").read_text(encoding="utf-8"))


def _blocks(prompt):
    return BLOCK.findall(prompt)


# --- Red: the block names exactly the uncovered paths, at 80% and at 70% ---

def test_80_percent_block_names_exactly_the_two_uncovered_paths(tmp_path):
    rd = _mixed_round(tmp_path / "p80", ["f8.py"])
    assert fc.merge_round(rd) == 0
    assert _merged_coverage(rd)["percent"] == 80
    blocks = _blocks(_check_prompt(_manifest(rd)))
    assert len(blocks) == 1
    for p in ("f9.py", "f10.py"):
        assert p in blocks[0]
    for p in ("f1.py", "f2.py", "f3.py", "f4.py", "f5.py", "f6.py", "f7.py", "f8.py"):
        assert p not in blocks[0]


def test_70_percent_block_names_its_three_uncovered_paths(tmp_path):
    rd = _mixed_round(tmp_path / "p70", [])
    assert fc.merge_round(rd) == 0
    assert _merged_coverage(rd)["percent"] == 70
    blocks = _blocks(_check_prompt(_manifest(rd)))
    assert len(blocks) == 1
    for p in ("f8.py", "f9.py", "f10.py"):
        assert p in blocks[0]
    assert "f7.py" not in blocks[0]


def test_block_written_at_90_percent_coverage_too(tmp_path):
    """The block is not an under-80% affordance: any non-empty uncovered list writes it."""
    rd = _mixed_round(tmp_path / "p90", ["f8.py", "f9.py"])
    assert fc.merge_round(rd) == 0
    assert _merged_coverage(rd)["percent"] == 90
    blocks = _blocks(_check_prompt(_manifest(rd)))
    assert len(blocks) == 1 and "f10.py" in blocks[0]


# --- Red: re-running the merge replaces the block, never duplicates it ---

def test_second_merge_replaces_the_block(tmp_path):
    rd = _mixed_round(tmp_path / "twice", [])
    assert fc.merge_round(rd) == 0
    first = _check_prompt(_manifest(rd))
    assert fc.merge_round(rd) == 0
    second = _check_prompt(_manifest(rd))
    assert len(_blocks(second)) == 1
    assert second == first
    assert second.count("<!-- uncovered-files -->") == 1


# --- Red: nothing uncovered → check prompt byte-equal, no block ---

def test_all_delivered_leaves_the_check_prompt_byte_equal(tmp_path):
    groups = [["a1.py"], ["a2.py"], ["a3.py"], ["a4.py"]]
    entries = [_entry(f"edge-s{k}", f"s{k}", groups[k - 1], outcome="delivered")
               for k in range(1, 5)]
    entries.append(fr.check_angle("/x/rulings.md"))
    rd = tmp_path
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "angles.json").write_text(json.dumps({"angles": entries}), encoding="utf-8")
    for e in entries[:4]:
        (rd / e["name"]).mkdir(exist_ok=True)
        (rd / e["name"] / "reply.md").write_text(json.dumps({"findings": []}),
                                                 encoding="utf-8")
    before = _check_prompt(_manifest(rd))
    assert fc.merge_round(rd) == 0
    after = _check_prompt(_manifest(rd))
    assert after == before
    assert _blocks(after) == []


def test_check_scope_removes_an_old_block_when_nothing_is_uncovered(tmp_path):
    manifest = {"angles": [{"name": fr.CHECK_NAME,
                            "prompt": "head\n\n<!-- uncovered-files -->\n- a.py\n"
                                      "<!-- /uncovered-files -->\ntail"}]}
    out = fc.check_scope(manifest, [])
    assert _blocks(_check_prompt(out)) == []


def test_check_scope_is_pure(tmp_path):
    manifest = {"angles": [{"name": fr.CHECK_NAME, "prompt": "head"}]}
    out = fc.check_scope(manifest, ["a.py"])
    assert out is not manifest
    assert _check_prompt(manifest) == "head"
    assert len(_blocks(_check_prompt(out))) == 1


def _merged_coverage(rd):
    return json.loads((rd / "opus-check" / fs.MERGED).read_text(encoding="utf-8"))["coverage"]
