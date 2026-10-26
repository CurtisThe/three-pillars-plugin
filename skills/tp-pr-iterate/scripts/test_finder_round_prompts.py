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


# finder-cap-coverage 1.8: the check is told how a retried parent, a `partial` reply
# and a `capped` outcome read. Code-tied tokens only — no sentence is pinned.
def test_check_prompt_says_a_retried_entry_was_split_into_two_halves():
    p = finder_round.check_angle(RULINGS)["prompt"]
    assert "<name>a" in p and "<name>b" in p


def test_check_prompt_uses_the_retry_outcome_tokens():
    import finder_retry

    p = finder_round.check_angle(RULINGS)["prompt"]
    for token in ("retried", "partial", "capped"):
        assert token in finder_retry.OUTCOMES
        assert f"`{token}`" in p
