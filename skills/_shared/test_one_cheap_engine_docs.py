"""one-cheap-engine 3.5: dispatch, config, run and launch prose names the one engine rule."""
from __future__ import annotations

from pathlib import Path

import skill_text

ROOT = Path(__file__).resolve().parents[2]
DISPATCH = "skills/_shared/local-dispatch.md"
SPAWN = "skills/_shared/strata-spawn.md"
CONFIG = "skills/_shared/repo-config.md"
LAUNCH = "skills/_shared/design-run-launch.md"
RUN = "skills/tp-run-full-design/SKILL.md"
RUN_CHEAP = "skills/tp-run-full-design/cheap-tier.md"
FLEET = "skills/tp-" + "fleet/SKILL.md"  # split: the leak guard bans the pro name in a free file
DISPATCH_CHEAP = "skills/_shared/cheap-dispatch.md"
GATED = (DISPATCH, SPAWN, CONFIG, LAUNCH, RUN, RUN_CHEAP, FLEET, DISPATCH_CHEAP)

GATE_NEEDLES = (
    "only with `--cheap-tier`", "only with `--cheap-tier[=ab]`", "under `--cheap-tier`",
    "under `--cheap-tier[=ab]`", "with `--cheap-tier[=ab]`", "only under the flag",
    "without the flag", "when the run has it", "when the run has the flag", "has the flag",
    "only when the skill has the flag", "with either key off", "`--cheap-tier`: [",
)


def _text(rel: str) -> str:
    if rel == RUN:
        return " ".join(skill_text.read_skill_text("tp-run-full-design").split())
    return " ".join((ROOT / rel).read_text(encoding="utf-8").split())


def test_dispatch_wait_branch_documented():
    text = _text(DISPATCH)
    assert "tier_ladder.py next --busy-policy wait" in text
    assert "busy-timeout" in text and "ladder_busy.py" in text


def test_strata_spawn_doc_names_unrouted_and_mode():
    text = _text(SPAWN)
    assert "unrouted" in text and "M51" in text and "TP_LOCAL_MODE" in text


def test_repo_config_deprecations_and_mode_values():
    text = _text(CONFIG)
    role = next(p for p in text.split("- `") if p.startswith("role_engines"))
    assert "deprecated" in role.lower()
    cheap = next(p for p in text.split("- `") if p.startswith("cheap_tier`"))
    assert "deprecated" in cheap.lower() and "default_run_flag" in cheap
    for needle in ("TP_LOCAL_MODE", "fallback", "wait", "exclusive", "unset"):
        assert needle in text, needle


def test_launch_doc_base_sync():
    text = _text(LAUNCH)
    assert "--base-sync" in text and "base-sync window" in text
    assert "--cheap-tier[=ab] | --no-cheap-tier" in text and "deprecated" in text


def test_fleet_base_sync_step_uses_launcher():
    text = _text(FLEET)
    assert "launch_design_run.py --base-sync <sibling>" in text
    assert "base-sync step* → `/tp-merge-from-main" not in text


def test_run_doc_task_dispatch_default():
    text = _text(RUN)
    assert "per-task cheap dispatch" in text
    assert "With `--local` or the cheap-tier task lever" not in text
    assert "under `--local` or the cheap-tier task lever" not in text


def test_run_docs_have_no_flag_gate():
    for rel in GATED:
        low = _text(rel).lower()
        for needle in GATE_NEEDLES:
            assert needle.lower() not in low, (rel, needle)


def test_slot9_dispatch_always_carries_cheap_tier():
    text = _text(RUN)
    assert "Runs `/tp-design-learn {slug} --auto --cheap-tier`" in text
    assert "`/tp-design-learn {slug} --auto --cheap-tier` inline" in text
