"""Task 6.4: cheap-tier.md Tier 1 runs the router archiver, fail-open."""
import hashlib
from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / "tp-run-full-design" / "cheap-tier.md"
LINE = 'python3 "$TP_ROOT"/skills/_shared/router_archive.py archive'
REACH_SHA = "54594019330982346df8dc8b7cf3d718a99efc7afb24c53062a15f4e19f7591a"


def _section(text, heading):
    start = text.index(heading)
    nxt = text.find("\n## ", start + 1)
    return text[start:] if nxt == -1 else text[start:nxt]


def test_tier1_has_one_archive_line_nowhere_else():
    text = DOC.read_text(encoding="utf-8")
    tier1 = _section(text, "## Tier 1 ")
    assert tier1.count(LINE) == 1
    assert text.count(LINE) == 1


def test_archive_line_is_marked_fail_open():
    tier1 = _section(DOC.read_text(encoding="utf-8"), "## Tier 1 ")
    block = [ln for ln in tier1.splitlines() if "router_archive.py" in ln]
    assert len(block) == 1
    i = tier1.index(block[0])
    window = tier1[max(0, i - 400): i + 600].lower()
    assert "fail-open" in window
    assert "never gat" in window


def test_reach_section_untouched():
    reach = DOC.read_text(encoding="utf-8")
    reach = reach[reach.index("## Reach"):]
    assert hashlib.sha256(reach.encode()).hexdigest() == REACH_SHA
