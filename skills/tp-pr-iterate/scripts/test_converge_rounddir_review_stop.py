"""`converge_rounddir.run` forwards a `finalizer_stop` on exit 3, never the exit-4 terminal.

design: seat-escalate-first (Phase 1, Task 1.4)

Oracle: example — exit code and out lines of `converge_rounddir.run` on a notes-only
round dir with the finish injected.
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
import review_stop  # noqa: E402
import round_scratch  # noqa: E402

PR = "https://github.com/o/r/pull/7"
HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
CLEAN = '{"findings": []}'
NOTE = {"file": "a.py", "line_range": [1, 2], "summary": "tighten", "verdict": "minor",
        "blocking": False, "class": "T"}


def _git(args):
    if args[:2] == ["git", "rev-parse"]:
        return 0, HEAD + "\n", ""
    return 0, "3\t1\tfoo.py\n", ""


def _round(tmp_path):
    proof = tmp_path / "proof"
    r = round_scratch.prepare(proof, PR, [{"name": n, "role": "confirmer", "model": "opus",
                                           "prompt": "p"} for n in ("correctness-leak",
                                                                    "edge-cases")],
                              base="b0", head=HEAD, effort="high",
                              state_path=str(proof / "iterate-state.7.v1.json"),
                              log_path=str(proof / "iterate-log.7.md"))
    manifest = json.loads((r / round_scratch.MANIFEST).read_text(encoding="utf-8"))
    for entry in manifest["angles"]:
        Path(entry["reply_path"]).write_text(CLEAN, encoding="utf-8")
    (r / round_scratch.TAIL / "findings.json").write_text(json.dumps([NOTE]), encoding="utf-8")
    return r


def _run(r, monkeypatch, doc, rc=3):
    def finish(**kw):
        kw["out"].write(json.dumps(doc) + "\n")
        return rc
    monkeypatch.setattr(converge, "_finish_clean", finish)
    out, err = io.StringIO(), io.StringIO()
    code = converge_rounddir.run(r, config={}, state_arg=None,
                                 seams={"out": out, "err": err, "run_git": _git})
    return code, [json.loads(ln) for ln in out.getvalue().splitlines()]


def _stop():
    return review_stop.due({}, [NOTE], pr_url=PR, head=HEAD)


def test_a_review_stop_is_forwarded_on_exit_3(tmp_path, monkeypatch):
    stop = _stop()
    doc = {"converged": False, "terminal": None, "reason": "run_round did not converge",
           "finalizer_stop": stop}
    code, lines = _run(_round(tmp_path), monkeypatch, doc)
    assert code == 3
    assert lines[-1]["finalizer_stop"] == stop
    assert all(d.get("terminal") != "evidence-complete" for d in lines)


def test_a_budget_terminal_stop_reaches_the_finalizer_too(tmp_path, monkeypatch):
    doc = {"converged": False, "terminal": "budget-exhausted",
           "finalizer_stop": {"source": "pr-iterate", "signal": "round-cap"}}
    code, lines = _run(_round(tmp_path), monkeypatch, doc)
    assert code == 3
    assert all(d.get("terminal") != "evidence-complete" for d in lines)


def test_no_stop_still_takes_the_evidence_terminal(tmp_path, monkeypatch):
    doc = {"converged": False, "terminal": "budget-exhausted"}
    code, lines = _run(_round(tmp_path), monkeypatch, doc)
    assert code == 4 and lines[-1]["terminal"] == "evidence-complete"
