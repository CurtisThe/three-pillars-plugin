"""Tests for the `cheap` model source in model_policy (design: one-cheap-engine, Task 2.1)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_classes  # noqa: E402
import model_policy as mp  # noqa: E402

JUDGMENT_AGENTS = [n for n in mp.AGENTS
                   if not any(c in n for c in "*?[") and cheap_classes.klass(n) == "judgment"]


def test_council_row_uses_cheap_source():
    assert mp.AGENTS["council-*"] == ("audit-member", "cheap", "high")


def test_council_member_is_sonnet_without_local():
    assert mp.agent_spec("council-ada") == {
        "role": "audit-member", "model": "sonnet", "effort": "high"}


def test_council_member_is_local_with_local_cfg():
    cfg = {"model": "claude-haiku-4-5", "fallback_model": "sonnet"}
    assert mp.agent_spec("council-ada", None, cfg)["model"] == "haiku"


@pytest.mark.parametrize("name", JUDGMENT_AGENTS)
def test_judgment_agents_stay_opus(name):
    assert mp.agent_spec(name)["model"] in ("opus", "fable")


def test_file_within_pin():
    lines = Path(mp.__file__).read_text(encoding="utf-8").count("\n")
    assert lines <= 301
