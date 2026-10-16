"""test_consumer_offers_gitignore.py — the gate-command offer checks ignore rules
(impl-audit finding F2, consumer-repo-parity).

A gate command that leaves un-ignored output (`__pycache__/`) makes the next run
start dirty and refuse the stamp, so offer (a) must check `.gitignore` for the
command's output and offer the missing rules as part of the CONFIRMED answer —
never a silent `.gitignore` edit. Pinned by token, not prose.
"""
from __future__ import annotations

from pathlib import Path

_SHARED = Path(__file__).resolve().parent


def _offer_a() -> str:
    text = (_SHARED / "consumer-offers.md").read_text(encoding="utf-8")
    start = text.index("## Offer (a)")
    return text[start:text.index("## Offer (b)")]


def test_offer_a_checks_ignore_rules_for_the_command_output():
    body = _offer_a()
    for token in (".gitignore", "__pycache__/", ".pytest_cache/", "build/",
                  "git check-ignore", "confirmed", "never"):
        assert token in body, token


def test_first_run_routes_the_ignore_check_to_offer_a():
    text = (_SHARED / "first-run.md").read_text(encoding="utf-8")
    section = text[text.index("## Consumer offers"):text.index("## Old-layout detection")]
    assert ".gitignore" in section and "__pycache__/" in section
    assert "confirmed" in section and "consumer-offers.md" in section
