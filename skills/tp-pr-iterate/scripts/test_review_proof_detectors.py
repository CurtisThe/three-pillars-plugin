"""test_review_proof_detectors.py — posted-comment detectors (enforce-review-proof).

Covers behaviors 1, 2, 9 for proof_comment_on_head + proof_ok, plus the digest
AUTHENTICITY rule (review findings on PR #109, rounds 1–2): a digest only
counts when its comment's AUTHOR is in the NARROW trusted set — the gh self
login + config review.automation_identities extras. The Copilot/native-bot
automation floor is deliberately NOT digest-trusted (an allowlist widens ≠
strengthens; a prompt-injected Copilot comment must not mint proof). Hermetic:
inject comments_fn + self_login_fn; use tmp_path + capture_proof for the local
arm. NEVER calls live gh/git. Digest fixtures are built by calling the REAL
format_proof_digest so the parser is tested against the production string.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import review_proof  # noqa: E402


# ---------- fixtures: real digest strings ----------


def _digest_for(head, base="base0000", files=3, ins=12, dels=4):
    """Build a non-degraded digest body via the REAL format_proof_digest."""
    meta = {
        "base": base, "head": head, "files_changed": files,
        "insertions": ins, "deletions": dels, "degraded": False, "reason": None,
    }
    return review_proof.format_proof_digest(meta, [("correctness", 1), ("edge", 0)])


def _degraded_digest(reason="empty-diff"):
    return review_proof.format_proof_digest({"degraded": True, "reason": reason})


PR = "https://github.com/o/r/pull/1"
HEAD = "def56789aabbccdd"

# Baseline fixtures author digests as the fixtures' own SELF login (the only
# hardcoded-trusted identity after the round-2 narrowing) so head/degraded
# behaviors stay pinned on their own dimension; the author dimension has
# dedicated tests below. _self keeps every test hermetic (the live self-login
# default shells out to gh); _no_self yields an EMPTY trusted set.
AUTHOR = "tp-loop-bot"


def _self():
    return AUTHOR


def _no_self():
    return None


def _c(body, author=AUTHOR):
    """One comments_fn item: a PR comment dict with an author login."""
    return {"author": author, "body": body}


# ---------- proof_comment_on_head (B1, B9) ----------


def test_proof_comment_matching_head_true():
    items = [_c("looks good\n" + _digest_for(HEAD))]
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: items, self_login_fn=_self,
    ) is True


def test_proof_comment_prior_head_only_false():
    items = [_c(_digest_for("0000000aaaa"))]  # a DIFFERENT head
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: items, self_login_fn=_self,
    ) is False


def test_proof_comment_degraded_digest_false():
    items = [_c(_degraded_digest())]
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: items, self_login_fn=_self,
    ) is False


def test_proof_comment_no_proof_comment_false():
    items = [_c("just a normal comment"), _c("another one\nwith lines")]
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: items, self_login_fn=_self,
    ) is False


def test_proof_comment_fn_raises_false():
    def boom(_u):
        raise RuntimeError("gh failed")
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=boom, self_login_fn=_self,
    ) is False


def test_proof_comment_non_list_return_false():
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: "nope", self_login_fn=_self,
    ) is False


def test_proof_comment_falsy_head_false():
    items = [_c(_digest_for(HEAD))]
    assert review_proof.proof_comment_on_head(
        PR, "", comments_fn=lambda _u: items, self_login_fn=_self,
    ) is False


def test_proof_comment_falsy_pr_url_false():
    items = [_c(_digest_for(HEAD))]
    assert review_proof.proof_comment_on_head(
        "", HEAD, comments_fn=lambda _u: items, self_login_fn=_self,
    ) is False


def test_proof_comment_multiple_digests_one_matches_true():
    # Two digests in one body; only the second matches the head — line-by-line scan.
    items = [_c(_digest_for("1111111zzz") + "\n" + _digest_for(HEAD))]
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: items, self_login_fn=_self,
    ) is True


def test_proof_comment_degraded_then_real_in_same_body_true():
    items = [_c(_degraded_digest() + "\n" + _digest_for(HEAD))]
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: items, self_login_fn=_self,
    ) is True


def test_proof_comment_degraded_marker_masks_embedded_digest_on_same_line_false():
    """Adversarial regression for the `_DEGRADED_RE`-skip `continue` branch
    (review finding on PR #109): a line matching BOTH _DEGRADED_RE and
    _DIGEST_HEAD_RE must still read as non-proof."""
    line = _degraded_digest().replace("</sub>", "") + " " + _digest_for(HEAD).replace("<sub>", "")
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: [_c(line)], self_login_fn=_self,
    ) is False


# ---------- authenticity: digest author must be trusted (PR #109 findings) ----------


def test_proof_comment_untrusted_author_false():
    """A drive-by commenter posting a PERFECT head-bound digest must NOT pass."""
    items = [_c(_digest_for(HEAD), author="drive-by-account")]
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: items, self_login_fn=_self,
    ) is False


def test_proof_comment_native_automation_bots_not_trusted():
    """Round-2 narrowing pin: the Copilot/native-bot automation floor must NOT
    mint proof. On expects_copilot=true repos Copilot's comment bodies are
    model-generated from attacker-influencible PR context — a prompt-injected
    Copilot comment echoing the digest line must stay non-proof; ditto the
    GitHub-native bots, which never legitimately post digests."""
    for bot in ("copilot", "Copilot", "copilot-pull-request-reviewer[bot]",
                "github-copilot[bot]", "copilot[bot]",
                "github-actions[bot]", "github-actions", "dependabot[bot]"):
        items = [_c(_digest_for(HEAD), author=bot)]
        assert review_proof.proof_comment_on_head(
            PR, HEAD, comments_fn=lambda _u: items, self_login_fn=_self,
        ) is False, f"digest authored by {bot!r} must not count as proof"


def test_proof_comment_bare_string_item_false():
    """A legacy authorless body (bare str) is never trusted — fail-closed by shape."""
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: [_digest_for(HEAD)], self_login_fn=_self,
    ) is False


def test_proof_comment_empty_author_false():
    items = [_c(_digest_for(HEAD), author="")]
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: items, self_login_fn=_self,
    ) is False


def test_proof_comment_self_login_author_true():
    """The framework's own gh login (the self arm) is trusted."""
    items = [_c(_digest_for(HEAD), author="MyRepoBot")]
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: items, self_login_fn=lambda: "MyRepoBot",
    ) is True


