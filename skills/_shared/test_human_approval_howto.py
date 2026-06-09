"""Content invariants for skills/_shared/human-approval-howto.md (Task 4.5, D8).

A lightweight substring/regex content test (mirrors test_merge_skill_md.py): the
operator guide must document the exact label, how to apply it on the current head,
the human-actor (out-of-band) requirement, the push-strips-it caveat, and that the
land skill (/tp-merge) refuses without a current human approval.

Run with: pytest skills/_shared/test_human_approval_howto.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

HOWTO = Path(__file__).resolve().parent / "human-approval-howto.md"


def _read() -> str:
    return HOWTO.read_text()


def test_howto_file_exists() -> None:
    assert HOWTO.exists(), "skills/_shared/human-approval-howto.md must exist"


def test_howto_covers_label_apply() -> None:
    text = _read()

    # The exact label.
    assert "tp:human-approved" in text, "must document the exact label tp:human-approved"

    # How to apply it (REST labels endpoint and/or gh).
    assert re.search(r"issues/\{?pr_number\}?/labels|labels\[\]=tp:human-approved|add-label", text), (
        "must show how to apply the label via the REST labels endpoint and/or gh"
    )

    # On the current head.
    assert re.search(r"current head|head SHA|on the .*head", text, re.IGNORECASE), (
        "must require applying the label on the current head"
    )


def test_howto_requires_human_out_of_band() -> None:
    text = _read()
    assert re.search(r"human", text, re.IGNORECASE)
    assert re.search(r"out.of.band", text, re.IGNORECASE), (
        "must state the approval is applied by a human out-of-band (not framework automation)"
    )
    assert re.search(r"automation|bot|self.approve|service account", text, re.IGNORECASE), (
        "must explain automation/bots/self cannot satisfy the predicate"
    )


def test_howto_documents_push_strips_it() -> None:
    text = _read()
    assert re.search(r"strip|stale|re.apply|re.approve", text, re.IGNORECASE), (
        "must document that pushing a new commit auto-strips the approval (re-approve)"
    )
    assert re.search(r"push", text, re.IGNORECASE), (
        "must connect the strip to advancing the PR head via a push"
    )


def test_howto_explains_land_refusal() -> None:
    text = _read()
    assert "/tp-merge" in text, "must name the land skill /tp-merge"
    assert re.search(r"refuse|REFUSED|MergeGateBlocked", text, re.IGNORECASE), (
        "must state the land skill refuses without a current human approval"
    )


def test_howto_distinguishes_advisory_label() -> None:
    text = _read()
    assert "tp:ready-for-human-merge" in text, (
        "must distinguish the advisory tp:ready-for-human-merge from the authorizing tp:human-approved"
    )


def test_howto_documents_single_account_rejection_and_remedy() -> None:
    """Design mandate (design.md L65-78): the howto MUST warn that an approver whose
    login equals the gh-auth self-login is REJECTED (INDETERMINATE) on a single-account
    deployment, AND give the remedy (a distinct GitHub identity OR relax via
    review.automation_identities). The refusal message points the operator here."""
    text = _read()
    # The self-login collision rejection is named.
    assert re.search(r"self.login", text, re.IGNORECASE), (
        "must mention the framework's self-login (the rejection cause)"
    )
    assert re.search(r"single.account|single.PAT|same .*login|shar", text, re.IGNORECASE), (
        "must call out the single-account / shared-login deployment"
    )
    assert re.search(r"reject|INDETERMINATE", text, re.IGNORECASE), (
        "must state the single-account operator's own approval is rejected"
    )
    # The remedy: a distinct GitHub identity.
    assert re.search(r"distinct .*identity|separate .*account|different .*login", text, re.IGNORECASE), (
        "must give the remedy: approve from a distinct GitHub identity"
    )
    # The alternate remedy: relax via config key.
    assert "review.automation_identities" in text, (
        "must offer the config remedy review.automation_identities"
    )


def test_howto_binds_currency_to_head_oid_not_timestamp() -> None:
    """Currency is SHA-equality on the immutable head OID (wave2 must-fix #1), NOT a
    forgeable committer timestamp. The howto must describe it as such."""
    text = _read()
    assert re.search(r"commit_id|head OID|head SHA", text), (
        "must describe currency as a head-OID/SHA binding"
    )
    assert re.search(r"SHA.equal|equal .*head|match.* current head", text, re.IGNORECASE), (
        "must describe the binding as SHA-equality with the current head"
    )
