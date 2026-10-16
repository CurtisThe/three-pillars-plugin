"""Tests for review_prep.py — cheap-tier-review-prep (Task 3.1).

Constants, work-dir derivation, facts payloads (exactly the design's keys),
draft_path, per-slot ctx keys, prompt_suffix, diff_bucket edges, and shape
independence from manifest order. Cache / move_work / render come in later
tasks (3.2+).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import review_prep  # noqa: E402


def _work(tmp_path: Path, angles=None) -> Path:
    """A minimal work dir: the shape `open` expects (meta.json with angles)."""
    work = tmp_path / "W"
    work.mkdir(parents=True, exist_ok=True)
    if angles is None:
        angles = [
            {"name": "correctness-leak", "skipped": False, "prompt": "prompt-A"},
            {"name": "edge-cases", "skipped": True, "prompt": "prompt-B"},
        ]
    meta = {"pr_url": "https://github.com/o/r/pull/7", "base": "b1",
            "head": "h1", "repo": ".", "log": "log.md", "angles": angles}
    (work / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return work


def test_constants():
    assert review_prep.SLICER_VERSION == 1
    assert review_prep.PREP_BUDGET_SEC == 300
    assert review_prep.PREP_LINE == ("Labelled cheap-tier prep (may be incomplete; "
                                     "the full diff is authoritative): {path}")


def test_work_dir_is_rounds_pr_prep_work_next(tmp_path):
    w = review_prep.work_dir(tmp_path, "https://github.com/o/r/pull/7")
    assert w == tmp_path / "rounds" / "7" / "prep-work" / "next"


def test_facts_review_slice_exact_keys(tmp_path):
    work = _work(tmp_path)
    f = review_prep.facts("review_slice", work, "correctness-leak")
    assert set(f) == {"slot", "angle", "angle_prompt", "diff_path", "out_path", "rule"}
    assert f["slot"] == "review_slice"
    assert f["angle"] == "correctness-leak"
    assert f["angle_prompt"] == "prompt-A"  # read from W/meta.json angles
    assert f["diff_path"] == str(work / "diff.patch")
    assert f["out_path"] == str(work / "review_slice" / "correctness-leak" / "draft.json")
    assert isinstance(f["rule"], str) and f["rule"]


def test_facts_other_slots_exact_keys(tmp_path):
    work = _work(tmp_path)
    refs = review_prep.facts("review_refs", work, "_")
    assert set(refs) == {"slot", "diff_path", "root", "out_path", "rule"}
    assert refs["root"] == "."
    assert refs["out_path"] == str(work / "review_refs" / "_" / "draft.json")

    triage = review_prep.facts("ci_log_triage", work, "build")
    assert set(triage) == {"slot", "check", "log_path", "out_path", "rule"}
    assert triage["check"] == "build"
    assert triage["log_path"] == str(work / "ci" / "build.log")
    assert triage["out_path"] == str(work / "ci_log_triage" / "build" / "draft.json")

    finding = {"file": "a.py", "line_range": [1, 9], "summary": "s", "class": "P"}
    scaffold = review_prep.facts("repro_scaffold", work, "abc123", finding=finding)
    assert set(scaffold) == {"slot", "finding", "diff_path", "head", "out_path", "rule"}
    assert scaffold["finding"] == finding
    assert scaffold["head"] == "h1"
    assert scaffold["out_path"] == str(work / "repro_scaffold" / "abc123" / "draft.json")


def test_draft_path(tmp_path):
    work = tmp_path / "W"
    assert review_prep.draft_path(work, "review_refs", "_") == \
        work / "review_refs" / "_" / "draft.json"


def test_ctx_for_per_slot(tmp_path):
    work = _work(tmp_path)
    assert review_prep.ctx_for("review_slice", work, unit="correctness-leak",
                               root=".") == {"diff_path": str(work / "diff.patch")}
    assert review_prep.ctx_for("review_refs", work, unit="_", root=".") == {"root": "."}
    assert review_prep.ctx_for("ci_log_triage", work, unit="build", root=".") == \
        {"log_path": str(work / "ci" / "build.log")}
    assert review_prep.ctx_for("repro_scaffold", work, unit="abc", root=".",
                               scratch=tmp_path / "scratch") == \
        {"cwd": ".", "head": "h1", "scratch_dir": str(tmp_path / "scratch")}


def test_prompt_suffix():
    assert review_prep.prompt_suffix(None) == ""
    p = "R/prep/correctness-leak.md"
    assert review_prep.prompt_suffix(p) == "\n\n" + review_prep.PREP_LINE.format(path=p)
    assert (review_prep.prompt_suffix(p)
            == "\n\nLabelled cheap-tier prep (may be incomplete; the full diff is "
               "authoritative): R/prep/correctness-leak.md")


def _diff(n_changed: int) -> str:
    """A diff with exactly `n_changed` changed (`+`/`-`) lines, no headers."""
    return "diff --git a/f.py b/f.py\n" + "\n".join(f"+x{i}" for i in range(n_changed))


def test_diff_bucket_edges():
    assert review_prep.diff_bucket(_diff(50)) == "xs"
    assert review_prep.diff_bucket(_diff(51)) == "s"
    assert review_prep.diff_bucket(_diff(300)) == "s"
    assert review_prep.diff_bucket(_diff(301)) == "m"
    assert review_prep.diff_bucket(_diff(1500)) == "m"
    assert review_prep.diff_bucket(_diff(1501)) == "l"
    assert review_prep.diff_bucket("") == "xs"


def test_shape_independent_of_manifest_order():
    def entry(name, model, role):
        return {"name": name, "model": model, "role": role}
    a = [entry("zeta", "opus", "confirmer"), entry("alpha", "fable", "finder"),
         entry("mid", "opus", "finder"), entry("skip-me", "fable", "confirmer")]
    text = _diff(40)
    assert review_prep.shape({"angles": a}, text) == \
        review_prep.shape({"angles": list(reversed(a))}, text)
