"""Task 2.2: the review-proof predicate carries a proof across round-log commits only."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tp-pr-iterate" / "scripts"))
import proof_predicate  # noqa: E402
import review_proof  # noqa: E402
from deterministic_gate import GateVerdict  # noqa: E402

PR = "https://github.com/o/r/pull/1"
AUTHOR = "tp-loop-bot"
ARCH = "three-pillars-docs/completed-tp-designs"
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
CARRY_CONFIG = {"schema_version": 1, "review": {
    "approval_survives_safe_base_sync": True, "base_sync_carry_max_chain": 5}}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)
    for key, val in IDENT.items():
        monkeypatch.setenv(key, val)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def commit(repo, files):
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "c")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    p = commit(tmp_path, {f"{ARCH}/demo/design.md": "d\n", f"{ARCH}/demo/decisions.md": "a\n"})
    return tmp_path, p


def _digest_for(head):
    meta = {"base": "base000", "head": head, "files_changed": 3, "insertions": 5,
            "deletions": 1, "degraded": False, "reason": None}
    return review_proof.format_proof_digest(meta, [("correctness", 0)])


def _run(root, head, proof_head, config=None, **kw):
    return proof_predicate.pred_review_proof_on_head(
        PR, head, comments_fn=lambda _u: [{"author": AUTHOR, "body": _digest_for(proof_head)}],
        config=config, self_login_fn=lambda: AUTHOR, repo_root=root,
        derive_base_ref_fn=lambda _u: "main", **kw)


def _log_head(r):
    return commit(r, {f"{ARCH}/demo/decisions.md": "a\nb\n"})


@pytest.mark.parametrize("config", [None, CARRY_CONFIG], ids=["off", "on"])
def test_round_log_head_carries_proof(repo, config):
    r, p = repo
    res = _run(r, _log_head(r), p, config)
    assert res.verdict == GateVerdict.PASS
    assert res.detail.startswith(
        f"proof comment carried across 1 round-log commit(s) (anchor {p[:7]})")


def test_code_commit_after_reviewed_head_still_refused(repo):
    r, p = repo
    h = commit(r, {"skills/x.py": "x = 1\n"})
    res = _run(r, h, p)
    assert res.verdict == GateVerdict.INDETERMINATE
    assert res.detail == proof_predicate._NO_PROOF_DETAIL


def test_mixed_commit_after_reviewed_head_still_refused(repo):
    r, p = repo
    h = commit(r, {f"{ARCH}/demo/decisions.md": "a\nz\n", "skills/x.py": "x = 1\n"})
    assert _run(r, h, p).verdict == GateVerdict.INDETERMINATE


def test_no_trusted_digest_spawns_no_git(repo, monkeypatch):
    r, _ = repo
    h = _log_head(r)

    calls = []

    def spy(*a, **k):
        calls.append(a)  # the carry swallows exceptions, so record rather than raise
        raise AssertionError("subprocess spawned")
    monkeypatch.setattr(subprocess, "run", spy)
    res = proof_predicate.pred_review_proof_on_head(
        PR, h, comments_fn=lambda _u: [], self_login_fn=lambda: AUTHOR, repo_root=r)
    assert res.verdict == GateVerdict.INDETERMINATE
    assert calls == []
