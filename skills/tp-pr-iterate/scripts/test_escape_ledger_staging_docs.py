"""Task 6.12: the Tier 7 flush and design-complete stage escape-ledger.ndjson
alongside dispatch-telemetry.ndjson (block-level prose-structure assertions,
per skills/_shared/test-fragility.md: not exact wording)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOPOLOGY = ROOT / "skills" / "tp-pr-iterate" / "round-topology.md"
COMPLETE = ROOT / "skills" / "tp-design-complete" / "SKILL.md"
TELEMETRY = "dispatch-telemetry.ndjson"
LEDGER = "escape-ledger.ndjson"


def _blocks(path):
    return re.split(r"\n\s*\n", path.read_text(encoding="utf-8"))


def test_two_stable_flush_stages_escape_ledger():
    hits = [b for b in _blocks(TOPOLOGY) if TELEMETRY in b and "two-stable" in b]
    assert hits, "no two-stable flush paragraph names dispatch telemetry"
    assert any(LEDGER in b for b in hits)


def test_design_complete_add_block_stages_escape_ledger():
    hits = [b for b in _blocks(COMPLETE) if "git add" in b and TELEMETRY in b]
    assert hits, "no git add block stages dispatch telemetry"
    assert any(LEDGER in b for b in hits)
