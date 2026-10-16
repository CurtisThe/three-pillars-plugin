"""test_ladder_split.py — Task 2.4: tier_ladder split is a pure move with re-exports."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ladder_entry  # noqa: E402
import ladder_rungs  # noqa: E402
import model_policy  # noqa: E402
import tier_ladder  # noqa: E402


def test_rung_names_reexported():
    for name in ("route_floor", "effective_model", "display", "LADDER", "SAFE_CLAUDE"):
        assert getattr(tier_ladder, name) is getattr(ladder_rungs, name)


def test_entry_names_reexported():
    for name in ("to_decision_entry", "to_telemetry", "MISSING"):
        assert getattr(tier_ladder, name) is getattr(ladder_entry, name)


def test_model_for_delegates():
    cfg = {"model": "qwen", "fallback_model": "sonnet"}
    for tier in tier_ladder.LADDER:
        assert tier_ladder.model_for(tier, cfg) == model_policy.rung_model(tier, cfg)


def test_tier_ladder_size():
    lines = Path(tier_ladder.__file__).read_text(encoding="utf-8").count("\n")
    assert lines <= 385  # red-commit-hook-refusal Task 1.4: hook-refused branch +≈20 lines (was ≤ 362: launch-role-precedence Task 2.2, originally ≤ 360 per cheap-tier-local-routing Task 2.3); further growth goes in a new module
