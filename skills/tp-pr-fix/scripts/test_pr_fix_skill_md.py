"""Grep-style invariants for `/tp-pr-fix` SKILL.md.

Asserts the prose carries the five contract-level tokens that downstream
code and design audits rely on:

- `[tp-pr-fix iter-` — commit-prefix convention (paired with `fix_round._commit_message`).
- `tp:do-not-merge-yet` — label name (paired with `fix_round._FIX_LABEL`).
- `GIT_COMMITTER_EMAIL` — committer-email override is documented for auditors.
- `standalone` — the worker is callable outside the loop driver.
- `structured-extraction` — the sanitization step is named so reviewers
  can map prose ↔ `structured_extract.extract`.

Run with: pytest skills/tp-pr-fix/scripts/test_pr_fix_skill_md.py -q
"""

from __future__ import annotations

from pathlib import Path

SKILL_MD = Path(__file__).parent.parent / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_iter_n_prefix_named():
    assert "[tp-pr-fix iter-" in _read(), "commit-prefix `[tp-pr-fix iter-N]` must be documented"


def test_label_name_present():
    assert "tp:do-not-merge-yet" in _read(), "label `tp:do-not-merge-yet` must be documented"


def test_committer_email_override_documented():
    assert "GIT_COMMITTER_EMAIL" in _read(), "committer-email override must be documented"


def test_standalone_usage_documented():
    assert "standalone" in _read().lower(), "standalone-use guidance must be present"


def test_structured_extraction_language_present():
    assert "structured-extraction" in _read().lower(), "structured-extraction step must be named"


def test_trusted_bot_gate_documented():
    """F3: the step-6 prose documents the trusted-reviewer-bot short-circuit and
    the TP_PR_FIX_TRUSTED_BOTS env var (the gate is as-built in fix_round)."""
    body = _read()
    assert "TP_PR_FIX_TRUSTED_BOTS" in body, (
        "the trusted-bot env-var extension must be documented"
    )
    assert "trusted-reviewer-bot" in body.lower() or "trusted requested-reviewer" in body.lower(), (
        "the trusted-reviewer-bot gate must be named"
    )
    # The stale 'Copilot 404 → defer non-collaborator' framing must be gone:
    # the Copilot login is now gated THROUGH, not deferred.
    assert "gated through" in body.lower(), (
        "step 6 must state the requested bot is gated through, not deferred"
    )


def test_head_ref_documented():
    """F1: the step-6 prose documents head-ref resolution + refuse-vs-checkout."""
    body = _read()
    assert "headRefName" in body, "head-ref resolution via gh pr view --json headRefName"
    assert "refus" in body.lower(), "standalone refuse-on-mismatch must be documented"
    assert "git checkout" in body.lower(), "loop auto-checkout must be documented"
