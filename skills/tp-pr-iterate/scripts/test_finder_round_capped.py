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


# finder-cap-coverage 1.8: a `capped` telemetry outcome left nothing — the check
# re-covers it exactly like an `unparseable` segment. Code-tied tokens only.
def test_check_prompt_re_covers_a_capped_segment_like_an_unparseable_one(tmp_path):
    flat = _flat_prompt(tmp_path)
    sentences = [s for s in flat.split(". ")
                 if "`capped`" in s and "unparseable" in s]
    assert len(sentences) == 1


def test_check_prompt_says_a_partial_covers_only_its_progress_files(tmp_path):
    flat = _flat_prompt(tmp_path)
    sentences = [s for s in flat.split(". ")
                 if "`partial`" in s and "progress" in s]
    assert len(sentences) == 1
