"""`converge --round-dir` reports an identity stop as its own terminal (PR #284 r1).

design: review-proof-ambient-gh-identity

On a clean round with HEAD unmoved, `evidence_complete.check` is true. A finish that
stops with `bot-auth-unavailable` or `proof-author-untrusted` must still come back as
exit 3 with that reason (round-topology.md step 2), never as the §D8 evidence-complete
accept that would hand the operator a `tp-accept:` hint for an untrusted proof.

Oracle: example — the exit code and stdout JSON lines of `converge_rounddir.run` on a
real round dir, with the post, the comment reader and `run_git` injected.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent.parent / "_shared"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import converge_rounddir  # noqa: E402
import round_scratch  # noqa: E402
from automation_identity import BotAuthUnavailable  # noqa: E402

PR = "https://github.com/o/r/pull/7"
HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


def _git(args):
    if args[:2] == ["git", "rev-parse"]:
        return 0, HEAD + "\n", ""
    return 0, "3\t1\tfoo.py\n", ""


def _run_round_dir(tmp_path, post_fn, comments_fn):
    proof = tmp_path / "proof"
    r = round_scratch.prepare(
        proof, PR,
        [{"name": n, "role": "confirmer", "model": "opus", "prompt": "p"}
         for n in ("correctness-leak", "edge-cases")],
        base="b0", head=HEAD, effort="high",
        state_path=str(proof / "iterate-state.7.v1.json"),
        log_path=str(proof / "iterate-log.7.md"))
    manifest = json.loads((r / round_scratch.MANIFEST).read_text(encoding="utf-8"))
    for e in manifest["angles"]:
        Path(e["reply_path"]).write_text('{"findings": []}', encoding="utf-8")
    (r / round_scratch.TAIL / "findings.json").write_text("[]", encoding="utf-8")
    out = io.StringIO()
    cfg = {"github": {"pr_author_account": "CurtisTheBot"},
           "review": {"expects_copilot": False}, "ci": {"expects_github_checks": False}}
    rc = converge_rounddir.run(r, config=cfg, seams={
        "out": out, "err": io.StringIO(), "post_fn": post_fn, "comments_fn": comments_fn,
        "self_login_fn": lambda: "CurtisThe", "run_git": _git,
        "run_round_fn": lambda s: {"converged": True, "terminal": "two-stable"}})
    return rc, [json.loads(x) for x in out.getvalue().strip().splitlines()]


def test_round_dir_reports_an_unavailable_bot_not_an_evidence_accept(tmp_path):
    def post(url, body):
        raise BotAuthUnavailable("bot 'CurtisTheBot' is not available")
    rc, docs = _run_round_dir(tmp_path, post, lambda u: [])
    assert rc == 3, (rc, docs)
    assert docs[-1]["reason"] == "bot-auth-unavailable", docs
    assert all(d.get("terminal") != "evidence-complete" for d in docs), docs


def test_round_dir_reports_an_untrusted_proof_author_not_an_evidence_accept(tmp_path):
    posts = []

    def post(url, body):
        posts.append(body)
        return True
    rc, docs = _run_round_dir(tmp_path, post,
                              lambda u: [{"author": "CurtisThe", "body": b} for b in posts])
    assert rc == 3, (rc, docs)
    assert docs[-1]["reason"] == "proof-author-untrusted", docs
    assert all(d.get("terminal") != "evidence-complete" for d in docs), docs
