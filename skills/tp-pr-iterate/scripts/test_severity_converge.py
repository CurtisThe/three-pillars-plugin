"""Behavior 8 at the converge finish: the one severity authority, not the verdict string.

design: review-convergence (Phase 1, D1 — Task 1.4)

`converge.guard_refusal` used to decide "is this round blocking?" from the finding's
`verdict` string — a second severity authority beside `severity.is_blocking`. That is
how #231 came back: a claim Opus's check downgraded still carried `verdict
"structural"` from an earlier pass, so the finish refused on a claim Opus had already
excused, whatever its reproducer did.

These pins hold the new order: the severity authority decides a tagged finding, while
an untagged (legacy) finding keeps its fail-closed `verdict` default — the dispatcher's
one fail-closed refinement, so closing the #231 hole can never open a fail-open one.

Hermetic: every external interaction of the CLI path is an injected seam — no live gh,
no network, no run_round.py subprocess.
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
import converge_cli  # noqa: E402
import review_merge  # noqa: E402

_HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
_PR = "https://github.com/o/r/pull/1"
_REPRO = {"kind": "test", "source": "def test_x():\n    assert False\n"}


def _finding(disposition: str, reproduction: str = "reproduced") -> dict:
    """A tagged finding whose verdict/severity disagree by construction.

    `verdict: "structural"` + `blocking: True` + a passing reproducer, checked by Opus
    with `escape.disposition` = `disposition`. Only the disposition changes between the
    kept and downgraded cases, so a refusal that follows the verdict string and one that
    follows `severity.is_blocking` cannot both be right.
    """
    return {
        "source": "code-review", "file": "a.py", "line_range": [1, 1],
        "summary": "x", "class": "P", "blocking": True, "verdict": "structural",
        "reproducer": dict(_REPRO), "reproduction": reproduction,
        "escape": {"disposition": disposition},
    }


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


class _Recorder:
    def __init__(self):
        self.posts = []

    def post_fn(self, url, body):
        self.posts.append((url, body))
        return True

    def run_round_fn(self, stdin):
        return {"converged": True, "terminal": "two-stable [code-review-only]"}

    def comments_fn(self, _url):
        return [{"author": "tp-bot", "body": self.posts[-1][1]}] if self.posts else []


def _main(argv, tmp_path, seams):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps(_config()), encoding="utf-8")
    return converge_cli.main(["--config", str(cfg), *argv], seams=seams)


def _seams(tmp_path, recorder):
    out, err = io.StringIO(), io.StringIO()
    return out, err, dict(
        proof_root=tmp_path / "proof", state_path=tmp_path / "state.json",
        post_fn=recorder.post_fn, run_round_fn=recorder.run_round_fn,
        comments_fn=recorder.comments_fn, self_login_fn=lambda: "tp-bot",
        run_git=_run_git(), out=out, err=err,
    )


# ---------- guard_refusal — the unit ----------


def test_opus_downgraded_reproduced_finding_alone_does_not_refuse():
    """Behavior 8: Opus downgraded the claim and the reproducer reproduced it.

    #231's exact shape reversed: the reproducer must not re-block a claim Opus excused,
    so the finish is NOT refused and the round may converge.
    """
    assert converge.guard_refusal([_finding("downgraded")]) is None


def test_opus_kept_finding_still_refuses_structurally():
    """Same finding, `disposition: "kept"` → the refusal stands, and it is the
    structural one (never the DEGRADED text — the review genuinely ran)."""
    refusal = converge.guard_refusal([_finding("kept")])
    assert refusal is not None
    assert "DEGRADED" not in refusal
    assert "FIX round" in refusal


def test_refuted_reproducer_does_not_refuse():
    """A reproducer that refutes the claim ends the argument: no refusal."""
    assert converge.guard_refusal([_finding("kept", reproduction="refuted")]) is None


def test_untagged_legacy_structural_finding_still_refuses():
    """Fail-closed: a finding with no `blocking` tag at all (the shape
    `review_merge.normalize_codereview` gives an untagged review finding) keeps its
    `verdict: "structural"` authority — the new severity filter may not read the
    absent tag as "not blocking" and let the round converge."""
    legacy = {"source": "code-review", "file": "a.py", "line_range": [1, 1],
              "summary": "legacy", "verdict": "structural"}
    refusal = converge.guard_refusal([legacy])
    assert refusal is not None
    assert "DEGRADED" not in refusal


def test_untagged_minor_note_still_does_not_refuse():
    """The other side of the legacy default: an untagged note stays a note."""
    note = {"source": "code-review", "file": "a.py", "line_range": [1, 1],
            "summary": "nit", "verdict": "minor"}
    assert converge.guard_refusal([note]) is None


def test_real_structural_finding_refuses_structurally():
    """A tagged, kept, reproduced blocker → the structural refusal names the fix loop."""
    refusal = converge.guard_refusal([_finding("kept")])
    assert refusal is not None
    assert "run_round.py" in refusal or "/tp-pr-fix" in refusal


def test_empty_findings_is_a_clean_round():
    assert converge.guard_refusal([]) is None


# ---------- Behavior 8 through `converge_cli.main --angle-file` ----------


def test_main_angle_file_downgraded_finding_finishes_the_round(tmp_path):
    """The standalone `--angle-file` path has no other backstop, so Behavior 8 must
    hold end-to-end: a reply carrying ONLY the Opus-downgraded claim is not refused by
    the guard — the finish runs, posts its proof, and never prints a refusal."""
    angle = tmp_path / "r1.txt"
    angle.write_text(json.dumps({"findings": [_finding("downgraded")]}), encoding="utf-8")
    rec = _Recorder()
    out, err, seams = _seams(tmp_path, rec)
    rc = _main(["--base", "base000", "--head", _HEAD, "--pr-url", _PR,
                "--angle-file", str(angle)], tmp_path, seams)
    assert rc == 0, err.getvalue()
    assert rec.posts, "the finish never posted its proof digest"
    assert "DEGRADED" not in err.getvalue()
    assert "FIX round" not in err.getvalue()
    assert json.loads(out.getvalue().strip().splitlines()[-1])["converged"] is True


def test_main_angle_file_kept_finding_refuses(tmp_path):
    """The control: the identical reply with `disposition: "kept"` IS refused, so the
    pass above is the disposition's doing and not a guard that stopped refusing."""
    angle = tmp_path / "r1.txt"
    angle.write_text(json.dumps({"findings": [_finding("kept")]}), encoding="utf-8")
    rec = _Recorder()
    _out, err, seams = _seams(tmp_path, rec)
    rc = _main(["--base", "base000", "--head", _HEAD, "--pr-url", _PR,
                "--angle-file", str(angle)], tmp_path, seams)
    assert rc == 2
    assert "FIX round" in err.getvalue()
    assert rec.posts == []


def test_merge_path_carries_the_escape_record_through(tmp_path):
    """Pin (not a behaviour change): the reply above survives the merge with its
    `escape` intact and `blocking` already False, so the guard's severity filter has the
    disposition available at the finish — the place a `verdict: "structural"` tag from an
    earlier pass (the unit cases above) is overridden."""
    findings = review_merge.merge_codereview_angles(
        [json.dumps({"findings": [_finding("downgraded")]})])
    assert len(findings) == 1
    assert findings[0]["escape"] == {"disposition": "downgraded"}
    assert findings[0]["blocking"] is False
    assert converge.guard_refusal(findings) is None
