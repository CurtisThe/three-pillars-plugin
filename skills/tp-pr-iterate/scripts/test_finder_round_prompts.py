"""finder_round.check_angle prompt text (review-convergence 1.5)."""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import finder_round  # noqa: E402

RULINGS = "/x/rulings.md"


def test_check_prompt_says_blocking_is_final():
    p = finder_round.check_angle(RULINGS)["prompt"]
    assert ("Your `blocking` is final: a finding you mark `downgraded` "
            "never blocks") in p


def test_check_prompt_final_sentence_is_complete():
    p = finder_round.check_angle(RULINGS)["prompt"]
    assert ("Your `blocking` is final: a finding you mark `downgraded` "
            "never blocks, whatever its reproducer does.") in p
