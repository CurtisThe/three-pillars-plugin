"""`converge_rounddir` separates the reviewed base from the PR base (review-convergence 4.6).

design: review-convergence (Task 4.6, detailed-design-pr-loop §D3)

A delta round (round n ≥ 2) reviews only the fix delta, so its manifest's `base` is
the prior round's head — while the growth budget must still measure the whole PR.
So the finish passes two different bases down: `review_base` is the manifest's
`pr_base` (the growth measure, `capture_proof`'s three-dot range) and `base` stays
`manifest["base"]` (the digest records the range actually reviewed). A manifest
written before `pr_base` existed has no such key, and its `review_base` falls back
to `base` — the old single-base behaviour, unchanged.

Oracle: example — the exact kwargs `_finish_clean` receives, on a real round dir
built by `round_scratch.prepare` (test-fragility).
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(HERE.parents[1] / "_shared"))

import angles  # noqa: E402
import converge  # noqa: E402
import converge_rounddir  # noqa: E402
import round_scratch  # noqa: E402

PR = "https://github.com/o/r/pull/7"
CLEAN = '{"findings": []}'
NOTE = {"file": "a.py", "line_range": [1, 2], "summary": "tighten", "verdict": "minor",
        "blocking": False, "class": "T"}
PRIOR_HEAD = "b1"  # a delta round's `base`: the head the last round reviewed
PR_BASE = "p0"     # the PR's own base: the growth budget's measure


class _Capture:
    def __init__(self):
        self.kwargs = None

    def finish(self, **kw):
        self.kwargs = kw
        kw["out"].write(json.dumps({"converged": True, "terminal": "two-stable"}) + "\n")
        return 0


def _round(tmp_path, monkeypatch, *, pr_base=PR_BASE):
    """A real round dir whose manifest says: reviewed `PRIOR_HEAD`, PR base `pr_base`."""
    proof = tmp_path / "proof"
    r = round_scratch.prepare(proof, PR, angles.DEFAULT_ANGLES, base=PRIOR_HEAD,
                              head="h1", effort="high",
                              state_path=str(proof / "iterate-state.7.v1.json"),
                              log_path=str(proof / "iterate-log.7.md"))
    m = json.loads((r / "angles.json").read_text(encoding="utf-8"))
    if pr_base is not None:
        m["pr_base"] = pr_base
    (r / "angles.json").write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    for e in m["angles"]:
        Path(e["reply_path"]).write_text(CLEAN, encoding="utf-8")
    (r / "tail" / "findings.json").write_text(json.dumps([NOTE]), encoding="utf-8")
    return r, m


def _run(r, tmp_path, monkeypatch):
    cap = _Capture()
    monkeypatch.setattr(converge, "_finish_clean", cap.finish)
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({}), encoding="utf-8")
    rc = converge_rounddir.run(r, config=str(cfg),
                               seams={"out": io.StringIO(), "err": io.StringIO(),
                                      "run_round_fn": lambda stdin: stdin,
                                      "repo_root": tmp_path})
    assert rc == 0
    return cap.kwargs


def test_review_base_is_pr_base_and_base_stays_the_reviewed_head(tmp_path, monkeypatch):
    r, _m = _round(tmp_path, monkeypatch)
    kw = _run(r, tmp_path, monkeypatch)
    assert kw["review_base"] == PR_BASE
    assert kw["base"] == PRIOR_HEAD
    assert kw["head"] == "h1" and kw["pr_url"] == PR


def test_a_manifest_without_pr_base_keeps_the_single_base(tmp_path, monkeypatch):
    r, _m = _round(tmp_path, monkeypatch, pr_base=None)
    kw = _run(r, tmp_path, monkeypatch)
    assert kw["review_base"] == PRIOR_HEAD == kw["base"]


@pytest.mark.parametrize("key", ["base", "head", "pr_url", "ordinal"])
def test_the_manifest_is_still_the_path_authority(tmp_path, monkeypatch, key):
    """`pr_base` is an extra key: the required manifest keys are still enforced."""
    r, m = _round(tmp_path, monkeypatch)
    m[key] = 7
    (r / "angles.json").write_text(json.dumps(m), encoding="utf-8")
    cap = _Capture()
    monkeypatch.setattr(converge, "_finish_clean", cap.finish)
    out = io.StringIO()
    rc = converge_rounddir.run(r, config=str(tmp_path / "cfg.json"),
                               seams={"out": out, "err": io.StringIO()})
    assert rc == converge._EXIT_REFUSED and cap.kwargs is None
    assert json.loads(out.getvalue())["reason"] == "manifest-invalid"
