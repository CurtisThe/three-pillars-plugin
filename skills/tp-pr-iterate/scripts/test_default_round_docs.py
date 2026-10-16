"""one-cheap-engine impl-audit-1 B1: the documented default round is the cheap-finder flow.

With no flag the review finders resolve to Sonnet, so `finder_round.round_angles` needs a rulings
file. Each doc that runs a round must therefore run the context scout first, pass an unbracketed
`--rulings` on every `round_scratch.py prepare`, and dispatch the `opus-check` angle after every
finder. Slices are cut by heading or list marker, never by line number.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

import skill_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
SKILL = "skills/tp-pr-iterate/SKILL.md"
TOPOLOGY = "skills/tp-pr-iterate/round-topology.md"
TIER7 = "skills/tp-run-full-design/SKILL.md"
RULINGS = "--rulings <proof_root>/rounds/<pr>/rulings.md"


def _text(rel: str) -> str:
    if rel == TIER7:
        return " ".join(skill_text.read_skill_text("tp-run-full-design").split())
    return " ".join((ROOT / rel).read_text(encoding="utf-8").split())


def _slice(rel: str, start: str, end: str | None) -> str:
    text = _text(rel)
    i = text.index(start)
    return text[i:text.index(end, i)] if end else text[i:]


def _round_docs() -> dict:
    return {
        SKILL: _slice(SKILL, "2.5. **Dual-source", "- **Multi-angle, not single-pass.**"),
        TOPOLOGY: _slice(TOPOLOGY, "## One round", "## Reproducer outcomes"),
        TIER7: _slice(TIER7, "## Tier 7 — PR-iterate", "### Step 2 — Clip"),
    }


def _prepare_commands(text: str) -> list:
    out = []
    for m in re.finditer(r"round_scratch\.py prepare", text):
        window = text[m.start():m.start() + 500]
        if "writes them into" in window[:60]:
            continue
        out.append((m.start(), window))
    return out


def test_every_prepare_passes_an_unbracketed_rulings():
    for rel, text in _round_docs().items():
        cmds = _prepare_commands(text)
        assert cmds, rel
        for _, window in cmds:
            assert RULINGS in window, (rel, window[:200])
            assert "[--rulings" not in window, (rel, window[:200])


def test_scout_step_comes_before_round_one():
    for rel, text in _round_docs().items():
        scout = text.find("§Context scout")
        first = _prepare_commands(text)[0][0]
        assert scout != -1 and scout < first, rel
        assert "needs-refresh" in text, rel


def test_check_angle_dispatched_after_the_finders():
    for rel, text in _round_docs().items():
        assert "opus-check" in text, rel
        assert re.search(r"after every finder[^.]*reply\.md", text), rel
        assert "on the cheap engine" in text.lower(), rel
        assert "Sonnet in parallel" in text and "Strata one at a time" in text, rel


def test_no_review_finder_local_conditionals():
    for rel in (SKILL, TOPOLOGY, TIER7):
        assert "review_finder=local" not in _text(rel), rel
