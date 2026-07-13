"""Fail-closed / tree-clean / idempotent + CLI-wiring tests for converge (B7).

Task 2.3. Hermetic — every seam injected; no live gh, no network, no real
run_round.py subprocess.
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
import converge_cli  # noqa: E402
import review_proof  # noqa: E402


_FULL_HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
_PR = "https://github.com/o/r/pull/1"


def _angle(findings) -> str:
    return "Notes.\n\n```json\n" + json.dumps(findings) + "\n```\n"


def _carry_off_config(author="tp-bot") -> dict:
    return {"review": {"expects_copilot": False, "automation_identities": [author]},
            "ci": {"expects_github_checks": False}}


def _run_git(numstat="3\t1\tfoo.py\n", head=_FULL_HEAD):
    def _run(args):
        if args[:2] == ["git", "rev-parse"]:
            return 0, head + "\n", ""
        if "--numstat" in args:
            return 0, numstat, ""
        return 0, "", ""
    return _run


class _Recorder:
    def __init__(self, env):
        self.posts = []
        self.env = env

    def post_fn(self, url, body):
        self.posts.append((url, body))
        return True

    def run_round_fn(self, stdin):
        self.last_stdin = stdin
        return dict(self.env)

    def comments_fn(self, _url):
        return [{"author": "tp-bot", "body": self.posts[-1][1]}] if self.posts else []


def _porcelain():
    out = subprocess.run(["git", "status", "--porcelain"], cwd=str(HERE),
                         capture_output=True, text=True, check=False)
    return out.stdout


# ============================================================
# B7 — degraded capture fails closed, no false converged, tree clean
# ============================================================


def test_degraded_capture_blocks_and_shows_degraded_digest(tmp_path):
    """Forced empty diff → degraded capture → non-zero, ⚠️ DEGRADED digest, no post."""
    angle = tmp_path / "r1.txt"
    angle.write_text(_angle([]), encoding="utf-8")
    rec = _Recorder({"converged": True, "terminal": "two-stable [code-review-only]"})
    out = io.StringIO()
    before = _porcelain()
    rc = converge.converge(
        base="base000", head=_FULL_HEAD, pr_url=_PR, config=_carry_off_config(),
        angle_files=[str(angle)], proof_root=tmp_path / "proof",
        state_path=tmp_path / "state.json",
        post_fn=rec.post_fn, run_round_fn=rec.run_round_fn,
        comments_fn=rec.comments_fn, self_login_fn=lambda: "tp-bot",
        run_git=_run_git(numstat=""),  # empty diff → degraded
        out=out, err=io.StringIO(),
    )
    assert rc != 0
    result = json.loads(out.getvalue().strip().splitlines()[-1])
    assert result["converged"] is False
    assert "⚠️ DEGRADED" in result["digest"]
    assert rec.posts == []                       # no post on a degraded capture
    assert not (tmp_path / "state.json").exists()  # state never seeded
    assert _porcelain() == before                # tracked tree unchanged


def test_post_failure_blocks(tmp_path):
    """A failed gh post → non-zero, converged False (fail-open post, fail-closed verdict)."""
    angle = tmp_path / "r1.txt"
    angle.write_text(_angle([]), encoding="utf-8")
    out = io.StringIO()
    rc = converge.converge(
        base="base000", head=_FULL_HEAD, pr_url=_PR, config=_carry_off_config(),
        angle_files=[str(angle)], proof_root=tmp_path / "proof",
        state_path=tmp_path / "state.json",
        post_fn=lambda u, b: False,  # post fails
        run_round_fn=lambda s: {"converged": True, "terminal": "two-stable [code-review-only]"},
        comments_fn=lambda u: [], self_login_fn=lambda: "tp-bot",
        run_git=_run_git(), out=out, err=io.StringIO(),
    )
    assert rc != 0
    result = json.loads(out.getvalue().strip().splitlines()[-1])
    assert result["converged"] is False
    assert not (tmp_path / "state.json").exists()  # blocked before seeding state


# ============================================================
# B7 — idempotent re-run on an already-converged head
# ============================================================


def test_idempotent_rerun_equivalent_digest_head_unchanged(tmp_path):
    angle = tmp_path / "r1.txt"
    angle.write_text(_angle([]), encoding="utf-8")

    def _once():
        rec = _Recorder({"converged": True, "terminal": "two-stable [code-review-only]"})
        out = io.StringIO()
        rc = converge.converge(
            base="base000", head=_FULL_HEAD, pr_url=_PR, config=_carry_off_config(),
            angle_files=[str(angle)], label_counts=[("correctness", 0)],
            proof_root=tmp_path / "proof", state_path=tmp_path / "state.json",
            post_fn=rec.post_fn, run_round_fn=rec.run_round_fn,
            comments_fn=rec.comments_fn, self_login_fn=lambda: "tp-bot",
            run_git=_run_git(), now_iso="2026-07-07T00:00:00+00:00",
            out=out, err=io.StringIO(),
        )
        return rc, json.loads(out.getvalue().strip().splitlines()[-1]), rec.posts[-1][1]

    rc1, res1, digest1 = _once()
    rc2, res2, digest2 = _once()
    assert rc1 == 0 and rc2 == 0
    assert res1["converged"] is True and res2["converged"] is True
    assert res1["head_sha"] == res2["head_sha"] == _FULL_HEAD
    assert digest1 == digest2  # equivalent digest posted


# ============================================================
# CLI wiring — main() end-to-end with all seams injected
# ============================================================


def test_main_end_to_end_converges_clean_round(tmp_path):
    angle = tmp_path / "r1.txt"
    angle.write_text(_angle([]), encoding="utf-8")
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(_carry_off_config()), encoding="utf-8")

    rec = _Recorder({"converged": True, "terminal": "two-stable [code-review-only]"})
    out = io.StringIO()
    seams = dict(
        proof_root=tmp_path / "proof", state_path=tmp_path / "state.json",
        post_fn=rec.post_fn, run_round_fn=rec.run_round_fn,
        comments_fn=rec.comments_fn, self_login_fn=lambda: "tp-bot",
        run_git=_run_git(), out=out, err=io.StringIO(),
    )
    argv = [
        "--base", "base000", "--head", _FULL_HEAD, "--pr-url", _PR,
        "--config", str(config_file), "--angle-file", str(angle),
        "--label-count", "correctness:0",
    ]
    rc = converge_cli.main(argv, seams=seams)
    assert rc == 0, out.getvalue()
    result = json.loads(out.getvalue().strip().splitlines()[-1])
    assert result["converged"] is True
    assert result["terminal"] == "two-stable [code-review-only]"
    assert result["proof_verified"] is True


def test_main_rejects_malformed_label_count(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(_carry_off_config()), encoding="utf-8")
    rc = converge_cli.main([
        "--base", "b", "--head", "h", "--pr-url", _PR,
        "--config", str(config_file), "--label-count", "bad",
    ])
    assert rc != 0
