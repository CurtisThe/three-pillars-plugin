"""test_consumer_offers_handoffs.py — first-run offer (c): the .handoffs/
ignore rule (archive-slimming, Task 2.2).

`.handoffs/` round-bundle JSON is never committed, but the cold-resume
worklists (`.md`) still are, so the rule is a pair per root and must be
offered, never applied silently: the offer runs the shipped
`handoffs_ignore.py check`, shows the exact four lines (both roots), and
appends them only on a confirmed answer — mirroring the gate-command
ignore-check in offer (a). A decline records `gitignore.handoffs_declined`.
Pinned by token, not prose (the style of
`test_consumer_offers_gitignore.py`).
"""
from __future__ import annotations

from pathlib import Path

_SHARED = Path(__file__).resolve().parent

OFFERS_CHECK = 'python3 "$TP_ROOT"/skills/_shared/handoffs_ignore.py check'


def _offer_c() -> str:
    text = (_SHARED / "consumer-offers.md").read_text(encoding="utf-8")
    start = text.index("## Offer (c)")
    end = text.index("## Enforcer", start)
    return text[start:end]


def test_offer_c_names_the_shipped_check_command():
    body = _offer_c()
    for token in (
        OFFERS_CHECK,
        "handoffs_ignore.py apply",
        "three-pillars-docs/tp-designs/*/.handoffs/*",
        "three-pillars-docs/completed-tp-designs/*/.handoffs/*",
        "confirmed",
        "never",
        "--auto",
    ):
        assert token in body, token


def test_offer_c_decline_records_the_config_key():
    body = _offer_c()
    assert "gitignore.handoffs_declined" in body
    assert "repo_config_load.py set" in body


def test_first_run_routes_offer_c():
    text = (_SHARED / "first-run.md").read_text(encoding="utf-8")
    section = text[text.index("## Consumer offers"):text.index("## Old-layout detection")]
    assert "Offer (c)" in section
    assert "consumer-offers.md" in section


def test_repo_config_documents_the_decline_key():
    text = (_SHARED / "repo-config.md").read_text(encoding="utf-8")
    assert "gitignore.handoffs_declined" in text


def test_decline_write_is_accepted_by_the_config_schema(tmp_path):
    # The offer's decline runs `repo_config_load.py set
    # gitignore.handoffs_declined true`. The shipped schema must accept the
    # key: a rejected write raises, and a pruned key would re-ask every run.
    import sys

    sys.path.insert(0, str(_SHARED))
    import repo_config_load as rcl

    rcl.update_config(tmp_path, "gitignore.handoffs_declined", True)
    loaded = rcl.load_repo_config(tmp_path)
    assert loaded.config.get("gitignore") == {"handoffs_declined": True}
    assert not loaded.warnings


def test_first_run_condition_8_settles_only_when_offer_c_settled():
    # PR #177 r1: condition 8's cheap-path predicate omitted offer (c), so a
    # repo with gate_command + commit_guard settled returned on the hot path
    # and was never offered the .handoffs/ rule. It must require the rule
    # present (the shipped check) or declined, and route the failure.
    text = (_SHARED / "first-run.md").read_text(encoding="utf-8")
    cond8 = next(line for line in text.splitlines()
                 if line.startswith("8. **Consumer offers are settled**"))
    assert "gitignore.handoffs_declined" in cond8
    assert OFFERS_CHECK in cond8
    routing = next(line for line in text.splitlines()
                   if line.startswith("If any condition fails"))
    route8 = routing[routing.index("condition 8 failing"):]
    assert "offer (c)" in route8 and "Consumer offers" in route8
