"""proof-carry-trivial-commits Task 1.7: docs name the proof-neutral class beside the round-log exception.

Block-level doc pins (skills/_shared/test-fragility.md): code-owned identifiers only,
read from one named paragraph or line.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROOF = ROOT / "skills" / "tp-pr-iterate" / "proof-of-review.md"
TIER7 = ROOT / "skills" / "tp-run-full-design" / "tier-7-review.md"


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(path: Path, start: str, end: str) -> str:
    text = path.read_text(encoding="utf-8")
    i = text.index(start)
    return _flat(text[i:text.index(end, i)])


def _missing(text: str, *needles: str) -> list[str]:
    return [n for n in needles if n not in text]


def test_head_binding_paragraph_names_neutral_class_and_keeps_round_log():
    para = _section(PROOF, "**last head-binding action**", "This is the correct ordering")
    assert not _missing(para, "proof_neutral_carry.py", "review.proof_neutral_carry")
    assert not _missing(para, "round-log commit", "round_log_carry", "no commit")


def test_tier7_neutral_line_names_carry_check():
    lines = [ln for ln in TIER7.read_text(encoding="utf-8").splitlines()
             if "proof_neutral_carry" in ln]
    assert len(lines) == 1, lines
    assert "carry_check.py" in lines[0]
