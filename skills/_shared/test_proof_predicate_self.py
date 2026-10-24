"""test_proof_predicate_self.py — the gate trusts the PR author's digest under `self`.

design: per-developer-automation-account, Task 1.5 (behaviours 6, 7, 8)

Under `github.per_developer_author: self`, `pred_review_proof_on_head` also trusts a head-bound,
non-degraded digest whose author is the PR author, and the roster detail then says the digest is
self-attested, but only when no base-set digest is on the PASS head. A third party, a stale head,
a degraded digest, an automation author and a fork PR never pass. Under `off`, with no key or with
an invalid value (read as `off`), the path makes exactly today's calls. Carry cases live in
test_proof_predicate_self_carry.py. Hermetic: comments and the head fetch are fakes.

Run with: pytest skills/_shared/test_proof_predicate_self.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
_PR_ITERATE = HERE.parent / "tp-pr-iterate" / "scripts"
if str(_PR_ITERATE) not in sys.path:
    sys.path.insert(0, str(_PR_ITERATE))

import proof_predicate  # noqa: E402
import review_proof  # noqa: E402
from deterministic_gate import GateVerdict  # noqa: E402

PR = "https://github.com/o/r/pull/1"
H = "a" * 40
OLD = "b" * 40
CFG_SELF = {"github": {"pr_author_account": "TeamBot", "per_developer_author": "self"}}
CFG_OFF = {"github": {"pr_author_account": "TeamBot"}}
CFG_BAD = {"github": {"pr_author_account": "TeamBot", "per_developer_author": "own-bot"}}
TODAY = "a head-bound proof comment exists on this head"
SELF_DETAIL = "self-attested digest by Alice (per_developer_author: self)"


def _boom(*_a, **_k):
    raise AssertionError("must not be called")


def head_fn(login="Alice", is_bot=False, cross=False):
    author = {"login": login, **({"is_bot": True} if is_bot else {})}
    return lambda _url: {"author": author, "isCrossRepository": cross}


def digest(head, degraded=False):
    meta = {"base": "base000", "head": head, "files_changed": 3, "insertions": 5,
            "deletions": 1, "degraded": degraded, "reason": "empty-diff" if degraded else None}
    return review_proof.format_proof_digest(meta, [("correctness", 0)])


def comments(*pairs):
    items = [{"author": a, "body": "summary\n" + d} for a, d in pairs]
    return lambda _url: items


def run(config, comments_fn, head=head_fn(), **kw):
    return proof_predicate.pred_review_proof_on_head(
        PR, H, comments_fn=comments_fn, config=config, self_login_fn=_boom, head_fn=head, **kw)


def test_the_authors_digest_on_the_head_passes_with_the_self_attested_detail():
    r = run(CFG_SELF, comments(("alice", digest(H))))
    assert (r.verdict, r.detail) == (GateVerdict.PASS, SELF_DETAIL)


@pytest.mark.parametrize("pairs", [
    [("mallory", digest(H))],                       # a third party
    [("alice", digest(OLD))],                       # a stale head
    [("alice", digest(H, degraded=True))],          # a degraded digest
])
def test_a_third_partys_stale_or_degraded_digest_is_indeterminate(pairs):
    assert run(CFG_SELF, comments(*pairs)).verdict == GateVerdict.INDETERMINATE


def test_a_bot_digest_keeps_todays_detail():
    r = run(CFG_SELF, comments(("teambot", digest(H))))
    assert (r.verdict, r.detail) == (GateVerdict.PASS, TODAY)


def test_a_head_fetch_that_raises_is_indeterminate_and_never_raises():
    boom = lambda _u: (_ for _ in ()).throw(RuntimeError("fetch failed"))  # noqa: E731
    assert run(CFG_SELF, comments(("alice", digest(H))), head=boom).verdict == (
        GateVerdict.INDETERMINATE)


def _recording_head():
    calls = []
    inner = head_fn()

    def f(url):
        calls.append(url)
        return inner(url)

    f.calls = calls
    return f


def test_with_the_key_removed_the_authors_digest_is_indeterminate_and_the_head_never_fetched():
    head = _recording_head()
    r = run(CFG_OFF, comments(("alice", digest(H))), head=head)
    assert r.verdict == GateVerdict.INDETERMINATE
    assert head.calls == []


def test_the_roster_entry_names_the_self_attested_digest():
    import gate_roster
    cfg = {**CFG_SELF, "review": {"require_review_proof": True}}
    _p, roster = gate_roster.build_predicates_and_roster(
        pr_url=PR, rollup=[], failure_class=None, threads=[], mergeable="MERGEABLE",
        head_oid=H, config=cfg,
        r={"comments_fn": comments(("alice", digest(H))), "head_fn": head_fn(),
           "self_login_fn": _boom},
        copilot_runners=None, running_live=False, shared_dir=None)
    entry = [e for e in roster if e.name == "review_proof_on_head"]
    assert len(entry) == 1 and SELF_DETAIL in entry[0].detail


def test_a_bot_digest_on_an_old_head_leaves_the_pass_head_detail_today():
    r = run(CFG_SELF, comments(("teambot", digest(H)), ("alice", digest(OLD))))
    assert (r.verdict, r.detail) == (GateVerdict.PASS, TODAY)


def test_a_base_set_digest_on_the_pass_head_keeps_todays_detail():
    r = run(CFG_SELF, comments(("teambot", digest(H)), ("alice", digest(H))))
    assert (r.verdict, r.detail) == (GateVerdict.PASS, TODAY)


def test_an_automation_author_is_never_trusted():
    r = run(CFG_SELF, comments(("ci-runner", digest(H))), head=head_fn("ci-runner", is_bot=True))
    assert r.verdict == GateVerdict.INDETERMINATE


def test_a_fork_pr_author_is_never_trusted():
    r = run(CFG_SELF, comments(("alice", digest(H))), head=head_fn(cross=True))
    assert r.verdict == GateVerdict.INDETERMINATE


def test_an_invalid_mode_reads_as_off_a_valid_bot_digest_passes_and_the_head_never_fetched():
    head = _recording_head()
    r = run(CFG_BAD, comments(("teambot", digest(H))), head=head)
    assert (r.verdict, r.detail) == (GateVerdict.PASS, TODAY)
    assert head.calls == []


def test_an_invalid_mode_does_not_trust_the_authors_digest():
    head = _recording_head()
    r = run(CFG_BAD, comments(("alice", digest(H))), head=head)
    assert r.verdict == GateVerdict.INDETERMINATE
    assert head.calls == []


def test_carry_off_a_heads_miss_returns_before_any_base_sync_carry(tmp_path):
    derive_calls, git_calls = [], []
    r = run(CFG_SELF, comments(("mallory", digest(H))), repo_root=str(tmp_path),
            run_git=lambda *a, **k: git_calls.append(a),
            derive_base_ref_fn=lambda url: derive_calls.append(url))
    assert r.verdict == GateVerdict.INDETERMINATE
    assert r.detail == proof_predicate._NO_PROOF_DETAIL
    assert derive_calls == [], "derive_base_ref_fn must not be called when carry is off"
    assert git_calls == [], "run_git must not be called when carry is off"
