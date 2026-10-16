"""A cheap (sonnet) finder round has the same shape as the local round (one-cheap-engine 3.1)."""
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import finder_round  # noqa: E402

ANGLES = [{"name": n, "role": "confirmer", "model": "opus", "prompt": f"look at {n}"}
          for n in ("correctness", "security", "perf")]
RULINGS = "/x/rulings.md"
CFG = {"review": {"angles": ANGLES}}


def test_sonnet_round_has_sonnet_finders_and_opus_check():
    got = finder_round.round_angles(CFG, root=".", rulings_path=RULINGS)
    assert len(got) == len(ANGLES) + 1
    for a, src in zip(got, ANGLES):
        assert a["name"] == src["name"]
        assert (a["role"], a["model"], a["advisory"]) == ("finder", "sonnet", True)
        assert RULINGS in a["prompt"]
    check = got[-1]
    assert check["name"] == finder_round.CHECK_NAME
    assert check["model"] == "opus"


def test_sonnet_round_without_rulings_raises():
    with pytest.raises(ValueError, match="rulings"):
        finder_round.round_angles(CFG, root=".")


def test_check_prompt_names_capped():
    assert "capped" in finder_round.check_angle(RULINGS)["prompt"]


def test_only_check_is_non_advisory():
    got = finder_round.round_angles(CFG, root=".", rulings_path=RULINGS)
    assert [a["name"] for a in got if not a.get("advisory")] == [finder_round.CHECK_NAME]
