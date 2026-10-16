"""`evidence_complete.check` — a capped confirmer reply is not evidence (review-convergence 7.7).

design: review-convergence (Task 7.7, detailed-design-pr-loop §D8)

A `capped: true` finding in a required confirmer's own reply means that confirmer ran
out of budget mid-review: its findings list is truncated, so "nothing blocking in the
tail" is not evidence the round is clean. The check reads the confirmer's reply file
(`<round>/<confirmer>/reply.md`), never `tail/findings.json`, so the normalised finding
needs no `capped` field. Confirmers are not capped today (caps companion §1), so this
is a defensive guard. Advisory confirmers never gate acceptance, so they never gate here.

Oracle: example — `check` on a real round dir built by `round_scratch.prepare`, with
`run_git` injected (no repo, no network, no model call).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import evidence_complete  # noqa: E402
import round_scratch  # noqa: E402

PR = "https://github.com/o/r/pull/7"
HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
CLEAN = '{"findings": []}'
NOTE = {"file": "a.py", "line_range": [1, 2], "summary": "tighten", "verdict": "minor",
        "blocking": False, "class": "T"}


def _angle(name, *, role="confirmer", model="opus", **extra):
    return {"name": name, "role": role, "model": model, "prompt": "p", **extra}


def _git(head=HEAD, rc=0):
    """`git rev-parse HEAD` → `head` at exit `rc`; anything else is empty."""
    def _run(args):
        if args[:2] == ["git", "rev-parse"] and rc == 0:
            return 0, head + "\n", ""
        return rc, "", "fatal: not a git repository"
    return _run


def _round(tmp_path, angles, *, findings=(), replies=None, head=HEAD):
    """A real round dir: manifest + angle replies + `tail/findings.json`."""
    proof = tmp_path / "proof"
    r = round_scratch.prepare(proof, PR, angles, base="b0", head=head, effort="high",
                              state_path=str(proof / "iterate-state.7.v1.json"),
                              log_path=str(proof / "iterate-log.7.md"))
    manifest = json.loads((r / round_scratch.MANIFEST).read_text(encoding="utf-8"))
    for entry in manifest["angles"]:
        text = (replies or {}).get(entry["name"], CLEAN)
        Path(entry["reply_path"]).write_text(text, encoding="utf-8")
    if findings is not None:
        (r / round_scratch.TAIL / "findings.json").write_text(
            json.dumps(list(findings)), encoding="utf-8")
    return r


def _check(r, **kw):
    return evidence_complete.check(r, run_git=kw.pop("run_git", _git()), **kw)


def _reply(*findings):
    return json.dumps({"findings": list(findings)})


def test_capped_confirmer_reply_is_not_complete(tmp_path):
    """A required confirmer whose reply carries `capped: true` → not evidence."""
    r = _round(tmp_path, [_angle("correctness-leak")], findings=[NOTE],
               replies={"correctness-leak": _reply({**NOTE, "capped": True})})
    complete, reason = _check(r)
    assert complete is False
    assert "capped" in reason


def test_uncapped_confirmer_reply_is_complete(tmp_path):
    """Control: the same round with an uncapped reply is evidence-complete."""
    r = _round(tmp_path, [_angle("correctness-leak")], findings=[NOTE],
               replies={"correctness-leak": _reply(NOTE)})
    complete, _reason = _check(r)
    assert complete is True


def test_capped_advisory_confirmer_does_not_block(tmp_path):
    """Only a required confirmer's cap counts; an advisory one never gates."""
    r = _round(tmp_path, [_angle("style", advisory=True), _angle("correctness-leak")],
               findings=[NOTE],
               replies={"style": _reply({**NOTE, "capped": True}),
                        "correctness-leak": _reply(NOTE)})
    complete, reason = _check(r)
    assert complete is True, reason
