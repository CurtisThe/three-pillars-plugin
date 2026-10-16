"""review-log-survives-teardown Task 2.4: the two-stable log flush is committed AND pushed.

Doc pins at block level (skills/_shared/test-fragility.md): each test reads one named section,
sentence or line, not whole-file keywords, so a stray mention elsewhere cannot satisfy it.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOPOLOGY = ROOT / "skills" / "tp-pr-iterate" / "round-topology.md"
SKILL = ROOT / "skills" / "tp-pr-iterate" / "SKILL.md"
PROOF = ROOT / "skills" / "tp-pr-iterate" / "proof-of-review.md"
LOG_NAMES = ("decisions.md", "dispatch-telemetry.ndjson", "escape-ledger.ndjson")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(path: Path, start: str, end: str) -> str:
    text = path.read_text(encoding="utf-8")
    i = text.index(start)
    return _flat(text[i:text.index(end, i)])


def _missing(text: str, *needles: str) -> list[str]:
    return [n for n in needles if n not in text]


def test_round_topology_flush_pushes():
    flush = _section(TOPOLOGY, "## Log flush", "## Budget terminals and recovery")
    assert not _missing(flush, "committed and pushed only at `two-stable`", "round_log_carry.py",
                        "completed-tp-designs/<slug>/decisions.md", "is_round_log_commit",
                        *LOG_NAMES)
    assert "**not pushed**" not in flush
    assert "exception to commit-then-push" not in flush


def test_pr_iterate_skill_flush_line_pushes():
    lines = [ln for ln in SKILL.read_text(encoding="utf-8").splitlines()
             if "round_scratch.py flush" in ln]
    assert lines, "no SKILL.md line names round_scratch.py flush"
    line = _flat(lines[0])
    assert "committed and pushed" in line and "round_log_carry" in line
    assert "never pushed" not in line


def test_proof_of_review_names_the_round_log_exception():
    para = _section(PROOF, "**last head-binding action**", "This is the correct ordering")
    assert "no commit" in para
    assert not _missing(para, "round-log commit", "round_log_carry")
