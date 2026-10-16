"""one-cheap-engine 3.4: review, council and classifier prose names the cheap engine."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FINDERS = "skills/tp-pr-iterate/strata-finders.md"
TOPOLOGY = "skills/tp-pr-iterate/round-topology.md"
CHEAP = "skills/tp-pr-iterate/cheap-tier.md"
SKILL = "skills/tp-pr-iterate/SKILL.md"
MEMBERS = "skills/council/strata-members.md"
FILES = (FINDERS, TOPOLOGY, CHEAP, SKILL, MEMBERS)

GATE_NEEDLES = (
    "only with `--cheap-tier`", "only with `--cheap-tier[=ab]`", "under `--cheap-tier`",
    "under `--cheap-tier[=ab]`", "with `--cheap-tier[=ab]`", "only under the flag",
    "without the flag", "when the run has it", "when the run has the flag", "has the flag",
)


def _text(rel: str) -> str:
    return " ".join((ROOT / rel).read_text(encoding="utf-8").split())


def test_prepare_commands_pass_rulings():
    for rel in (FINDERS, SKILL, TOPOLOGY):
        text = _text(rel)
        hits = [m.start() for m in re.finditer(r"round_scratch\.py prepare", text)]
        assert hits, rel
        for i in hits:
            window = text[i:i + 400]
            if "writes them into" in window[:60]:
                continue  # prose about the manifest, not a command
            assert "--rulings" in window, (rel, window[:120])


def test_finder_and_member_docs_name_caps():
    for rel in (FINDERS, MEMBERS):
        text = _text(rel)
        for needle in ("Sonnet", "--local", "agent_caps.py check", "soft-cap", "SendMessage",
                       "TaskStop", "put-capped", "strata_spawn.py release", "kept: null",
                       "escape_ledger"):
            assert needle in text, (rel, needle)
        assert "busy" in text.lower()


def test_resolve_calls_pass_local():
    for rel in (FINDERS, MEMBERS):
        text = _text(rel)
        calls = re.findall(r"role_engine\.py resolve \S+[^`]*", text)
        assert calls, rel
        for call in calls:
            assert "--local" in call, (rel, call)


def test_classifier_site_asks_cheap_engine():
    text = _text(SKILL)
    assert "cheap_engine.py resolve pr_classifier" in text
    assert "classifier_gate" in text
    assert "deprecated" in text


def test_no_role_engines_opus_default():
    for rel in FILES:
        low = _text(rel).lower()
        assert not re.search(r"role_engines[^.]{0,60}default[^.]{0,20}opus", low), rel
        assert "engine` is `opus`" not in low, rel


def test_no_flag_gate_left():
    for rel in FILES:
        low = _text(rel).lower()
        for needle in GATE_NEEDLES:
            assert needle.lower() not in low, (rel, needle)
