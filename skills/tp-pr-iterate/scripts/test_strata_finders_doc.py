"""strata-finders.md states the one review path on Strata (local-role-routing 6.8)."""
from __future__ import annotations

import re
from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / "strata-finders.md"

REQUIRED = (
    "role_engine.py resolve review_finder",
    "role_engine.py resolve context_scout",
    "context_scout.py prompt",
    "tp-review-confirmer",
    "context_scout.py put",
    "rulings.json",
    "proof_root.py",
    "context_scout.py needs-refresh",
    "scout unavailable: slot-lost",
    "round_scratch.py prepare",
    "--scope",
    "--rulings",
    "strata-spawn.md",
    "finder_round.py mark-unparseable",
    "opus-check",
    "reproduce.py",
    "escape_ledger.py append-review",
    "converge.py --round-dir",
)


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_doc_contains_each_required_item():
    text = _text()
    missing = [r for r in REQUIRED if r not in text]
    assert missing == []


def test_scout_spawn_takes_model_from_context_scout_resolve():
    text = _text()
    spawn = re.search(r"Agent\([^)]*tp-review-confirmer[^)]*\)", text, re.S)
    assert spawn and "context_scout" in text[max(0, spawn.start() - 600) : spawn.end() + 300]


def test_omitted_scope_runs_every_angle():
    text = _text()
    assert re.search(r"omit[^\n]*--scope[^\n]*every angle|--scope[^\n]*omit[^\n]*every angle",
                     text, re.I)
    assert "scoped re-review" in text


def test_mark_unparseable_precedes_opus_check_step():
    text = _text()
    assert text.index("finder_round.py mark-unparseable") < text.index("opus-check")


def test_unparseable_order_is_stated():
    text = _text().lower()
    for needle in ("unparseable", "respawns remain", "exhaustion", "re-covered by the opus check",
                   "served-by fallback", "strata_spawn.busy", "accepted"):
        assert needle in text, needle


def _section(text: str, head: str) -> str:
    start = text.index(head)
    nxt = text.find("\n## ", start + 1)
    return text[start : nxt if nxt != -1 else len(text)]


def test_spawns_use_the_manifest_entry_fields_not_angle_names():
    text = _text()
    assert not re.search(r'agent_ref\("<[^">]*>"\)', text)
    check = _section(text, "## The Opus check")
    assert 'agent_ref("tp-review-confirmer")' not in check
    assert re.search(r"Agent\([^)]*agent_ref[^)]*\)", check, re.S)
    serial = _section(text, "## Serial finders")
    assert "agent_ref" in serial and "dispatch_model" in serial
    assert "prompt" in serial


def test_mark_busy_between_decide_and_opus_check_step():
    text = _text()
    assert "finder_round.py mark-busy" in text
    serial = _section(text, "## Serial finders")
    assert serial.index("decide") < serial.index("mark-busy")
    assert text.index("finder_round.py mark-busy") < text.index("## The Opus check")


def test_decisions_flag_on_both_resolves_and_ledger_staged():
    text = _text()
    for role in ("review_finder", "context_scout"):
        assert re.search(rf"role_engine\.py resolve {role}\s+--decisions", text), role
    tail = _section(text, "## Tail")
    assert tail.index("append-review") < tail.index("escape-ledger.ndjson")
