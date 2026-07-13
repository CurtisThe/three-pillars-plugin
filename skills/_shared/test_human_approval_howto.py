"""Content invariants for skills/_shared/human-approval-howto.md (retire-approval-tags).

Updated for the review-first howto (Path A label retired): the operator guide must
document the review-path authorization (APPROVED PR review), the human-actor
requirement, the currency check (commit_id == headRefOid), the single-account = no-gate
posture, and that the land skill (/tp-merge) refuses without a current human approval.

Run with: pytest skills/_shared/test_human_approval_howto.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

HOWTO = Path(__file__).resolve().parent / "human-approval-howto.md"


def _read() -> str:
    return HOWTO.read_text(encoding="utf-8")


def test_howto_file_exists() -> None:
    assert HOWTO.exists(), "skills/_shared/human-approval-howto.md must exist"


def test_howto_covers_review_approval() -> None:
    """The howto must document the review-path authorization mechanism."""
    text = _read()

    # The review path must be documented.
    assert re.search(r"APPROVED.*review|review.*APPROVED|Approve|approve", text), (
        "must document the APPROVED PR review authorization mechanism"
    )

    # On the current head.
    assert re.search(r"current head|head SHA|on the .*head", text, re.IGNORECASE), (
        "must require the review to be on the current head"
    )


def test_howto_no_label_apply_instruction() -> None:
    """retire-approval-tags: the howto must NOT instruct the operator to apply a label."""
    text = _read()
    # The label REST snippet (apply label REST call) should be gone.
    assert "issues/{pr_number}/labels" not in text and "issues/\\{pr_number\\}/labels" not in text, (
        "howto must not contain label REST snippet (Path A retired)"
    )
    # Must not tell the operator to create/apply the SHA-tagged label.
    # (It may still mention the label in a historical/retirement context,
    # but must not have an 'Applying it' / 'apply it' operator-instruction section.)
    assert not re.search(
        r"^## Applying it",
        text, re.MULTILINE
    ), "howto must not have an 'Applying it' operator-instruction section (Path A retired)"


def test_howto_requires_human_out_of_band() -> None:
    text = _read()
    assert re.search(r"human", text, re.IGNORECASE)
    assert re.search(r"out.of.band", text, re.IGNORECASE), (
        "must state the approval is applied by a human out-of-band (not framework automation)"
    )
    assert re.search(r"automation|bot|self.approve|service account", text, re.IGNORECASE), (
        "must explain automation/bots/self cannot satisfy the predicate"
    )


def test_howto_documents_currency_via_commit_id() -> None:
    """Currency is the review's immutable commit_id == headRefOid (server-set).
    The howto must document this (not the old SHA-in-label-name mechanism)."""
    text = _read()
    # Must reference the immutable commit_id currency.
    assert re.search(r"commit_id|immutable|server.set", text, re.IGNORECASE), (
        "must describe review currency via the immutable server-set commit_id"
    )
    # Must reference headRefOid or head SHA.
    assert re.search(r"head OID|head SHA|headRefOid|commit_id.*head|head.*commit_id",
                     text, re.IGNORECASE), (
        "must describe currency as a commit_id == headRefOid binding"
    )


def test_howto_explains_land_refusal() -> None:
    text = _read()
    assert "/tp-merge" in text, "must name the land skill /tp-merge"
    assert re.search(r"refuse|REFUSED|MergeGateBlocked", text, re.IGNORECASE), (
        "must state the land skill refuses without a current human approval"
    )


def test_howto_documents_single_account_no_gate() -> None:
    """Design mandate (retire-approval-tags): the howto MUST warn that on a
    single-account setup (operator == framework login) the review-path gate has
    NO distinct human reviewer → you have NO gate. Two-account required for a
    real gate."""
    text = _read()
    # The self-login collision is named.
    assert re.search(r"self.login", text, re.IGNORECASE), (
        "must mention the framework's self-login"
    )
    assert re.search(r"single.account|single.PAT|same .*login|shar", text, re.IGNORECASE), (
        "must call out the single-account / shared-login deployment"
    )
    # Single-account = no gate (not just rejected — no gate at all).
    assert re.search(r"no gate|no distinct|no .*reviewer|cannot.*distinguish", text, re.IGNORECASE), (
        "must state that single-account == no gate (no distinct reviewer)"
    )
    # The remedy: a two-account setup.
    assert re.search(r"two.account|distinct .*identity|separate .*account|different .*login",
                     text, re.IGNORECASE), (
        "must give the remedy: two-account setup for a real gate"
    )
    # The config remedy should still be present.
    assert "review.automation_identities" in text, (
        "must still document review.automation_identities config"
    )


def test_howto_distinguishes_advisory_label() -> None:
    text = _read()
    assert "tp:ready-for-human-merge" in text, (
        "must distinguish the advisory tp:ready-for-human-merge from the review path"
    )
