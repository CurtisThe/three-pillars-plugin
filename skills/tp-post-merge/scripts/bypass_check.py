#!/usr/bin/env python3
"""bypass_check.py — the post-merge banner for a landing nobody proved (E3).

design: review-convergence (Task 11.5, detailed-design-gates §E3)

A PR can reach the base with NEITHER a review proof on its merged head NOR an
operator-accept — a bypassed gate, a raw `gh pr merge`, a UI merge. After the
merge there is nothing left to block, so the check is a banner: it names the PR
and the landed head so the operator sees the hole while the clean-revert window
is still open. `/tp-post-merge` step 6.5 prints it. It NEVER blocks and NEVER
writes the base. Gitea → the named unavailable line BEFORE either side is
consulted (degrades VISIBLY, never silently; `gitea-forge-adapter` owns the gap).

Total by construction: a raising fetch on either side is an unprovable
observation ("not proven"), never a raise, never PASS. A missing observation is
never read as proof. stdlib-only; every network runner is injectable.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# review_proof lives in tp-pr-iterate/scripts; proof_predicate, operator_accept + forge in _shared.
_HERE = Path(__file__).resolve().parent
_SHARED = _HERE.parents[1] / "_shared"
_PROOF = _HERE.parents[1] / "tp-pr-iterate" / "scripts"
for _p in (str(_SHARED), str(_PROOF)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import proof_predicate  # noqa: E402 — pred_review_proof_on_head (the proof arm)
import operator_accept  # noqa: E402 — pred_operator_accept (the accept arm)

GITEA_LINE = "bypass check unavailable on gitea (gitea-forge-adapter)"

# Test/hermetic seam: a live run with no injected runner reads these first, so a
# CLI test can go hermetic without ever reaching `gh`. Keys: comments_fn,
# self_login_fn, reviews_fn. Absent → each arm's own live default.
_LIVE_BUILDERS: dict = {}

_PULL_RE = re.compile(r"/pull/(\d+)")


def _pr_number(pr_url) -> str:
    """The PR number from a `/pull/<n>` URL, or `?` when it cannot be read."""
    match = _PULL_RE.search(str(pr_url or ""))
    return match.group(1) if match else "?"


def _is_gitea(repo_root) -> bool:
    """True when `repo_root`'s origin resolves to Gitea. Total: no observation → False."""
    try:
        import forge  # noqa — in _shared/ beside this file

        return getattr(forge.resolve(repo_root), "kind", "") == "gitea"
    except Exception:  # noqa — an unresolvable forge is not a claim of Gitea
        return False


def _proof_present(pr_url, merged_head, comments_fn, runners, config, repo_root) -> bool:
    """The review-proof arm: the merge gate's own predicate PASSes on the merged head.

    `pred_review_proof_on_head` also carries a proof across the two-stable round-log
    flush and certified base-syncs, so a gate-proven landing is never a bypass.
    """
    try:
        from deterministic_gate import GateVerdict  # lazy: late-cycle pair

        result = proof_predicate.pred_review_proof_on_head(
            pr_url, merged_head,
            comments_fn=comments_fn if comments_fn is not None
            else _LIVE_BUILDERS.get("comments_fn"),
            config=config,
            self_login_fn=(runners or {}).get("self_login_fn")
            or _LIVE_BUILDERS.get("self_login_fn"),
            repo_root=repo_root)
        return getattr(result, "verdict", None) is GateVerdict.PASS
    except Exception:  # noqa — an unprovable observation is not proof
        return False


def _accept_present(pr_url, merged_head, runners, config) -> bool:
    """The operator-accept arm: PASS on the merged head."""
    try:
        merged = {}
        for key in ("self_login_fn", "reviews_fn"):
            fn = (runners or {}).get(key) or _LIVE_BUILDERS.get(key)
            if fn is not None:
                merged[key] = fn
        result = operator_accept.pred_operator_accept(
            pr_url, merged_head, runners=merged or None, config=config)
        from deterministic_gate import GateVerdict  # lazy: late-cycle pair

        return getattr(result, "verdict", None) is GateVerdict.PASS
    except Exception:  # noqa — an unprovable observation is not an accept
        return False


def _repo_config(repo_root):
    """`<repo_root>/.three-pillars/config.json` (so the base-sync carry runs from the CLI);
    None when absent, empty or unreadable — fail-open, never a raise."""
    try:
        from repo_config_load import load_repo_config  # noqa — in _shared/

        return load_repo_config(repo_root or ".").config or None
    except Exception:  # noqa — an unreadable config is no config
        return None


def check(pr_url, merged_head, *, comments_fn=None, runners=None,
          config=None, repo_root=".") -> "str | None":
    """The `bypass:` banner when the merged head had neither proof nor accept.

    None (silent) when `proof_predicate.pred_review_proof_on_head` PASSes OR
    `pred_operator_accept` PASSes on it; the named Gitea line on a Gitea origin
    (checked FIRST, before either side is consulted); the `bypass:` line
    otherwise. No `config` → the repo's own config is loaded. Never raises.
    """
    if _is_gitea(repo_root):
        return GITEA_LINE
    if config is None:
        config = _repo_config(repo_root)
    if _proof_present(pr_url, merged_head, comments_fn, runners, config, repo_root):
        return None
    if _accept_present(pr_url, merged_head, runners, config):
        return None
    return (f"bypass: PR #{_pr_number(pr_url)} merged head "
            f"{str(merged_head or '')[:7]} had neither a review proof "
            f"nor an operator-accept")


def main(argv=None) -> int:
    """`bypass_check.py --pr-url U --head SHA [--repo DIR]`.

    Prints the banner line when there is one, nothing when the head was proven.
    ALWAYS exits 0 — this is an advisory post-merge banner, never a gate.
    """
    parser = argparse.ArgumentParser(
        prog="bypass_check.py",
        description="Advisory: did the merged head have a review proof or an "
                    "operator-accept?")
    parser.add_argument("--pr-url", required=True)
    parser.add_argument("--head", required=True,
                        help="the PR's head sha at merge")
    parser.add_argument("--repo", default=".",
                        help="repo root whose origin/config decide the forge "
                             "(default .)")
    args = parser.parse_args(argv)
    try:
        line = check(args.pr_url, args.head, repo_root=args.repo)
    except Exception as exc:  # noqa — advisory: a broken check is a note, not a failure
        line = f"bypass check unavailable ({type(exc).__name__})"
    if line:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