def test_proof_comment_author_match_case_insensitive_true():
    items = [_c(_digest_for(HEAD), author="MYREPOBOT")]
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: items, self_login_fn=lambda: "myrepobot",
    ) is True


def test_proof_comment_config_extra_author_true():
    """config review.automation_identities extends the trusted set (no code change).

    Mixed-case on BOTH sides (round-2 mutation pin): GitHub logins are
    case-preserving, so the extras entry and the comment author must each be
    lowercased — dropping either .lower() silently fails closed in production
    while lowercase-only fixtures stay green."""
    items = [_c(_digest_for(HEAD), author="Org-CI-Bot")]
    cfg = {"review": {"automation_identities": ["ORG-ci-bot"]}}
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: items, config=cfg, self_login_fn=_no_self,
    ) is True


def test_proof_comment_self_login_unresolvable_fail_closed():
    """self_login_fn raising SHRINKS the set (fail-closed): the framework's own
    digest stops matching rather than any author sneaking in. Dual of
    human_approval's F2, where a shrunken set would fail OPEN."""
    def boom():
        raise RuntimeError("gh api user failed")
    items = [_c(_digest_for(HEAD), author="MyRepoBot")]
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: items, self_login_fn=boom,
    ) is False


def test_proof_comment_untrusted_digest_does_not_mask_trusted_one():
    """Trust is per-comment: an untrusted digest never poisons a trusted one."""
    items = [
        _c(_digest_for(HEAD), author="drive-by-account"),
        _c(_digest_for(HEAD)),
    ]
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: items, self_login_fn=_self,
    ) is True


