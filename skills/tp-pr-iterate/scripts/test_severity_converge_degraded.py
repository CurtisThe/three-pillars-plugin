"""Degraded-review refusals survive the severity reorder (pr-loop §D1 cases (a)-(c)).

design: review-convergence (Phase 1, D1 — Task 1.4)

`severity.is_blocking` excludes sentinels, so a guard that filters by severity FIRST and
returns None on an empty blocking list would read "no angles ran" (or "an angle would not
parse") as a clean round and post a `:0` proof digest — the L125/M27 class of hole, now
reached from the severity side. The sentinel branch therefore runs before the severity
filter, and it must still say DEGRADED when a real-but-harmless note sits beside the
sentinel (the review did not run cleanly, whatever the note's own verdict).

Hermetic: seams everywhere, including a fake finish, so a guard that fails open reports
as a missing refusal instead of shelling the real run_round.py.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import angles  # noqa: E402
import converge  # noqa: E402
import converge_rounddir  # noqa: E402
import round_scratch  # noqa: E402
import review_merge  # noqa: E402

_HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
_PR = "https://github.com/o/r/pull/7"
_NOTE = {"source": "code-review", "file": "a.py", "line_range": [1, 2],
         "summary": "tighten", "verdict": "minor", "blocking": False, "class": "T"}
_DOWNGRADED = {"source": "code-review", "file": "a.py", "line_range": [1, 1],
               "summary": "x", "class": "P", "blocking": True, "verdict": "structural",
               "reproducer": {"kind": "test", "source": "def test_x():\n    assert False\n"},
               "reproduction": "reproduced", "escape": {"disposition": "downgraded"}}


def _config() -> dict:
    return {"review": {"expects_copilot": False, "automation_identities": ["tp-bot"]},
            "ci": {"expects_github_checks": False}}


def _run_git(head=_HEAD):
    def _run(args):
        if args[:2] == ["git", "rev-parse"]:
            return 0, head + "\n", ""
        if "--numstat" in args:
            return 0, "3\t1\tfoo.py\n", ""
        return 0, "", ""
    return _run


def _finish_seams(finish_calls):
    """Every finish seam injected: a guard that fails open lands in the fake finish."""
    return dict(
        post_fn=lambda url, body: finish_calls.append(("post", body)) or True,
        comments_fn=lambda _u: [], self_login_fn=lambda: "tp-bot",
        run_git=_run_git(), derive_base_ref_fn=None, repo_root=".",
        now_iso="2026-10-09T00:00:00+00:00",
        run_round_fn=lambda stdin: finish_calls.append(("run_round", stdin)) or {
            "converged": True, "terminal": "two-stable [code-review-only]"},
    )


# ---------- (a) sentinel-only → DEGRADED ----------


def test_sentinel_only_guard_names_degraded():
    assert "DEGRADED" in converge.guard_refusal(review_merge.merge_codereview_angles([]))


def test_sentinel_only_angle_file_refuses_degraded(tmp_path):
    """An angle file whose reply cannot be parsed becomes the per-angle sentinel; the
    finish refuses it as DEGRADED, never as a clean `:0` round."""
    angle = tmp_path / "r1.txt"
    angle.write_text("Clean. No findings.\n", encoding="utf-8")
    finish_calls = []
    out, err = io.StringIO(), io.StringIO()
    rc = converge.converge(
        base="base000", head=_HEAD, pr_url=_PR, config=_config(),
        angle_files=[str(angle)], proof_root=tmp_path / "proof",
        state_path=tmp_path / "state.json", out=out, err=err,
        **_finish_seams(finish_calls))
    assert rc == 2
    assert "DEGRADED" in err.getvalue()
    assert finish_calls == []
    assert not (tmp_path / "state.json").exists()


def _round(tmp_path, findings):
    """A round dir with parseable (clean) angle replies and `findings.json` written."""
    proof = tmp_path / "proof"
    r = round_scratch.prepare(
        proof, _PR, angles.DEFAULT_ANGLES, base="b0", head=_HEAD, effort="high",
        state_path=str(proof / "iterate-state.7.v1.json"),
        log_path=str(proof / "iterate-log.7.md"))
    manifest = json.loads((r / round_scratch.MANIFEST).read_text(encoding="utf-8"))
    for entry in manifest["angles"]:
        Path(entry["reply_path"]).write_text('{"findings": []}', encoding="utf-8")
    (r / round_scratch.TAIL / "findings.json").write_text(
        json.dumps(list(findings)), encoding="utf-8")
    return r


def test_sentinel_only_round_dir_refuses_degraded(tmp_path):
    """`converge_rounddir.run` reads `tail/findings.json` straight into the guard, so a
    round whose tail carries only a sentinel must still be refused as DEGRADED."""
    finish_calls = []
    out, err = io.StringIO(), io.StringIO()
    seams = {"out": out, "err": err}
    seams.update(_finish_seams(finish_calls))
    rc = converge_rounddir.run(
        _round(tmp_path, review_merge.merge_codereview_angles([])),
        config=_config(), seams=seams)
    assert rc == 2
    assert "DEGRADED" in err.getvalue()
    assert finish_calls == []
    assert out.getvalue() == ""


# ---------- (b) sentinel + one non-blocking note → DEGRADED ----------


def test_sentinel_plus_minor_note_names_degraded_not_fix_round():
    """The review is degraded even though real evidence was also found: the refusal must
    name DEGRADED (re-run the fan-out), not send the operator to the fix loop for a
    finding that does not block."""
    findings = review_merge.merge_codereview_angles(
        ["not-json garbage", json.dumps({"findings": [_NOTE]})])
    assert len(findings) == 2
    refusal = converge.guard_refusal(findings)
    assert refusal is not None
    assert "DEGRADED" in refusal


def test_sentinel_plus_minor_note_angle_file_refuses_degraded(tmp_path):
    angle_bad = tmp_path / "r1.txt"
    angle_bad.write_text("Clean. No findings.\n", encoding="utf-8")
    angle_note = tmp_path / "r2.txt"
    angle_note.write_text(json.dumps({"findings": [_NOTE]}), encoding="utf-8")
    finish_calls = []
    out, err = io.StringIO(), io.StringIO()
    rc = converge.converge(
        base="base000", head=_HEAD, pr_url=_PR, config=_config(),
        angle_files=[str(angle_bad), str(angle_note)], proof_root=tmp_path / "proof",
        state_path=tmp_path / "state.json", out=out, err=err,
        **_finish_seams(finish_calls))
    assert rc == 2
    assert "DEGRADED" in err.getvalue()
    assert finish_calls == []


def test_sentinel_plus_minor_note_round_dir_refuses_degraded(tmp_path):
    finish_calls = []
    out, err = io.StringIO(), io.StringIO()
    seams = {"out": out, "err": err}
    seams.update(_finish_seams(finish_calls))
    findings = review_merge.merge_codereview_angles([]) + [_NOTE]
    rc = converge_rounddir.run(_round(tmp_path, findings), config=_config(), seams=seams)
    assert rc == 2
    assert "DEGRADED" in err.getvalue()
    assert finish_calls == []


# ---------- (c) Opus-downgraded reproduced finding alone → no refusal ----------


def test_downgraded_reproduced_finding_alone_does_not_refuse():
    """Behavior 8 survives the reorder: with sentinels checked first, a round holding
    only a claim Opus downgraded still has nothing blocking → None."""
    assert converge.guard_refusal([_DOWNGRADED]) is None


def test_downgraded_finding_plus_minor_note_does_not_refuse():
    assert converge.guard_refusal([dict(_NOTE), _DOWNGRADED]) is None
