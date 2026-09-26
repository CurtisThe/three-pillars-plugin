"""Identity-gate tests for `fix_round.run_round` — split out of test_fix_round.py
(500-line test cap). Covers the trusted-reviewer-bot short-circuit, the loop's own
local `/code-review` arm (keyed on the framework-set `source`, never on the
forgeable `reviewer` login), and the envelope schema admitting the arm's null
`comment_id`. Shares the stub-`gh` repo fixture with the base module.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import fix_round  # noqa: E402
from test_fix_round import _git, _make_classified, _make_repo_fixture  # noqa: E402


def test_copilot_bot_reviewer_is_trusted_despite_404(tmp_path, monkeypatch):
    """F3 (pr-fix-targeting): Copilot is a requested-reviewer *Bot*, not a repo
    collaborator, so `gh api .../collaborators/Copilot` 404s. Its review comments
    are legitimate and must be actioned — a trusted-reviewer-bot allowlist
    short-circuits the gate so a structural Copilot comment is applied, NOT
    deferred as 'non-collaborator'. Runs in non-collaborator mode so a regression
    (removing the allowlist) re-defers it and fails this test."""
    clone, env = _make_repo_fixture(tmp_path, mode="non-collaborator")
    _git(clone, "config", "user.email", "curtis.theoret@gmail.com", env=env)
    monkeypatch.chdir(clone)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    (clone / "fix.py").write_text("# fix applied\n")

    classified = [_make_classified("c1", "Copilot")]
    envelope = fix_round.run_round(
        design="foo",
        pr_url="https://github.com/o/r/pull/1",
        iteration=1,
        classified=classified,
    )

    deferred_reasons = [d["reason"] for d in envelope["fixes_deferred"]]
    assert "non-collaborator" not in deferred_reasons, envelope
    assert envelope["verdict"] == "applied", envelope
    assert any(f["comment_id"] == "c1" for f in envelope["fixes_applied"])


def test_local_code_review_arm_is_gated_through_without_a_collaborators_call(
    tmp_path, monkeypatch
):
    """The loop's local `/code-review` arm stamps `source == "code-review"`
    (review_merge.normalize_codereview) and carries no GitHub identity. Without
    a short-circuit the collaborators gate 404s and defers every local finding
    as 'non-collaborator', so the dual-source loop's second half is never fixed.
    Runs in non-collaborator mode and forbids the API call outright."""
    clone, env = _make_repo_fixture(tmp_path, mode="non-collaborator")
    _git(clone, "config", "user.email", "curtis.theoret@gmail.com", env=env)
    monkeypatch.chdir(clone)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    def _no_api(*_a, **_k):  # pragma: no cover — must never run
        raise AssertionError("collaborators API consulted for the local review arm")

    monkeypatch.setattr(fix_round, "_check_collaborator", _no_api)
    (clone / "fix.py").write_text("# fix applied\n")

    classified = [dict(_make_classified("cr-1", "code-review"), source="code-review")]
    envelope = fix_round.run_round(
        design="foo",
        pr_url="https://github.com/o/r/pull/1",
        iteration=1,
        classified=classified,
    )

    deferred_reasons = [d["reason"] for d in envelope["fixes_deferred"]]
    assert "non-collaborator" not in deferred_reasons, envelope
    assert envelope["verdict"] == "applied", envelope
    assert any(f["comment_id"] == "cr-1" for f in envelope["fixes_applied"])


def test_a_github_login_named_code_review_does_not_bypass_the_gate(
    tmp_path, monkeypatch
):
    """`reviewer` is the raw GitHub author login for polled comments, and
    "code-review" is a legal login. The local-arm short-circuit must key on the
    framework-set `source`, so a drive-by comment whose author is literally
    named code-review still goes through the collaborators gate (and, in
    non-collaborator mode, is deferred)."""
    clone, env = _make_repo_fixture(tmp_path, mode="non-collaborator")
    _git(clone, "config", "user.email", "curtis.theoret@gmail.com", env=env)
    monkeypatch.chdir(clone)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    (clone / "fix.py").write_text("# fix applied\n")

    classified = [dict(_make_classified("c-spoof", "code-review"), source="copilot")]
    envelope = fix_round.run_round(
        design="foo",
        pr_url="https://github.com/o/r/pull/1",
        iteration=1,
        classified=classified,
    )

    assert envelope["verdict"] == "no-applicable-fixes", envelope
    assert [d["reason"] for d in envelope["fixes_deferred"]] == ["non-collaborator"]


def test_envelope_schema_accepts_a_local_arm_finding_with_null_comment_id():
    """Local `/code-review` findings carry `comment_id: None`; once they are
    gated through, both `fixes_applied` and `fixes_deferred` entries must still
    validate against fix-envelope.v1.json."""
    from jsonschema import Draft202012Validator

    schema = json.loads(
        (HERE.parent / "schemas" / "fix-envelope.v1.json").read_text(encoding="utf-8")
    )
    envelope = fix_round._make_envelope(
        1, [{"comment_id": None, "summary": "x"}],
        [{"comment_id": None, "reason": "minor-only"}], "applied", 0,
    )
    Draft202012Validator(schema).validate(envelope)
