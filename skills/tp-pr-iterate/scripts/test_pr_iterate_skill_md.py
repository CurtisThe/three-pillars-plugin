"""Structured contract checks for `skills/tp-pr-iterate/SKILL.md` (dev repo only).

design: fragile-test-prevention (Part D reference integrity + frontmatter schema, phase 18).
These replace the substring and regex pins on the SKILL.md with checks on parsed
structures: the frontmatter through `skill_frontmatter`, the references (every path,
skill, flag or `python3` invocation the prose names) through `skill_refs` (invariant
46), the model role through `model_policy`, the per-surface Copilot login filter
through `review_readiness`, and the dual-source / reply-and-resolve / proof helpers
directly (they are shipped modules whose behaviour is owned by their own test files).
No assert here reads a heading, a section, a phrase or a line count out of the prose.

Run with: pytest skills/tp-pr-iterate/scripts/test_pr_iterate_skill_md.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS.parent
SKILL_MD = SKILL_DIR / "SKILL.md"
REPO_ROOT = SCRIPTS.parents[2]
for _dir in (REPO_ROOT / "skills" / "_shared", SCRIPTS):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))


def _frontmatter() -> dict:
    """`{key: value}` of the SKILL.md frontmatter, through the shipped parser."""
    skill_frontmatter = pytest.importorskip("skill_frontmatter")
    fields, issues = skill_frontmatter.parse(SKILL_MD.read_text(encoding="utf-8"))
    assert fields is not None and issues == [], f"unparseable frontmatter {issues}"
    return {key: value for key, (_line, value) in fields.items()}


def test_skill_frontmatter_passes_schema():
    """The frontmatter is a closed schema: `name`, `description` and the `argument-hint`
    that declares the skill's interface (`--max-iterations`, `--max-wall-clock`,
    `--dry-run`, `--dispose-only`) — parsed, not read as prose."""
    skill_frontmatter = pytest.importorskip("skill_frontmatter")
    assert skill_frontmatter.check(SKILL_MD) == []


def test_skill_references_resolve(tmp_path):
    """Every path, `/tp-*` skill and `python3` invocation the SKILL.md names resolves
    and parses with its own argparse (invariant 46's check, run in-suite). This covers
    `model_policy.py`, `classifier_judge.py`, `review_merge.py`, `round_scratch.py`,
    `reproduce.py`, `converge.py`, `run_round.py`, `thread_dispose.py`,
    `thread_resolver.py`, `fix_round.py`, the `tp-pr-fix` and `tp-run-full-design`
    skills, the proof-of-review.md pointer and every other referenced script, flag
    or skill the prose once pinned as a substring."""
    skill_refs = pytest.importorskip("skill_refs")
    report = skill_refs.check(REPO_ROOT, [SKILL_MD], cache_dir=tmp_path)
    assert report.issues == []


def test_classifier_role_is_declared():
    """The classifier judge (the Sonnet model that classifies borderline comments)
    is a named model role: `model_policy.ROLES` holds it and `model_for` resolves it
    against the role's own config block (the prose's `model_policy.model_for("classifier",
    config)` seam)."""
    model_policy = pytest.importorskip("model_policy")
    assert "classifier" in model_policy.ROLES
    assert callable(getattr(model_policy, "model_for"))


def test_copilot_logins_per_surface_are_distinct():
    """The Copilot login differs by surface — REST review/comment author carries the
    `[bot]` suffix while GraphQL `reviewThreads…author.login` does not. The registry
    the loop's poll / classify code actually uses must hold a REST set and a bare
    GraphQL login, and the two must be distinct (a single hard-coded filter yields
    false zeros — the observed gotcha this registry exists to prevent)."""
    review_readiness = pytest.importorskip("review_readiness")
    rest = review_readiness._REST_COPILOT_LOGINS
    graphql = review_readiness._GRAPHQL_COPILOT_LOGIN
    assert isinstance(rest, frozenset) and rest
    assert "copilot-pull-request-reviewer[bot]" in rest
    assert isinstance(graphql, str) and graphql
    assert graphql not in rest


def test_dual_source_merge_helpers_are_shipped():
    """Both review sources are normalized, deduped, and merged fail-closed into the
    per-round decision. The dual-source helpers the SKILL.md prose once pinned
    (Enhancement 1, the multi-angle / fail-closed parse contract, and the mandatory
    summary comment on every `/code-review` invocation) must be importable from the
    shipped `review_merge` module — their behaviour is owned by
    `skills/tp-pr-iterate/scripts/test_review_merge.py` and the `test_review_merge_*`
    siblings, not by this prose-pin test."""
    rm = pytest.importorskip("review_merge")
    for name in (
        "normalize_copilot",
        "normalize_codereview",
        "dedupe",
        "merge_codereview_angles",
        "parse_codereview_findings_or_block",
        "format_codereview_comment",
        "post_codereview_comment",
    ):
        assert callable(getattr(rm, name)), name


def test_reply_and_resolve_primitives_are_shipped():
    """The shared reply-and-resolve primitives (reply before resolve, idempotent,
    driven by the per-thread disposition) must be importable from the shipped
    `thread_resolver` and `thread_dispose` modules — the loop's step 9.5 and the
    `--dispose-only` out-of-band path both call the same `dispose_threads` primitive
    (single source of truth), and the behaviour is owned by
    `skills/_shared/test_thread_dispose.py` and `test_thread_resolver.py`, not by
    this prose-pin test."""
    tr = pytest.importorskip("thread_resolver")
    for name in ("disposition_for", "reply_to_thread", "resolve_thread",
                 "list_review_threads"):
        assert callable(getattr(tr, name)), name
    td = pytest.importorskip("thread_dispose")
    assert callable(getattr(td, "dispose_threads"))


def test_transient_copilot_error_detector_is_shipped():
    """The 'Copilot encountered an error' transient build-crash contract (never
    classify it, never terminate on it) is owned by the shipped detector
    `review_readiness.is_error_body` (its `_ERROR_BODY_MARKER` registry) — the
    prose's 'no signal' gotcha is the detector's behaviour, tested in
    `skills/_shared/test_review_readiness.py`, not by a prose substring here."""
    review_readiness = pytest.importorskip("review_readiness")
    assert callable(getattr(review_readiness, "is_error_body"))
    marker = getattr(review_readiness, "_ERROR_BODY_MARKER", "")
    assert isinstance(marker, str) and marker


def test_round_decision_helpers_are_shipped():
    """The per-round re-request (`_request_copilot_review`) and the two-stable /
    blocked-no-independent-review terminal decision live in the shipped
    `loop_driver` module; their behaviour is owned by
    `skills/tp-pr-iterate/scripts/test_loop_driver.py` and the `test_loop_driver_*`
    siblings, not by this prose-pin test."""
    ld = pytest.importorskip("loop_driver")
    assert callable(getattr(ld, "_request_copilot_review"))
    assert callable(getattr(ld, "run_round"))


def test_proof_capture_helpers_are_shipped():
    """The per-round proof-of-review contract (capture proof, digest, present-and-
    nonempty check, and the comment-on-head verifier) lives in the shipped
    `review_proof` module; its behaviour is owned by
    `skills/tp-pr-iterate/scripts/test_review_proof.py` and the `test_review_proof_*`
    siblings, not by this prose-pin test."""
    rp = pytest.importorskip("review_proof")
    for name in ("capture_proof", "proof_present_and_nonempty",
                 "format_proof_digest", "proof_comment_on_head"):
        assert callable(getattr(rp, name)), name
