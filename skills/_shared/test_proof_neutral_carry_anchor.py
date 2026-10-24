"""The walk stops at a reviewed head that is itself a doc or round-log commit (review round 1).

`strip_proof_neutral_commits` used to strip greedily to a code commit, so a proof anchored on a
doc-only commit plus one more neutral commit walked past it and the gate returned INDETERMINATE.
The fix passes the reviewed heads to the walk (`stop_at`). Real throwaway git repos; example-based.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tp-pr-iterate" / "scripts"))
import proof_neutral_carry as pnc  # noqa: E402
import proof_predicate  # noqa: E402
import review_proof  # noqa: E402
from deterministic_gate import GateVerdict  # noqa: E402

BOT = "tp-loop-bot"
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)
    for key, val in IDENT.items():
        monkeypatch.setenv(key, val)


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def _commit(repo, rel, text):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c")
    return _git(repo, "rev-parse", "HEAD")


def _history(repo, extra=1):
    """code, code, reviewed doc-only commit, then `extra` more doc-only commits."""
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, "pkg/a.py", "x = 1\n")
    _commit(repo, "pkg/a.py", "x = 2\n")
    reviewed = _commit(repo, "three-pillars-docs/guide.md", "guide\n")
    head = reviewed
    for i in range(extra):
        head = _commit(repo, "three-pillars-docs/guide.md", "guide\n" + "more\n" * (i + 1))
    return reviewed, head


def _verdict(repo, reviewed, head):
    meta = {"base": "b", "head": reviewed, "files_changed": 1, "insertions": 1,
            "deletions": 0, "degraded": False, "reason": None}
    body = review_proof.format_proof_digest(meta, [("correctness", 0)])
    return proof_predicate.pred_review_proof_on_head(
        "https://github.com/o/r/pull/1", head,
        comments_fn=lambda _u: [{"author": BOT, "body": body}],
        config=None, self_login_fn=lambda: BOT, repo_root=repo,
        derive_base_ref_fn=lambda _u: "main")


def test_proof_on_a_doc_commit_carries_across_one_more_doc_commit(tmp_path):
    reviewed, head = _history(tmp_path)
    res = _verdict(tmp_path, reviewed, head)
    assert res.verdict == GateVerdict.PASS, res.detail


def test_walk_stops_at_the_reviewed_head_not_the_code_commit_below_it(tmp_path):
    reviewed, head = _history(tmp_path, extra=2)
    res = pnc.strip_proof_neutral_commits(tmp_path, head, stop_at=frozenset([reviewed]))
    assert (res.anchor, res.links) == (reviewed, 2)


def test_without_stop_at_the_walk_still_runs_to_the_code_commit(tmp_path):
    reviewed, head = _history(tmp_path)
    res = pnc.strip_proof_neutral_commits(tmp_path, head)
    assert res.anchor != reviewed and res.links == 2
