"""The Opus check treats a capped finder reply as unchecked (review-convergence 7.5)."""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import finder_round  # noqa: E402

UNCHECKED = "treat what they did not check as unchecked"


def _flat_prompt(tmp_path):
    rulings = tmp_path / "rulings.md"
    rulings.write_text("# rulings\n", encoding="utf-8")
    return " ".join(finder_round.check_angle(str(rulings))["prompt"].split())


def test_check_prompt_says_to_treat_uncovered_as_unchecked(tmp_path):
    assert UNCHECKED in _flat_prompt(tmp_path)


def test_the_uncapped_hint_sits_in_the_sentence_about_a_capped_reply(tmp_path):
    flat = _flat_prompt(tmp_path)
    sentences = [s for s in flat.split(". ") if UNCHECKED in s]
    assert len(sentences) == 1
    assert "capped" in sentences[0]
