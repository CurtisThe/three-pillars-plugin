"""Ordered-orchestration tests for converge.py (Phase 2, traps a + d).

Task 2.1 — the convergence-only GUARD: refuse non-clean / empty-angle rounds.
Task 2.2 — the ordered seam: post before run_round, HEAD invariant, proof-verified
           verdict (B2, B6).

Hermetic: every external interaction is behind an injected seam (post_fn / run_git /
run_round_fn / comments_fn / self_login_fn) — no live gh, no network, no subprocess.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import converge  # noqa: E402
import review_proof  # noqa: E402
from convergence_proof import non_degraded_proof_on_head  # noqa: E402


# ---------- helpers ----------


def _angle(findings) -> str:
    """A `/code-review` reply carrying a fenced JSON findings array."""
    return "Review notes.\n\n```json\n" + json.dumps(findings) + "\n```\n"


_STRUCTURAL = [{
    "file": "foo.py", "line_range": [10, 12],
    "summary": "off-by-one on the loop bound", "verdict": "structural",
}]


def _write_angle(tmp_path, name, findings) -> str:
    p = tmp_path / name
    p.write_text(_angle(findings), encoding="utf-8")
    return str(p)


class _Recorder:
    """Records the ordered seam calls (post + run_round) with a shared counter."""

    def __init__(self, run_round_env=None):
        self.calls: list[str] = []
        self.posts: list[tuple] = []
        self._n = 0
        self._run_round_env = run_round_env or {}
        self.post_index = None
        self.run_round_index = None

    def post_fn(self, pr_url, body):
        self.post_index = self._n
        self._n += 1
        self.calls.append("post")
        self.posts.append((pr_url, body))
        return True

    def run_round_fn(self, stdin):
        self.run_round_index = self._n
        self._n += 1
        self.calls.append("run_round")
        self.last_stdin = stdin
        return dict(self._run_round_env)


def _porcelain():
    out = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(HERE),
        capture_output=True, text=True, check=False,
    )
    return out.stdout


# ============================================================
# Task 2.1 — convergence-only guard (B1, B5-refuse)
# ============================================================


def test_guard_refuses_real_structural_finding(tmp_path):
    """A real structural finding → refuse: zero posts, nothing written, exit != 0."""
    angle = _write_angle(tmp_path, "r1.txt", _STRUCTURAL)
    rec = _Recorder()
    proof_root = tmp_path / "proof"
    state_path = tmp_path / "state.json"
    before = _porcelain()

    rc = converge.converge(
        base="base000", head="head111", pr_url="https://github.com/o/r/pull/1",
        config={"review": {"expects_copilot": False}}, angle_files=[angle],
        proof_root=proof_root, state_path=state_path,
        post_fn=rec.post_fn, run_round_fn=rec.run_round_fn,
        run_git=lambda a: (0, "head111\n", ""),
        out=io.StringIO(), err=io.StringIO(),
    )
    assert rc != 0
    assert rec.posts == []            # posted nothing
    assert not proof_root.exists()    # captured nothing
    assert not state_path.exists()    # mutated no state
    assert _porcelain() == before     # tree unchanged


def test_guard_diagnostic_names_fix_path(tmp_path):
    angle = _write_angle(tmp_path, "r1.txt", _STRUCTURAL)
    err = io.StringIO()
    rc = converge.converge(
        base="base000", head="head111", pr_url="https://github.com/o/r/pull/1",
        config={"review": {"expects_copilot": False}}, angle_files=[angle],
        proof_root=tmp_path / "proof", state_path=tmp_path / "state.json",
        post_fn=lambda u, b: True, run_round_fn=lambda s: {},
        run_git=lambda a: (0, "head111\n", ""),
        out=io.StringIO(), err=err,
    )
    assert rc != 0
    diag = err.getvalue()
    assert "run_round.py" in diag or "/tp-pr-fix" in diag


def test_guard_refuses_empty_angle_set(tmp_path):
    """Empty --angle-file set → NO-ANGLES sentinel → refuse (never a false []) ."""
    rec = _Recorder()
    proof_root = tmp_path / "proof"
    state_path = tmp_path / "state.json"
    rc = converge.converge(
        base="base000", head="head111", pr_url="https://github.com/o/r/pull/1",
        config={"review": {"expects_copilot": False}}, angle_files=[],
        proof_root=proof_root, state_path=state_path,
        post_fn=rec.post_fn, run_round_fn=rec.run_round_fn,
        run_git=lambda a: (0, "head111\n", ""),
        out=io.StringIO(), err=io.StringIO(),
    )
    assert rc != 0
    assert rec.posts == []
    assert not proof_root.exists()
    assert not state_path.exists()


def test_guard_refuses_empty_angle_file_content(tmp_path):
    """An angle file that is empty (unparseable) → degraded → refuse."""
    empty = tmp_path / "r1.txt"
    empty.write_text("", encoding="utf-8")
    rec = _Recorder()
    rc = converge.converge(
        base="base000", head="head111", pr_url="https://github.com/o/r/pull/1",
        config={"review": {"expects_copilot": False}}, angle_files=[str(empty)],
        proof_root=tmp_path / "proof", state_path=tmp_path / "state.json",
        post_fn=rec.post_fn, run_round_fn=rec.run_round_fn,
        run_git=lambda a: (0, "head111\n", ""),
        out=io.StringIO(), err=io.StringIO(),
    )
    assert rc != 0
    assert rec.posts == []


# ============================================================
# Task 2.2 — ordered converge(): post before run_round, HEAD invariant,
#            proof-verified verdict (B2, B6)
# ============================================================


_FULL_HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
_PR = "https://github.com/o/r/pull/1"


def _digest_for(head: str) -> str:
    return review_proof.format_proof_digest({
        "base": "base000", "head": head, "files_changed": 3,
        "insertions": 5, "deletions": 1, "degraded": False, "reason": None,
    })


def _carry_off_config(author="tp-bot") -> dict:
    return {"review": {"expects_copilot": False, "automation_identities": [author]},
            "ci": {"expects_github_checks": False}}


def _run_git_ok(head=_FULL_HEAD):
    def _run(args):
        if args[:2] == ["git", "rev-parse"]:
            return 0, head + "\n", ""
        if "--numstat" in args:
            return 0, "3\t1\tfoo.py\n", ""
        return 0, "", ""
    return _run


def _clean_angle(tmp_path):
    return _write_angle(tmp_path, "r1.txt", [])  # parses to [] — genuinely clean


def test_clean_round_converges_post_before_run_round_head_invariant(tmp_path):
    angle = _clean_angle(tmp_path)
    rec = _Recorder(run_round_env={
        "converged": True, "terminal": "two-stable [code-review-only]",
        "head_sha": _FULL_HEAD,
    })

    def comments_fn(_url):
        # the oracle reads back the digest converge just posted (trusted author).
        return [{"author": "tp-bot", "body": rec.posts[-1][1]}] if rec.posts else []

    out = io.StringIO()
    rc = converge.converge(
        base="base000", head=_FULL_HEAD, pr_url=_PR,
        config=_carry_off_config(), angle_files=[angle],
        label_counts=[("correctness", 0)],
        proof_root=tmp_path / "proof", state_path=tmp_path / "state.json",
        post_fn=rec.post_fn, run_round_fn=rec.run_round_fn,
        comments_fn=comments_fn, self_login_fn=lambda: "tp-bot",
        run_git=_run_git_ok(), out=out, err=io.StringIO(),
    )
    assert rc == 0, out.getvalue()
    result = json.loads(out.getvalue().strip().splitlines()[-1])
    assert result["converged"] is True
    assert result["terminal"] == "two-stable [code-review-only]"
    assert result["head_sha"] == _FULL_HEAD
    assert result["proof_verified"] is True

    # ordering: post is strictly BEFORE the run_round subprocess call.
    assert rec.post_index is not None and rec.run_round_index is not None
    assert rec.post_index < rec.run_round_index

    # run_round stdin carries the REAL clean findings ([]) and OMITS decisions_path.
    assert rec.last_stdin["codereview_findings"] == []
    assert "decisions_path" not in rec.last_stdin
    assert isinstance(rec.last_stdin["review_proof_root"], str)


def test_stale_head_digest_blocks(tmp_path):
    """B6: an injected comments_fn returning a stale-head digest → non-PASS → block."""
    angle = _clean_angle(tmp_path)
    rec = _Recorder(run_round_env={
        "converged": True, "terminal": "two-stable [code-review-only]"})
    out = io.StringIO()
    rc = converge.converge(
        base="base000", head=_FULL_HEAD, pr_url=_PR,
        config=_carry_off_config(), angle_files=[angle],
        proof_root=tmp_path / "proof", state_path=tmp_path / "state.json",
        post_fn=rec.post_fn, run_round_fn=rec.run_round_fn,
        comments_fn=lambda _u: [{"author": "tp-bot", "body": _digest_for("stale" + "0" * 35)}],
        self_login_fn=lambda: "tp-bot",
        run_git=_run_git_ok(), out=out, err=io.StringIO(),
    )
    assert rc != 0
    result = json.loads(out.getvalue().strip().splitlines()[-1])
    assert result["converged"] is False


def test_untrusted_author_digest_blocks(tmp_path):
    """B6: a matching digest from an UNTRUSTED author → non-PASS → block."""
    angle = _clean_angle(tmp_path)
    rec = _Recorder(run_round_env={
        "converged": True, "terminal": "two-stable [code-review-only]"})
    out = io.StringIO()
    rc = converge.converge(
        base="base000", head=_FULL_HEAD, pr_url=_PR,
        config=_carry_off_config(), angle_files=[angle],
        proof_root=tmp_path / "proof", state_path=tmp_path / "state.json",
        post_fn=rec.post_fn, run_round_fn=rec.run_round_fn,
        comments_fn=lambda _u: [{"author": "drive-by", "body": _digest_for(_FULL_HEAD)}],
        self_login_fn=lambda: "tp-bot",
        run_git=_run_git_ok(), out=out, err=io.StringIO(),
    )
    assert rc != 0
    result = json.loads(out.getvalue().strip().splitlines()[-1])
    assert result["converged"] is False


def test_run_round_not_converged_blocks(tmp_path):
    """Oracle PASS but run_round did NOT reach two-stable → still blocked (fail-closed)."""
    angle = _clean_angle(tmp_path)
    rec = _Recorder(run_round_env={
        "converged": False, "terminal": "blocked-no-independent-review",
        "not_converged_reason": "degraded-or-absent-proof-on-head"})

    def comments_fn(_url):
        return [{"author": "tp-bot", "body": rec.posts[-1][1]}] if rec.posts else []

    out = io.StringIO()
    rc = converge.converge(
        base="base000", head=_FULL_HEAD, pr_url=_PR,
        config=_carry_off_config(), angle_files=[angle],
        proof_root=tmp_path / "proof", state_path=tmp_path / "state.json",
        post_fn=rec.post_fn, run_round_fn=rec.run_round_fn,
        comments_fn=comments_fn, self_login_fn=lambda: "tp-bot",
        run_git=_run_git_ok(), out=out, err=io.StringIO(),
    )
    assert rc != 0
    result = json.loads(out.getvalue().strip().splitlines()[-1])
    assert result["converged"] is False


def test_interposed_commit_flips_proof_to_indeterminate():
    """B2 documents the invariant the ordering protects: with carry ON, a proof
    digest for a PRIOR head does NOT satisfy the predicate for a MOVED head (a
    commit interposed after the post) — it flips to non-PASS. Hermetic: the
    base-sync carry seam is neutralized (derive_base_ref_fn → None)."""
    carry_on = {"review": {"expects_copilot": False,
                           "approval_survives_safe_base_sync": True,
                           "automation_identities": ["tp-bot"]}}
    old_head = "0" * 40
    new_head = "1" * 40
    comments_fn = lambda _u: [{"author": "tp-bot", "body": _digest_for(old_head)}]  # noqa: E731

    # the ORIGINAL head is proven...
    assert non_degraded_proof_on_head(
        _PR, old_head, config=carry_on, comments_fn=comments_fn,
        self_login_fn=lambda: "tp-bot", derive_base_ref_fn=lambda _u: None) is True
    # ...but the MOVED head is NOT (INDETERMINATE → False).
    assert non_degraded_proof_on_head(
        _PR, new_head, config=carry_on, comments_fn=comments_fn,
        self_login_fn=lambda: "tp-bot", derive_base_ref_fn=lambda _u: None) is False
