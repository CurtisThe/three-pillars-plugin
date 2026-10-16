"""`converge_rounddir.run` reaches the §D8 evidence-complete terminal (review-convergence 5.7).

design: review-convergence (Task 5.7, detailed-design-pr-loop §D8)

When the round's evidence is in but the bookkeeping refuses (a `--state` that resolves
elsewhere, a finish that came back non-zero), the loop stops at exit 4 with the
`tp-accept:` hint instead of starting another round. The refusal that means the
evidence is NOT in — a real blocking finding (`converge.guard_refusal`), an
unparseable angle reply, a missing/lost manifest — keeps today's exit 2 unchanged, and
a HEAD that moved out from under the round never takes the evidence path.

Oracle: example — the exact stdout JSON line and exit code from `converge_rounddir.run`
on a real round dir, with `run_git` and the finish injected.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import converge  # noqa: E402
import converge_rounddir  # noqa: E402
import round_scratch  # noqa: E402

PR = "https://github.com/o/r/pull/7"
HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
CLEAN = '{"findings": []}'
NOTE = {"file": "a.py", "line_range": [1, 2], "summary": "tighten", "verdict": "minor",
        "blocking": False, "class": "T"}
BLOCK = {"file": "a.py", "line_range": [1, 2], "summary": "bug", "verdict": "structural",
         "blocking": True, "class": "P", "reproduction": "reproduced"}


def _git(head=HEAD):
    def _run(args):
        if args[:2] == ["git", "rev-parse"]:
            return 0, head + "\n", ""
        return 0, "3\t1\tfoo.py\n", ""
    return _run


def _round(tmp_path, *, findings=(NOTE,), head=HEAD):
    proof = tmp_path / "proof"
    r = round_scratch.prepare(proof, PR, [{"name": n, "role": "confirmer", "model": "opus",
                                           "prompt": "p"} for n in ("correctness-leak",
                                                                    "edge-cases")],
                              base="b0", head=head, effort="high",
                              state_path=str(proof / "iterate-state.7.v1.json"),
                              log_path=str(proof / "iterate-log.7.md"))
    manifest = json.loads((r / round_scratch.MANIFEST).read_text(encoding="utf-8"))
    for entry in manifest["angles"]:
        Path(entry["reply_path"]).write_text(CLEAN, encoding="utf-8")
    (r / round_scratch.TAIL / "findings.json").write_text(json.dumps(list(findings)),
                                                          encoding="utf-8")
    return r


def _finish(rc, doc=None):
    """A stand-in `converge._finish_clean` returning `rc` and writing one JSON line."""
    calls = []

    def finish(**kw):
        calls.append(kw)
        kw["out"].write(json.dumps(doc or {"converged": False, "terminal": "budget-exhausted"})
                        + "\n")
        return rc
    return finish, calls


def _run(r, monkeypatch, *, rc=0, finish_doc=None, state_arg=None, run_git=None):
    finish, calls = _finish(rc, finish_doc)
    monkeypatch.setattr(converge, "_finish_clean", finish)
    out, err = io.StringIO(), io.StringIO()
    code = converge_rounddir.run(r, config={}, state_arg=state_arg,
                                 seams={"out": out, "err": err,
                                        "run_git": run_git or _git()})
    return code, out.getvalue(), err.getvalue(), calls


# ---------- the terminal itself ----------


def test_state_path_mismatch_with_evidence_in_is_exit_4(tmp_path, monkeypatch):
    """§D8 row 1: a bookkeeping refusal + parseable Opus reply + 0 blockers → 4 + hint."""
    r = _round(tmp_path)
    code, out, _err, calls = _run(r, monkeypatch, state_arg=str(tmp_path / "x.json"))
    assert code == 4 and calls == []
    doc = json.loads(out.strip())
    assert doc == {"converged": False, "terminal": "evidence-complete", "head_sha": HEAD,
                   "reason": "state-path-mismatch",
                   "accept_hint": f"Approve with a review body line: tp-accept: {HEAD} "
                                  "state-path-mismatch"}


def test_non_zero_finish_with_evidence_in_is_exit_4(tmp_path, monkeypatch):
    """A blocked finish on a round whose evidence is in stops the loop at 4, not another round."""
    r = _round(tmp_path)
    code, out, _err, calls = _run(r, monkeypatch, rc=converge._EXIT_BLOCKED,
                                  finish_doc={"converged": False, "terminal": "budget-exhausted",
                                              "reason": "round cap"})
    assert code == 4 and len(calls) == 1
    doc = json.loads(out.strip().splitlines()[-1])
    assert doc["terminal"] == "evidence-complete" and doc["head_sha"] == HEAD
    assert doc["accept_hint"].startswith(f"Approve with a review body line: tp-accept: {HEAD} ")


def test_exit_4_is_the_evidence_terminal_code():
    assert converge_rounddir.evidence_complete.EXIT_EVIDENCE == 4


# ---------- a HEAD that moved never takes the path ----------


def test_moved_head_keeps_today_behaviour(tmp_path, monkeypatch):
    r = _round(tmp_path)
    code, out, _err, _calls = _run(r, monkeypatch, state_arg=str(tmp_path / "x.json"),
                                   run_git=_git(head="f" * 40))
    assert code == 2 and json.loads(out)["terminal"] == "needs-human-attention"


def test_moved_head_after_a_non_zero_finish_keeps_today_behaviour(tmp_path, monkeypatch):
    r = _round(tmp_path)
    code, out, _err, _calls = _run(r, monkeypatch, rc=converge._EXIT_BLOCKED,
                                   run_git=_git(head="f" * 40))
    assert code == converge._EXIT_BLOCKED
    assert "evidence-complete" not in out


# ---------- refusals that mean the evidence is NOT in ----------


def test_guard_refusal_never_takes_the_evidence_path(tmp_path, monkeypatch):
    """A real blocker is a FIX round, never an acceptance hint (§D8)."""
    r = _round(tmp_path, findings=[BLOCK])
    code, out, err, calls = _run(r, monkeypatch)
    assert code == 2 and calls == [] and "FIX round" in err
    assert "evidence-complete" not in out


def test_unparseable_review_angle_never_takes_the_evidence_path(tmp_path, monkeypatch):
    r = _round(tmp_path)
    manifest = json.loads((r / round_scratch.MANIFEST).read_text(encoding="utf-8"))
    Path(manifest["angles"][0]["reply_path"]).write_text("Clean.\n" + CLEAN,
                                                         encoding="utf-8")
    code, out, _err, calls = _run(r, monkeypatch)
    assert code == 2 and calls == []
    assert json.loads(out)["reason"] == "unparseable-review-angle"


def test_missing_manifest_never_takes_the_evidence_path(tmp_path, monkeypatch):
    code, out, _err, calls = _run(tmp_path / "nope", monkeypatch)
    assert code == 2 and calls == []
    assert json.loads(out)["reason"] == "manifest-invalid"


def test_missing_tail_findings_is_not_evidence_complete(tmp_path, monkeypatch):
    r = _round(tmp_path)
    (r / round_scratch.TAIL / "findings.json").unlink()
    code, out, _err, calls = _run(r, monkeypatch)
    assert code == 2 and calls == []
    assert json.loads(out)["reason"] == "findings-missing"


# ---------- a converged finish is untouched ----------


def test_zero_finish_is_unchanged(tmp_path, monkeypatch):
    r = _round(tmp_path)
    code, out, _err, calls = _run(r, monkeypatch, rc=0,
                                  finish_doc={"converged": True, "terminal": "two-stable"})
    assert code == 0 and len(calls) == 1
    assert "evidence-complete" not in out
