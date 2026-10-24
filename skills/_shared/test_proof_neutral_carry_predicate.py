"""Task 1.5: the review-proof predicate carries a proof across proof-neutral commits.

A proof-bearing anchor plus 1-3 proof-neutral commits (a living-doc `.md` edit or a comment-only
`.py` edit, at most 200 changed lines) passes `review_proof_on_head` with the design's detail. Every
non-neutral, over-cap or disabled case is today's INDETERMINATE (`_NO_PROOF_DETAIL`). The ci-local
stamp predicate stays round-log-only: a neutral head still FAILs it. Real throwaway git repos, the
fixture shape of `test_round_log_carry_proof.py`; the oracle is example-based (test-fragility.md
section 3): each case is one concrete history with the design's expected verdict and detail.
"""
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
import round_log_carry  # noqa: E402
from deterministic_gate import GateVerdict  # noqa: E402

PR = "https://github.com/o/r/pull/1"
AUTHOR = "tp-loop-bot"
ARCH = "three-pillars-docs/completed-tp-designs"
DOC = "three-pillars-docs/guide.md"
PY = "pkg/a.py"
PRE = "import os\nimport sys\n"  # two neutral lines, so the edited comment sits below lines 1-2
PY_BASE = PRE + "def f():\n    return 1  # old\n"
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
ON_CONFIG = {"review": {"approval_survives_safe_base_sync": True}}
OFF_CONFIG = {"review": {"proof_neutral_carry": False}}
SELF_CFG = {"github": {"pr_author_account": "TeamBot", "per_developer_author": "self"}}
SELF_DETAIL = "self-attested digest by Alice (per_developer_author: self)"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)
    for key, val in IDENT.items():
        monkeypatch.setenv(key, val)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def real_git(repo):
    def _run(args):
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        return (r.returncode, r.stdout, r.stderr)
    return _run


def commit(repo, files):
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "c")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    p = commit(tmp_path, {f"{ARCH}/demo/design.md": "d\n", f"{ARCH}/demo/decisions.md": "a\n",
                          DOC: "guide\n", PY: PY_BASE})
    return tmp_path, p


def _digest_for(head):
    meta = {"base": "base000", "head": head, "files_changed": 3, "insertions": 5,
            "deletions": 1, "degraded": False, "reason": None}
    return review_proof.format_proof_digest(meta, [("correctness", 0)])


def _run(root, head, proof_head, config=None, author=AUTHOR, **kw):
    return proof_predicate.pred_review_proof_on_head(
        PR, head, comments_fn=lambda _u: [{"author": author, "body": _digest_for(proof_head)}],
        config=config, self_login_fn=lambda: AUTHOR, repo_root=root,
        derive_base_ref_fn=lambda _u: "main", **kw)


def doc_commit(r, n=1):
    text = (r / DOC).read_text(encoding="utf-8")
    return commit(r, {DOC: text + "".join(f"more {i}\n" for i in range(n))})


def comment_commit(r):
    return commit(r, {PY: PY_BASE.replace("# old", "# new")})


def log_commit(r):
    return commit(r, {f"{ARCH}/demo/decisions.md": "a\nb\n"})


@pytest.mark.parametrize("config", [None, ON_CONFIG], ids=["default", "carry-key-on"])
def test_a_neutral_doc_commit_carries_the_proof(repo, config):
    r, p = repo
    res = _run(r, doc_commit(r), p, config)
    assert res.verdict == GateVerdict.PASS
    assert res.detail.startswith(
        f"proof comment carried across 1 proof-neutral commit(s) (anchor {p[:7]})")


def test_a_comment_only_py_commit_carries_the_proof(repo):
    r, p = repo
    res = _run(r, comment_commit(r), p)
    assert res.verdict == GateVerdict.PASS
    assert res.detail.startswith(
        f"proof comment carried across 1 proof-neutral commit(s) (anchor {p[:7]})")


