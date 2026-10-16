"""Task 9.4: converge.py records the final head's changed-tests run at two-stable.

Hermetic — every seam injected via `runs_record_fn`; no live test run, no network.
Mirrors the seam/fixture pattern in test_converge_verdict.py.
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


_FULL_HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
_PR = "https://github.com/o/r/pull/1"


def _angle(findings) -> str:
    return "```json\n" + json.dumps({"findings": findings}) + "\n```\n"


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


def _converge_kwargs(tmp_path, rec, runs_record_fn=None):
    angle = tmp_path / "r1.txt"
    angle.write_text(_angle([]), encoding="utf-8")
    return dict(
        base="base000", head=_FULL_HEAD, pr_url=_PR, config=_carry_off_config(),
        angle_files=[str(angle)], proof_root=tmp_path / "proof",
        state_path=tmp_path / "state.json",
        post_fn=rec.post_fn, run_round_fn=rec.run_round_fn,
        comments_fn=rec.comments_fn, self_login_fn=lambda: "tp-bot",
        run_git=_run_git(), runs_record_fn=runs_record_fn,
    )


def test_two_stable_calls_runs_record_with_base_and_head(tmp_path):
    """On a clean two-stable finish, converge calls the runs-record seam exactly once,
    with (repo_root-or-'.', base, head)."""
    rec = _Recorder({"converged": True, "terminal": "two-stable [code-review-only]"})
    calls = []

    def runs_record_fn(root, base, head):
        calls.append((root, base, head))

    out = io.StringIO()
    rc = converge.converge(
        **_converge_kwargs(tmp_path, rec, runs_record_fn=runs_record_fn),
        out=out, err=io.StringIO(),
    )
    assert rc == 0
    result = json.loads(out.getvalue().strip().splitlines()[-1])
    assert result["converged"] is True
    assert calls == [(".", "base000", _FULL_HEAD)]


def test_two_stable_calls_runs_record_with_explicit_repo_root(tmp_path):
    """`repo_root`, when passed, is forwarded verbatim (never defaulted to '.')."""
    rec = _Recorder({"converged": True, "terminal": "two-stable [code-review-only]"})
    calls = []

    def runs_record_fn(root, base, head):
        calls.append((root, base, head))

    out = io.StringIO()
    rc = converge.converge(
        **_converge_kwargs(tmp_path, rec, runs_record_fn=runs_record_fn),
        repo_root="/some/repo", out=out, err=io.StringIO(),
    )
    assert rc == 0
    assert calls == [("/some/repo", "base000", _FULL_HEAD)]


def test_delta_round_records_against_the_pr_base_not_the_prior_head(tmp_path):
    """A delta round's `base` is the prior reviewed head; the head-bound record that
    fragility_clear reads must still cover the whole PR (`review_base`...head)."""
    rec = _Recorder({"converged": True, "terminal": "two-stable [code-review-only]"})
    calls = []
    rc = converge.converge(
        **_converge_kwargs(tmp_path, rec,
                           runs_record_fn=lambda root, base, head: calls.append((base, head))),
        review_base="prbase0", out=io.StringIO(), err=io.StringIO(),
    )
    assert rc == 0
    assert calls == [("prbase0", _FULL_HEAD)]


def test_runs_record_error_is_logged_and_verdict_unchanged(tmp_path):
    """A runs-record seam that raises is fail-open: the two-stable verdict is
    unaffected, and the error is logged to err."""
    rec = _Recorder({"converged": True, "terminal": "two-stable [code-review-only]"})

    def runs_record_fn(root, base, head):
        raise RuntimeError("boom")

    out = io.StringIO()
    err = io.StringIO()
    rc = converge.converge(
        **_converge_kwargs(tmp_path, rec, runs_record_fn=runs_record_fn),
        out=out, err=err,
    )
    assert rc == 0
    result = json.loads(out.getvalue().strip().splitlines()[-1])
    assert result["converged"] is True
    assert err.getvalue().strip() != ""


def test_runs_record_not_called_when_not_converged(tmp_path):
    """A round that does not reach two-stable never calls the runs-record seam —
    it belongs to the success path only."""
    rec = _Recorder({"converged": False, "terminal": None})
    calls = []

    def runs_record_fn(root, base, head):
        calls.append((root, base, head))

    out = io.StringIO()
    rc = converge.converge(
        **_converge_kwargs(tmp_path, rec, runs_record_fn=runs_record_fn),
        out=out, err=io.StringIO(),
    )
    assert rc != 0
    assert calls == []