def test_proof_comment_body_none_trusted_author_no_crash_false():
    """The live default can yield body=None ("body": null from the API); a
    trusted-author item with a None/non-str body must neither raise nor count."""
    items = [_c(None), _c(12345)]
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: items, self_login_fn=_self,
    ) is False
    # ...and it must not mask a later valid digest in the same list.
    items = [_c(None), _c(_digest_for(HEAD))]
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: items, self_login_fn=_self,
    ) is True


def test_proof_comment_no_self_lookup_without_digest_candidate():
    """The self-login lookup runs ONLY when a digest-bearing comment needs an
    author check (round-2 finding: a garbage authored comment used to trigger
    a live `gh api user`). A call-RECORDING spy proves it is not called — a
    raising sentinel is useless here because _trusted_digest_authors swallows
    self_login_fn exceptions by design (its fail-closed shrink), so the old
    raising pin passed even against the eager trust-first ordering."""
    calls = []

    def spy():
        calls.append("called")
        return AUTHOR

    items = [_c("just chatter"), _c("more chatter")]
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: items, self_login_fn=spy,
    ) is False
    assert calls == [], "self_login_fn must not run without a digest-bearing candidate"
    # ...and the SAME spy runs exactly once when a digest candidate appears.
    items = [_c("chatter"), _c(_digest_for(HEAD))]
    assert review_proof.proof_comment_on_head(
        PR, HEAD, comments_fn=lambda _u: items, self_login_fn=spy,
    ) is True
    assert calls == ["called"]


def test_proof_comment_prefix_collision_not_proof():
    """Full-SHA currency (round-2 finding): a digest for head H1 must NOT prove
    a different head H2 sharing H1's 7-hex prefix — a 7-char prefix is
    grindable (lucky-commit), so prefix-match would let a push-capable actor
    mint proof for an unreviewed head off an older trusted digest."""
    h1 = "def5678" + "a" * 33
    h2 = "def5678" + "b" * 33
    items = [_c(_digest_for(h1))]
    assert review_proof.proof_comment_on_head(
        PR, h2, comments_fn=lambda _u: items, self_login_fn=_self,
    ) is False
    # Exact full-SHA match still proves.
    assert review_proof.proof_comment_on_head(
        PR, h1, comments_fn=lambda _u: items, self_login_fn=_self,
    ) is True


def test_default_comments_fn_returns_author_body_dicts(monkeypatch):
    """_default_comments_fn parses gh JSON into {"author", "body"} dicts —
    missing author/login folds to "" (untrusted), non-dict items are dropped."""
    payload = {"comments": [
        {"author": {"login": "CurtisTheBot"}, "body": "b1"},
        {"author": {}, "body": "b2"},
        {"body": "b3"},
        "garbage",
    ]}

    class _R:
        returncode = 0
        stdout = json.dumps(payload)
        stderr = ""

    monkeypatch.setattr(review_proof.subprocess, "run", lambda *a, **k: _R())
    assert review_proof._default_comments_fn(PR) == [
        {"author": "CurtisTheBot", "body": "b1"},
        {"author": "", "body": "b2"},
        {"author": "", "body": "b3"},
    ]


# ---------- _default_self_login_fn (round-2 finding: untested sibling) ----------


def _login_result(rc, stdout):
    class _R:
        returncode = rc
        stderr = "boom" if rc else ""
    _R.stdout = stdout
    return _R


def test_default_self_login_fn_strips_output(monkeypatch):
    """A trailing newline must not enter the trusted set (a whitespaced login
    would silently wedge every live p7 evaluation INDETERMINATE)."""
    monkeypatch.setattr(review_proof.subprocess, "run",
                        lambda *a, **k: _login_result(0, "MyBot\n"))
    assert review_proof._default_self_login_fn() == "MyBot"


def test_default_self_login_fn_empty_output_folds_to_none(monkeypatch):
    monkeypatch.setattr(review_proof.subprocess, "run",
                        lambda *a, **k: _login_result(0, "  \n"))
    assert review_proof._default_self_login_fn() is None


