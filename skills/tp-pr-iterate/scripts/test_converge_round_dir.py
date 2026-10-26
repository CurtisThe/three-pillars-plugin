"""Tests for `converge.py --round-dir` (converge_rounddir) and `--class-log-path`.

design: iterate-convergence-budget (Task 6.3)
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

import angles  # noqa: E402
import converge  # noqa: E402
import converge_cli  # noqa: E402
import round_scratch  # noqa: E402

PR = "https://github.com/o/r/pull/7"
CLEAN = '{"findings": []}'
NOTE = {"file": "a.py", "line_range": [1, 2], "summary": "tighten", "verdict": "minor",
        "blocking": False, "class": "T"}
BLOCK = {"file": "a.py", "line_range": [1, 2], "summary": "bug", "verdict": "structural",
         "blocking": True, "class": "P"}


def _round(tmp_path, *, rounds=1, angle_set=None, findings=(), replies=True):
    proof = tmp_path / "proof"
    kw = dict(base="b0", head="h1", effort="high",
              state_path=str(proof / "iterate-state.7.v1.json"),
              log_path=str(proof / "iterate-log.7.md"))
    r = None
    for i in range(rounds):
        if r is not None:
            (r / "tail" / "envelope.json").write_text('{"action":"fix"}', encoding="utf-8")
        r = round_scratch.prepare(proof, PR, angle_set or angles.DEFAULT_ANGLES, **kw)
    m = json.loads((r / "angles.json").read_text(encoding="utf-8"))
    if replies:
        for e in m["angles"]:
            Path(e["reply_path"]).write_text(CLEAN, encoding="utf-8")
    if findings is not None:
        (r / "tail" / "findings.json").write_text(json.dumps(list(findings)), encoding="utf-8")
    return r, m


class _Fake:
    def __init__(self):
        self.kwargs = None
        self.stdin = None

    def finish(self, **kw):
        self.kwargs = kw
        self.stdin = kw["run_round_fn"]({"state_path": str(kw["state_path"])})
        kw["out"].write(json.dumps({"converged": True, "terminal": "two-stable"}) + "\n")
        return 0


def _main(argv, monkeypatch, tmp_path, cfg=None):
    fake = _Fake()
    monkeypatch.setattr(converge, "_finish_clean", fake.finish)
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(cfg or {}), encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    seams = {"out": out, "err": err, "run_round_fn": lambda stdin: stdin,
             "repo_root": tmp_path}
    rc = converge_cli.main(["--config", str(path), *argv], seams=seams)
    return rc, out.getvalue(), err.getvalue(), fake


def test_paths_come_from_manifest(tmp_path, monkeypatch):
    r, m = _round(tmp_path, findings=[NOTE])
    rc, out, _err, fake = _main(["--round-dir", str(r)], monkeypatch, tmp_path)
    assert rc == 0
    kw = fake.kwargs
    assert str(kw["state_path"]) == m["paths"]["state_path"]
    assert str(kw["proof_root"]) == m["paths"]["proof_root"]
    assert (kw["base"], kw["head"], kw["pr_url"], kw["review_base"]) == ("b0", "h1", PR, "b0")
    assert kw["findings"] == [NOTE]
    assert [lbl for lbl, _ in kw["label_counts"]][0] == "correctness-leak[opus/confirmer]"


def test_digest_counts_each_angles_findings(tmp_path, monkeypatch):
    """The proof digest carries each angle's real finding count, not a constant."""
    r, m = _round(tmp_path, findings=[NOTE])
    Path(m["angles"][0]["reply_path"]).write_text(json.dumps({"findings": [NOTE, NOTE]}),
                                                   encoding="utf-8")
    rc, _out, _err, fake = _main(["--round-dir", str(r)], monkeypatch, tmp_path)
    assert rc == 0
    assert [c for _, c in fake.kwargs["label_counts"]] == [2, 0, 0]


def test_unsegmented_round_posts_the_not_segmented_coverage_line(tmp_path, monkeypatch):
    """Behavior 6: the finish posts the round's coverage line on the check label."""
    angs = [{"name": "edge", "prompt": "p", "role": "finder", "model": "local",
             "advisory": True},
            {"name": "opus-check", "prompt": "p", "role": "confirmer", "model": "opus"}]
    r, _m = _round(tmp_path, angle_set=angs, findings=[NOTE])
    rc, _out, _err, fake = _main(["--round-dir", str(r)], monkeypatch, tmp_path)
    assert rc == 0
    assert [lbl for lbl, _ in fake.kwargs["label_counts"]] == [
        "edge[local/finder]",
        "opus-check[opus/confirmer] [coverage n/a (not segmented)]",
    ]


