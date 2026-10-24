"""Task 1.6: the loop's carry question (`carry_check.check`) reaches the proof predicate for a
neutral-only delta, whatever the base-sync key says.

A proof-bearing head P plus 1-3 proof-neutral commits (a living-doc `.md` edit) is reported
carried with reason `NEUTRAL_ON`, even when the committed config is absent or the base-sync key
is not true. The opt-out (`review.proof_neutral_carry: false`), an unreadable committed config, a
code commit above P and a root-commit head are not carried, and on those paths the loop never
fetches PR comments (the predicate is never reached). Where the predicate IS reached but finds no
trusted proof on the anchor, the answer is today's off dict. Real throwaway git repos with the
config committed BEFORE P (a `.json` commit is never neutral); the oracle is example-based
(test-fragility.md section 3): each case is one concrete history with the expected dict.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tp-pr-iterate" / "scripts"))
import carry_check  # noqa: E402
import review_proof  # noqa: E402

PR = "https://github.com/o/r/pull/1"
AUTHOR = "tp-loop-bot"
ARCH = "three-pillars-docs/completed-tp-designs"
DOC = "three-pillars-docs/guide.md"
CFG = ".three-pillars/config.json"
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
NEUTRAL_DETAIL = "proof comment carried across 1 proof-neutral commit(s)"
UNREADABLE_PREFIX = "carry off: config unreadable at HEAD ("


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
        p.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "c")
    return git(repo, "rev-parse", "HEAD")


def cfg(**review):
    """A committed config the reader accepts (a missing `schema_version` ignores the whole file)."""
    return {"schema_version": 1, "review": review}


def build(tmp_path, config=None, raw=None):
    """A repo whose proof-bearing commit P also carries the committed config (if any)."""
    root = tmp_path / "r"
    git(tmp_path, "init", "-q", "-b", "main", str(root))
    files = {f"{ARCH}/demo/design.md": "d\n", f"{ARCH}/demo/decisions.md": "a\n", DOC: "guide\n"}
    if raw is not None:
        files[CFG] = raw
    elif config is not None:
        files[CFG] = json.dumps(config)
    return root, commit(root, files)


def doc_commit(root, n=1):
    text = (root / DOC).read_text(encoding="utf-8")
    return commit(root, {DOC: text + "".join(f"more {i}\n" for i in range(n))})


def _digest_for(head):
    meta = {"base": "base000", "head": head, "files_changed": 3, "insertions": 5,
            "deletions": 1, "degraded": False, "reason": None}
    return review_proof.format_proof_digest(meta, [("correctness", 0)])


class Comments:
    """A recording `comments_fn`: one trusted digest, for `proof_head`."""

    def __init__(self, proof_head):
        self.body = _digest_for(proof_head)
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        return [{"author": AUTHOR, "body": self.body}]


def run_check(root, head, comments):
    runners = {"comments_fn": comments, "self_login_fn": lambda: AUTHOR,
               "derive_base_ref_fn": lambda _u: "main"}
    return carry_check.check(str(root), PR, head, runners=runners)


def off(reason):
    return {"carried": False, "reason": reason, "detail": ""}


@pytest.mark.parametrize("config", [
    None,
    {"schema_version": 1},
    cfg(approval_survives_safe_base_sync=False),
], ids=["no-config", "key-absent", "key-false"])
def test_a_neutral_delta_is_carried_whatever_the_base_sync_key_says(tmp_path, config):
    root, p = build(tmp_path, config)
    res = run_check(root, doc_commit(root), Comments(p))
    assert carry_check.NEUTRAL_ON == "carry on: proof-neutral commits"
    assert res["carried"] is True
    assert res["reason"] == carry_check.NEUTRAL_ON
    assert res["detail"].startswith(f"{NEUTRAL_DETAIL} (anchor {p[:7]})")


def test_a_neutral_delta_with_the_base_sync_key_true_keeps_the_on_reason(tmp_path):
    root, p = build(tmp_path, cfg(approval_survives_safe_base_sync=True))
    res = run_check(root, doc_commit(root), Comments(p))
    assert res["carried"] is True
    assert res["reason"] == carry_check.ON == "carry on"
    assert res["detail"].startswith(f"{NEUTRAL_DETAIL} (anchor {p[:7]})")


def test_the_opt_out_key_is_not_carried_and_never_fetches_comments(tmp_path):
    root, p = build(tmp_path, cfg(proof_neutral_carry=False))
    comments = Comments(p)
    assert run_check(root, doc_commit(root), comments) == off(carry_check.OFF_KEY)
    assert comments.calls == []


def test_an_unreadable_config_is_not_carried_and_never_fetches_comments(tmp_path):
    root, p = build(tmp_path, raw="{ not json")
    comments = Comments(p)
    res = run_check(root, doc_commit(root), comments)
    assert res["carried"] is False
    assert res["reason"].startswith(UNREADABLE_PREFIX)
    assert res["detail"] == ""
    assert comments.calls == []


def test_a_code_commit_is_not_carried_and_never_fetches_comments(tmp_path):
    root, p = build(tmp_path)
    comments = Comments(p)
    head = commit(root, {"skills/x.py": "x = 1\n"})
    assert run_check(root, head, comments) == off(carry_check.OFF_NO_CONFIG)
    assert comments.calls == []


def test_a_root_commit_head_is_not_carried_and_never_fetches_comments(tmp_path):
    root = tmp_path / "r"
    git(tmp_path, "init", "-q", "-b", "main", str(root))
    head = commit(root, {"README.md": "repo\n"})
    comments = Comments(head)
    assert run_check(root, head, comments) == off(carry_check.OFF_NO_CONFIG)
    assert comments.calls == []


def test_a_neutral_delta_without_a_proof_on_the_anchor_is_todays_off_answer(tmp_path):
    root, _ = build(tmp_path)
    # The only trusted digest is for some other head, so the predicate finds no proof on the
    # anchor. It is reached here, so the fetch count is the predicate's business: assert the dict.
    res = run_check(root, doc_commit(root), Comments("f" * 40))
    assert res == off(carry_check.OFF_NO_CONFIG)


def test_a_neutral_commit_over_a_code_commit_is_todays_off_answer(tmp_path):
    root, p = build(tmp_path)
    commit(root, {"skills/x.py": "x = 1\n"})
    assert run_check(root, doc_commit(root), Comments(p)) == off(carry_check.OFF_NO_CONFIG)


def test_five_neutral_commits_are_over_the_link_cap_and_not_carried(tmp_path):
    root, p = build(tmp_path)
    for _ in range(4):
        doc_commit(root)
    assert run_check(root, doc_commit(root), Comments(p)) == off(carry_check.OFF_NO_CONFIG)