def test_a_round_log_then_a_doc_commit_counts_both_links(repo):
    r, p = repo
    log_commit(r)
    res = _run(r, doc_commit(r), p)
    assert res.verdict == GateVerdict.PASS
    assert res.detail.startswith(
        f"proof comment carried across 2 proof-neutral commit(s) (anchor {p[:7]})")


def test_a_doc_commit_then_a_round_log_flush_carries_both(repo):
    r, p = repo
    doc_commit(r)
    res = _run(r, log_commit(r), p)
    assert res.verdict == GateVerdict.PASS
    assert res.detail.startswith(
        f"proof comment carried across 2 proof-neutral commit(s) (anchor {p[:7]})")


def test_three_neutral_commits_at_exactly_200_lines_are_the_edge_that_passes(repo):
    r, p = repo
    doc_commit(r, 99)    # 99 added lines
    comment_commit(r)    # 1 added + 1 deleted
    res = _run(r, doc_commit(r, 99), p)  # 200 changed lines in all
    assert res.verdict == GateVerdict.PASS
    assert "3 proof-neutral commit(s)" in res.detail


def test_a_round_log_only_head_keeps_the_round_log_detail(repo):
    r, p = repo
    res = _run(r, log_commit(r), p)
    assert res.verdict == GateVerdict.PASS
    assert res.detail.startswith(
        f"proof comment carried across 1 round-log commit(s) (anchor {p[:7]})")


def _refused(res):
    assert res.verdict == GateVerdict.INDETERMINATE
    assert res.detail == proof_predicate._NO_PROOF_DETAIL


def test_a_code_commit_is_refused(repo):
    r, p = repo
    _refused(_run(r, commit(r, {"skills/x.py": "x = 1\n"}), p))


def test_a_neutral_commit_over_a_code_commit_is_refused(repo):
    r, p = repo
    commit(r, {"skills/x.py": "x = 1\n"})
    _refused(_run(r, doc_commit(r), p))


def test_five_neutral_commits_are_over_the_link_cap(repo):
    r, p = repo
    for _ in range(4):
        doc_commit(r)
    _refused(_run(r, doc_commit(r), p))


def test_one_201_line_doc_commit_is_over_the_line_cap(repo):
    r, p = repo
    _refused(_run(r, doc_commit(r, 201), p))


def test_the_key_off_restores_todays_refusal(repo):
    r, p = repo
    _refused(_run(r, doc_commit(r), p, OFF_CONFIG))


def test_no_trusted_digest_spawns_no_git(repo, monkeypatch):
    r, _ = repo
    h = doc_commit(r)
    calls = []

    def spy(*a, **k):
        calls.append(a)  # the carry swallows exceptions, so record rather than raise
        raise AssertionError("subprocess spawned")
    monkeypatch.setattr(subprocess, "run", spy)
    res = proof_predicate.pred_review_proof_on_head(
        PR, h, comments_fn=lambda _u: [], self_login_fn=lambda: AUTHOR, repo_root=r)
    assert res.verdict == GateVerdict.INDETERMINATE
    assert calls == []


def test_a_self_attested_digest_carries_across_a_neutral_commit(repo):
    r, p = repo

    def no_login():
        raise AssertionError("must not be called")
    res = proof_predicate.pred_review_proof_on_head(
        PR, doc_commit(r), config=SELF_CFG, self_login_fn=no_login, repo_root=r,
        comments_fn=lambda _u: [{"author": "alice", "body": _digest_for(p)}],
        head_fn=lambda _u: {"author": {"login": "Alice"}, "isCrossRepository": False},
        derive_base_ref_fn=lambda _u: "main")
    assert res.verdict == GateVerdict.PASS
    assert res.detail == (f"proof comment carried across 1 proof-neutral commit(s) "
                          f"(anchor {p[:7]}); {SELF_DETAIL}")


def test_the_ci_local_stamp_is_not_carried_across_a_neutral_commit(repo):
    r, p = repo
    res = round_log_carry.pred_ci_local_stamp_carried(
        doc_commit(r), repo_root=str(r), run_git=real_git(r),
        stamp={"schema": 1, "head_sha": p, "dirty": False})
    assert res.verdict == GateVerdict.FAIL