def test_default_self_login_fn_raises_on_gh_failure(monkeypatch):
    import pytest
    monkeypatch.setattr(review_proof.subprocess, "run",
                        lambda *a, **k: _login_result(1, ""))
    with pytest.raises(RuntimeError):
        review_proof._default_self_login_fn()


# ---------- proof_ok (B2, B9) ----------


def _stage_local_proof(tmp_path, head, base="base000", numstat="3\t1\tf.py\n"):
    proof_root = tmp_path / "proof"
    review_proof.capture_proof(
        base, head, ["resp"], root=proof_root,
        run_git=lambda args: (0, numstat, ""),
    )
    return proof_root


def test_proof_ok_local_arm_true(tmp_path):
    root = _stage_local_proof(tmp_path, HEAD)
    # Local artifact present, no comment available → True via the local arm.
    assert review_proof.proof_ok(HEAD, root=root, comments_fn=lambda _u: []) is True


def test_proof_ok_comment_arm_true(tmp_path):
    empty_root = tmp_path / "empty"  # no artifact staged
    items = [_c(_digest_for(HEAD))]
    assert review_proof.proof_ok(
        HEAD, pr_url=PR, root=empty_root, comments_fn=lambda _u: items,
        self_login_fn=_self,
    ) is True


def test_proof_ok_comment_arm_untrusted_author_false(tmp_path):
    empty_root = tmp_path / "empty"
    items = [_c(_digest_for(HEAD), author="drive-by-account")]
    assert review_proof.proof_ok(
        HEAD, pr_url=PR, root=empty_root, comments_fn=lambda _u: items,
        self_login_fn=_self,
    ) is False


def test_proof_ok_comment_arm_config_extras_forwarded(tmp_path):
    """Round-2 mutation pin: proof_ok must FORWARD config to the comment arm —
    binding config=None there passed the suite while making extras-authored
    digests invisible to the loop terminal (spurious convergence block)."""
    empty_root = tmp_path / "empty"
    items = [_c(_digest_for(HEAD), author="org-ci-bot")]
    cfg = {"review": {"automation_identities": ["org-ci-bot"]}}
    assert review_proof.proof_ok(
        HEAD, pr_url=PR, root=empty_root, comments_fn=lambda _u: items,
        config=cfg, self_login_fn=_no_self,
    ) is True


def test_proof_ok_both_absent_false(tmp_path):
    empty_root = tmp_path / "empty"
    assert review_proof.proof_ok(
        HEAD, pr_url=PR, root=empty_root, comments_fn=lambda _u: [],
        self_login_fn=_no_self,
    ) is False


def test_proof_ok_no_pr_url_no_local_false(tmp_path):
    empty_root = tmp_path / "empty"
    # pr_url omitted → comment arm not consulted; no local → False.
    assert review_proof.proof_ok(HEAD, root=empty_root) is False


def test_proof_ok_moved_head_false(tmp_path):
    # Local meta head=A and comment head=A, but the QUERY head is B → both arms miss.
    head_a = "aaaaaaa111"
    head_b = "bbbbbbb222"
    root = _stage_local_proof(tmp_path, head_a)
    items = [_c(_digest_for(head_a))]
    assert review_proof.proof_ok(
        head_b, pr_url=PR, root=root, comments_fn=lambda _u: items,
        self_login_fn=_self,
    ) is False


# ---------- own under-cap + c1-clean guards ----------


def test_review_proof_detectors_under_cap():
    src = (HERE / "test_review_proof_detectors.py").read_text(encoding="utf-8")
    lines = src.count("\n") + 1
    assert lines <= 500, f"test_review_proof_detectors.py is {lines} lines (cap=500)"
    assert len(src) <= 50000, f"too many chars ({len(src)})"


def test_review_proof_detectors_c1_clean():
    src = (HERE / "test_review_proof_detectors.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = (alias.name or "").lower()
                assert "anthropic" not in name, f"C1 violation: import {alias.name}"
                assert "claude_agent" not in name, f"C1 violation: import {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").lower()
            assert "anthropic" not in module, f"C1 violation: from {module}"
            assert "claude_agent" not in module, f"C1 violation: from {module}"
