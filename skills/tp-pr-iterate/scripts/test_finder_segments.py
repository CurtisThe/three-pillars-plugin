"""Part 1: large diffs are cut into segments for Strata finders."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import finder_round  # noqa: E402
import finder_segments as fs  # noqa: E402

CFG = {"max_lines": 600, "max_files": 10, "max_segments": 4}


def _file(path, n, hunks=1, body=""):
    out = [f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}"]
    per = n // hunks
    for h in range(hunks):
        out.append(f"@@ -{h * 100 + 1},0 +{h * 100 + 1},{per} @@")
        out += [f"+line {i}" for i in range(per)]
    if body:
        out.append(f"+{body}")
    return "\n".join(out)


def _diff(*files):
    return "\n".join(files) + "\n"


def _ids(plan):
    return [(s["id"], sorted(s["files"])) for s in plan["segments"]]


def test_under_threshold_not_engaged():
    plan = fs.plan_segments(_diff(_file("a.py", 100), _file("test_a.py", 100)), CFG)
    assert plan["engaged"] is False and plan["segments"] == []


def test_over_file_count_engages():
    files = [_file(f"f{i}.md", 2) for i in range(11)]
    plan = fs.plan_segments(_diff(*files), CFG)
    assert plan["engaged"] and all(len(s["files"]) <= 10 for s in plan["segments"])


def test_source_stays_with_its_tests_and_citing_docs():
    d = _diff(_file("skills/x/alpha.py", 200), _file("skills/x/test_alpha.py", 150),
              _file("skills/x/test_alpha_edge.py", 50),
              _file("docs/alpha.md", 10, body="see alpha.py"),
              _file("skills/x/beta.py", 500), _file("skills/x/test_beta.py", 100))
    plan = fs.plan_segments(d, CFG)
    seg = {p: s["id"] for s in plan["segments"] for p in s["files"]}
    assert seg["skills/x/alpha.py"] == seg["skills/x/test_alpha.py"] == seg["docs/alpha.md"]
    assert seg["skills/x/test_alpha_edge.py"] == seg["skills/x/alpha.py"]
    assert seg["skills/x/beta.py"] == seg["skills/x/test_beta.py"]
    assert seg["skills/x/beta.py"] != seg["skills/x/alpha.py"]


def test_import_edge_groups_a_test_with_its_module():
    test = _file("tests/check_it.py", 100, body="import widget")
    plan = fs.plan_segments(_diff(_file("pkg/widget.py", 300), test, _file("other.py", 400)), CFG)
    seg = {p: s["id"] for s in plan["segments"] for p in s["files"]}
    assert seg["pkg/widget.py"] == seg["tests/check_it.py"]


def test_no_segment_over_threshold_except_a_single_hunk():
    d = _diff(_file("big.py", 1500, hunks=5), _file("one.py", 900, hunks=1), _file("s.py", 50))
    plan = fs.plan_segments(d, CFG)
    for s in plan["segments"]:
        assert s["lines"] <= 600 or (s["ranges"] is not None or s["files"] == ["one.py"])
    big = [s for s in plan["segments"] if s["files"] == ["big.py"]]
    assert len(big) == 3 and all(s["ranges"] for s in big) and all(s["lines"] <= 600 for s in big)
    assert [s for s in plan["segments"] if s["files"] == ["one.py"]][0]["lines"] == 900


def test_cap_marks_the_rest_skipped_budget():
    d = _diff(*[_file(f"m{i}.py", 500) for i in range(7)])
    plan = fs.plan_segments(d, CFG)
    status = [s["status"] for s in plan["segments"]]
    assert status[:4] == ["run"] * 4 and all("segment-budget" in s for s in status[4:])
    assert len(status) == 7


def test_deadline_fraction_scales_with_size():
    plan = fs.plan_segments(_diff(_file("a.py", 590), _file("b.py", 300), _file("c.py", 590),
                                  _file("d.py", 20)), CFG)
    fr = {tuple(s["files"]): s["fraction"] for s in plan["segments"]}
    assert fr[("a.py",)] == 0.98 and fr[("b.py", "d.py")] == 0.53
    tiny = fs.plan_segments(_diff(_file("a.py", 590), _file("c.py", 590), _file("d.py", 20)), CFG)
    assert min(s["fraction"] for s in tiny["segments"]) == fs.MIN_FRACTION


def test_settings_defaults_override_and_off():
    assert fs.settings(None) == fs.DEFAULTS
    assert fs.settings({"review": {"strata_finder_segment": {"max_lines": 50, "bogus": 1}}})[
        "max_lines"] == 50
    assert fs.settings({"review": {"strata_finder_segment": False}}) is None


def _angles():
    base = {"role": "finder", "model": "local", "advisory": True}
    return [{**base, "name": "edge", "prompt": "p1"},
            {"name": "opus-check", "role": "confirmer", "model": "opus", "prompt": "c"},
            {"name": "sonnet-one", "role": "finder", "model": "sonnet", "advisory": True,
             "prompt": "s"}]


def test_expand_only_strata_finders_and_marks_budget_skips():
    d = _diff(*[_file(f"m{i}.py", 500) for i in range(6)])
    plan = fs.plan_segments(d, CFG)
    out = fs.expand_angles(_angles(), plan, base="B", head="H", whole="files: x")
    names = [a["name"] for a in out]
    assert names[:6] == [f"edge-s{k}" for k in range(1, 7)]
    assert "opus-check" in names and "sonnet-one" in names
    run, skipped = out[0], out[5]
    assert "SEGMENT s1 of 6" in run["prompt"] and "git diff B...H" in run["prompt"]
    assert "files: x" in run["prompt"] and run["segment"]["angle"] == "edge"
    assert skipped["skipped"] == fs.SKIP_BUDGET and skipped["prompt"] == "p1"


def test_expand_unchanged_when_not_engaged():
    plan = fs.plan_segments(_diff(_file("a.py", 10)), CFG)
    assert fs.expand_angles(_angles(), plan, base="B", head="H", whole="") == _angles()


def _manifest():
    def e(name, angle, sid, files, **kw):
        return {"name": name, "segment": {"angle": angle, "id": sid, "files": files}, **kw}
    return {"angles": [e("edge-s1", "edge", "s1", ["a.py"]),
                       e("edge-s2", "edge", "s2", ["b.py"], unparseable="re-covered-by-opus-check"),
                       e("edge-s3", "edge", "s3", ["c.py"], skipped="segment-budget"),
                       e("tq-s1", "tq", "s1", ["a.py"]),
                       e("tq-s2", "tq", "s2", ["b.py"])]}


def test_uncovered_files_names_skipped_and_absent_segments():
    got = fs.uncovered_files(_manifest())
    assert got == ["b.py", "c.py"]  # edge-s2 absent, edge-s3 skipped; tq's own segments served
    assert fs.uncovered_files({"angles": [{"name": "x"}]}) == []


def test_merge_dedupes_by_file_line_and_skips_absent():
    finding = {"file": "a.py", "line_range": [3, 4], "summary": "bug"}
    manifest = _manifest()
    merged = fs.merge_segment_replies(manifest, {
        "edge-s1": [finding, {"file": "a.py", "line_range": [9, 9], "summary": "other"}],
        "edge-s2": [finding],  # unparseable: ignored
        "tq-s1": [finding], "tq-s2": []})
    assert len(merged["edge"]) == 2
    assert [f["segments"] for f in merged["edge"]] == [["s1"], ["s1"]]
    merged = fs.merge_segment_replies(
        {"angles": [_manifest()["angles"][0], {**_manifest()["angles"][0], "name": "edge-sx",
                                               "segment": {"angle": "edge", "id": "sx",
                                                           "files": ["a.py"]}}]},
        {"edge-s1": [finding], "edge-sx": [finding]})
    assert len(merged["edge"]) == 1 and merged["edge"][0]["segments"] == ["s1", "sx"]


def test_check_prompt_names_segments_skipped_and_absent():
    prompt = finder_round.check_angle("/r.md")["prompt"]
    assert "-s<k>" in prompt and "segment-budget" in prompt and "unparseable" in prompt
    assert "segments-merged.json" in prompt


def test_cli_merge_writes_view(tmp_path):
    rd = tmp_path
    manifest = _manifest()
    (rd / "angles.json").write_text(json.dumps(manifest), encoding="utf-8")
    ok = json.dumps({"findings": [{"file": "a.py", "line_range": [1, 1], "summary": "x"}]})
    for e in manifest["angles"]:
        (rd / e["name"]).mkdir()
        (rd / e["name"] / "reply.md").write_text(ok, encoding="utf-8")
    assert fs.main(["merge", "--round-dir", str(rd)]) == 0
    out = json.loads((rd / "opus-check" / fs.MERGED).read_text(encoding="utf-8"))
    assert out["uncovered_files"] == ["b.py", "c.py"]
    assert len(out["merged"]["edge"]) == 1


def test_apply_to_round_expands_over_threshold_and_not_off_strata(monkeypatch):
    big = _diff(*[_file(f"m{i}.py", 500) for i in range(3)])
    monkeypatch.setattr(fs, "whole_diff", lambda *a: big)
    monkeypatch.setattr(fs, "_intent", lambda *a: "do the thing")
    out = fs.apply_to_round(_angles(), {}, repo=".", base="B", head="H")
    assert [a["name"] for a in out if a.get("segment")][:3] == ["edge-s1", "edge-s2", "edge-s3"]
    assert "intent: do the thing" in out[0]["prompt"]
    no_strata = [a for a in _angles() if a["model"] != "local"]
    assert fs.apply_to_round(no_strata, {}, repo=".", base="B", head="H") == no_strata
    off = {"review": {"strata_finder_segment": False}}
    assert fs.apply_to_round(_angles(), off, repo=".", base="B", head="H") == _angles()
    monkeypatch.setattr(fs, "whole_diff", lambda *a: _diff(_file("a.py", 10)))
    assert fs.apply_to_round(_angles(), {}, repo=".", base="B", head="H") == _angles()


def test_parse_diff_counts_lines_that_look_like_headers():
    text = ("diff --git a/a.md b/a.md\n--- a/a.md\n+++ b/a.md\n@@ -1,2 +1,2 @@\n"
            "----\n++x\n+new\ndiff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-old\n")
    files = fs.parse_diff(text)
    assert [f["lines"] for f in files] == [3, 1]


def test_parse_diff_handles_quoted_and_spaced_paths():
    text = ('diff --git "a/f\\303\\251.py" "b/f\\303\\251.py"\n--- "a/f\\303\\251.py"\n+++ "b/f\\303\\251.py"\n'
            '@@ -1 +1,2 @@\n+a\n+b\n'
            "diff --git a/x b/y.py b/x b/y.py\n--- a/x b/y.py\n+++ b/x b/y.py\n@@ -1 +1 @@\n+z\n")
    files = fs.parse_diff(text)
    assert [(f["path"], f["lines"]) for f in files] == [("fé.py", 2), ("x b/y.py", 1)]


def test_merge_survives_malformed_finder_fields_and_keeps_distinct_summaries():
    manifest = _manifest()
    merged = fs.merge_segment_replies(manifest, {
        "edge-s1": [{"file": "a.py", "line_range": 7, "summary": "x"},
                    {"file": ["a.py"], "line_range": [[1]], "summary": "y"}, "junk",
                    {"file": "a.py", "line_range": 7, "summary": "second take"}]})
    assert len(merged["edge"]) == 2
    first = merged["edge"][0]
    assert first["also"] == ["second take"]


def test_prompt_quotes_paths_and_split_file_counts_as_uncovered():
    seg = {"id": "s1", "files": ["a b.py", "$(x).py"], "ranges": None}
    p = fs.segment_prompt("P", seg, n=1, base="B", head="H", whole="w")
    assert "'a b.py' '$(x).py'" in p
    manifest = {"angles": [
        {"name": "e-s1", "segment": {"angle": "e", "id": "s1", "files": ["big.py"]}},
        {"name": "e-s2", "segment": {"angle": "e", "id": "s2", "files": ["big.py"]},
         "skipped": "segment-budget"}]}
    assert fs.uncovered_files(manifest) == ["big.py"]


def test_header_tab_and_mixed_quoted_paths_decode_cleanly():
    text = ("diff --git a/sp ace.py b/sp ace.py\n--- a/sp ace.py\t\n+++ b/sp ace.py\t\n@@ -1 +1 @@\n+a\n"
            'diff --git "a/tab\\té.py" "b/tab\\té.py"\n--- "a/tab\\té.py"\n+++ "b/tab\\té.py"\n'
            "@@ -1 +1 @@\n+b\n")
    assert [f["path"] for f in fs.parse_diff(text)] == ["sp ace.py", "tab\té.py"]
