"""`evidence_complete.check` — the §D8 evidence-complete predicate (review-convergence 5.7).

design: review-convergence (Task 5.7, detailed-design-pr-loop §D8)

A bookkeeping refusal on a round whose **evidence is already in** is a terminal, not
another round: the operator approves the head with a `tp-accept:` line instead of
spending a round on paperwork. `check` answers True only when every piece of that
evidence is actually present — a readable `R/tail/findings.json` list, nothing
blocking per `severity.is_blocking`, no degraded sentinel (the same test
`round_freeze` uses), >= 1 non-advisory confirmer on Claude with a parseable reply,
and a working HEAD still equal to the manifest's head. Any git failure or mismatch
fails closed: an evidence-complete terminal posts an acceptance, so it may only fire
on the head the round reviewed.

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
BLOCK = {"file": "a.py", "line_range": [1, 2], "summary": "bug", "verdict": "structural",
         "blocking": True, "class": "P", "reproduction": "reproduced"}
SENTINEL = {"source": "no-angles", "file": "<review-output:unparseable>",
            "summary": "the angle did not parse", "verdict": "minor", "blocking": False}


def _angle(name, *, role="confirmer", model="opus", **extra):
    return {"name": name, "role": role, "model": model, "prompt": "p", **extra}


def _git(head=HEAD, rc=0):
    """`git rev-parse HEAD` → `head` at exit `rc`; anything else is empty."""
    def _run(args):
        if args[:2] == ["git", "rev-parse"] and rc == 0:
            return 0, head + "\n", ""
        return rc, "", "fatal: not a git repository"
    return _run


def _raising_git():
    def _run(_args):
        raise OSError("git: exec failed")
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


# ---------- the complete case (§D8 row 1) ----------


def test_refusal_round_with_full_evidence_is_complete(tmp_path):
    """0 blockers, no sentinel, a parseable Opus confirmer, HEAD unmoved → complete."""
    r = _round(tmp_path, [_angle("scan", role="finder", model="local"),
                          _angle("correctness-leak")], findings=[NOTE])
    complete, reason = _check(r)
    assert complete is True
    assert reason and "tighten" not in reason  # the reason names the round, not a finding


# ---------- the reply must be a real Claude confirmer's (§D8 row 2) ----------


def test_unparseable_confirmer_reply_is_not_complete(tmp_path):
    r = _round(tmp_path, [_angle("correctness-leak")], replies={"correctness-leak":
                                                                "Clean. No findings.\n"})
    complete, _reason = _check(r)
    assert complete is False


def test_advisory_confirmer_reply_is_not_complete(tmp_path):
    """An advisory angle's reply is not the evidence an acceptance rests on."""
    r = _round(tmp_path, [_angle("check", advisory=True)])
    assert _check(r)[0] is False


def test_confirmer_off_claude_is_not_complete(tmp_path):
    """A local-tier reply alone never signs the round (parity with `angles.confirmer_ran`)."""
    r = _round(tmp_path, [_angle("check", model="local")])
    assert _check(r)[0] is False


def test_no_confirmer_at_all_is_not_complete(tmp_path):
    r = _round(tmp_path, [_angle("scan", role="finder", model="local")])
    assert _check(r)[0] is False


# ---------- the findings must be real and non-blocking (§D8 rows 3-4) ----------


def test_blocking_finding_is_not_complete(tmp_path):
    r = _round(tmp_path, [_angle("correctness-leak")], findings=[NOTE, BLOCK])
    assert _check(r)[0] is False


def test_sentinel_finding_is_not_complete(tmp_path):
    """A degraded review is missing evidence, not clean evidence (§D8 "no sentinel")."""
    r = _round(tmp_path, [_angle("correctness-leak")], findings=[SENTINEL, NOTE])
    assert _check(r)[0] is False


def test_missing_findings_json_is_not_complete(tmp_path):
    r = _round(tmp_path, [_angle("correctness-leak")], findings=None)
    complete, reason = _check(r)
    assert complete is False and reason


def test_findings_json_that_is_not_a_list_is_not_complete(tmp_path):
    r = _round(tmp_path, [_angle("correctness-leak")], findings=[])
    (r / round_scratch.TAIL / "findings.json").write_text('{"findings": []}',
                                                          encoding="utf-8")
    assert _check(r)[0] is False


# ---------- HEAD must still be the head the round reviewed (§D8 row 5) ----------


def test_moved_head_is_not_complete(tmp_path):
    r = _round(tmp_path, [_angle("correctness-leak")])
    assert _check(r, run_git=_git(head="f" * 40))[0] is False


def test_manifest_short_head_still_matches_a_full_rev_parse(tmp_path):
    """The manifest carries what the caller passed; a prefix match is the same commit."""
    r = _round(tmp_path, [_angle("correctness-leak")], head=HEAD[:8])
    assert _check(r)[0] is True


def test_git_failure_is_not_complete(tmp_path):
    r = _round(tmp_path, [_angle("correctness-leak")])
    assert _check(r, run_git=_git(rc=128))[0] is False


def test_git_that_raises_is_not_complete(tmp_path):
    r = _round(tmp_path, [_angle("correctness-leak")])
    assert _check(r, run_git=_raising_git())[0] is False


def test_empty_rev_parse_output_is_not_complete(tmp_path):
    r = _round(tmp_path, [_angle("correctness-leak")])
    assert _check(r, run_git=lambda _a: (0, "\n", ""))[0] is False


# ---------- the manifest itself ----------


def test_unreadable_manifest_is_not_complete(tmp_path):
    r = _round(tmp_path, [_angle("correctness-leak")])
    (r / round_scratch.MANIFEST).write_text("{not json", encoding="utf-8")
    assert _check(r)[0] is False