def test_stdin_carries_round_ordinal_class_log(tmp_path, monkeypatch):
    r, _m = _round(tmp_path)
    log = tmp_path / "class.log"
    rc, _o, _e, fake = _main(["--round-dir", str(r), "--class-log-path", str(log)], monkeypatch, tmp_path)
    assert rc == 0
    assert (fake.stdin["round"], fake.stdin["ordinal"]) == (1, "r1")
    assert fake.stdin["class_log_path"] == str(log)


def test_terminal_json_has_class_tally(tmp_path, monkeypatch):
    r, _m = _round(tmp_path, findings=[NOTE])
    rc, out, _e, _f = _main(["--round-dir", str(r)], monkeypatch, tmp_path)
    doc = json.loads(out.strip().splitlines()[-1])
    assert rc == 0 and doc["converged"] is True
    assert doc["class_tally"]["T"] == 1 and doc["class_tally"]["blocking"] == 0


def test_mismatched_state_refused(tmp_path, monkeypatch):
    r, _m = _round(tmp_path)
    rc, _o, _e, fake = _main(["--round-dir", str(r), "--state", str(tmp_path / "x.json")],
                             monkeypatch, tmp_path)
    assert rc == 2 and fake.kwargs is None


def test_matching_state_accepted(tmp_path, monkeypatch):
    r, m = _round(tmp_path)
    rc, _o, _e, _f = _main(["--round-dir", str(r), "--state", m["paths"]["state_path"]],
                           monkeypatch, tmp_path)
    assert rc == 0


def test_mid_loop_absent_state_refused_before_seed(tmp_path, monkeypatch):
    r, m = _round(tmp_path, rounds=2)
    monkeypatch.setattr(converge, "_seed_state",
                        lambda *a, **k: pytest.fail("seeded mid-loop"))
    rc, out, _e, fake = _main(["--round-dir", str(r)], monkeypatch, tmp_path)
    assert rc == 2 and fake.kwargs is None
    assert json.loads(out)["reason"] == "state-bootstrapped-mid-loop"
    assert not Path(m["paths"]["state_path"]).exists()


def test_mid_loop_present_state_proceeds(tmp_path, monkeypatch):
    r, m = _round(tmp_path, rounds=2)
    Path(m["paths"]["state_path"]).write_text("{}", encoding="utf-8")
    assert _main(["--round-dir", str(r)], monkeypatch, tmp_path)[0] == 0


def test_finder_only_refused(tmp_path, monkeypatch):
    finders = [{"name": "scan", "prompt": "p", "role": "finder", "model": "qwen"}]
    r, _m = _round(tmp_path, angle_set=finders)
    rc, out, _e, fake = _main(["--round-dir", str(r)], monkeypatch, tmp_path)
    assert rc == 2 and fake.kwargs is None
    assert json.loads(out)["reason"] == "no-confirmer"


def test_unparseable_confirmer_refused(tmp_path, monkeypatch):
    r, _m = _round(tmp_path, replies=False)
    assert _main(["--round-dir", str(r)], monkeypatch, tmp_path)[0] == 2


def test_unparseable_angle_reply_refused_not_counted_zero(tmp_path, monkeypatch):
    """M27: a clean tail findings.json never digests an unparseable reply as `:0`."""
    r, m = _round(tmp_path)
    Path(m["angles"][1]["reply_path"]).write_text("Clean.\n" + CLEAN, encoding="utf-8")
    rc, out, _e, fake = _main(["--round-dir", str(r)], monkeypatch, tmp_path)
    assert rc == 2 and fake.kwargs is None
    assert json.loads(out)["reason"] == "unparseable-review-angle"


def test_missing_tail_findings_refused(tmp_path, monkeypatch):
    r, _m = _round(tmp_path, findings=None)
    rc, out, _e, _f = _main(["--round-dir", str(r)], monkeypatch, tmp_path)
    assert rc == 2 and json.loads(out)["reason"] == "findings-missing"


def test_blocking_finding_refused(tmp_path, monkeypatch):
    r, _m = _round(tmp_path, findings=[BLOCK, NOTE])
    rc, _o, err, fake = _main(["--round-dir", str(r)], monkeypatch, tmp_path)
    assert rc == 2 and fake.kwargs is None and "FIX round" in err


def test_legacy_angle_file_refused_with_custom_angles(tmp_path, monkeypatch):
    reply = tmp_path / "r1.txt"
    reply.write_text(CLEAN, encoding="utf-8")
    cfg = {"review": {"angles": [
        {"name": "a", "prompt": "p", "role": "confirmer", "model": "opus"}]}}
    rc, _o, err, fake = _main(["--angle-file", str(reply), "--base", "b", "--head", "h",
                               "--pr-url", PR], monkeypatch, tmp_path, cfg)
    assert rc == 2 and fake.kwargs is None and "--round-dir" in err


def test_legacy_requires_base_head_pr_url(tmp_path, monkeypatch):
    reply = tmp_path / "r1.txt"
    reply.write_text(CLEAN, encoding="utf-8")
    assert _main(["--angle-file", str(reply)], monkeypatch, tmp_path)[0] == 2
