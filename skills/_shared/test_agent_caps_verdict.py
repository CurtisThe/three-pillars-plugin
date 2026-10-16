"""Tests for agent_caps.py -- per-role cap table and cap verdict.

design: one-cheap-engine (Task 1.4).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_caps  # noqa: E402
import cheap_classes  # noqa: E402

TASK_SLOT = {"task", "tp-task-worker", "tp-task-worker-*"}


def test_finder_and_member_numbers():
    for role in ("review_finder", "council_member"):
        c = agent_caps.CAPS[role]
        assert (c.soft_s, c.soft_tokens) == (900, 150_000)
        assert (c.hard_s, c.hard_tokens) == (1500, 250_000)


def test_wrap_up_once_then_ok():
    v = agent_caps.verdict
    assert v("review_finder", 10, 10, False) == "ok"
    assert v("review_finder", 900, 10, False) == "wrap-up"
    assert v("review_finder", 10, 150_000, False) == "wrap-up"
    assert v("review_finder", 899, 149_999, False) == "ok"
    assert v("review_finder", 1000, 10, True) == "ok"


def test_stop_past_hard_on_either_axis():
    v = agent_caps.verdict
    assert v("council_member", 1500, 0, True) == "stop"
    assert v("council_member", 0, 250_000, False) == "stop"
    assert v("council_member", 1499, 249_999, True) == "ok"


def test_task_worker_has_no_cap_row():
    for name in ("task", "tp-task-worker", "tp-task-worker-sonnet-medium",
                 "tp-finalizer", "council-synth"):
        with pytest.raises(KeyError):
            agent_caps.cap_for(name)
    with pytest.raises(KeyError):
        agent_caps.verdict("tp-task-worker", 1, 1, False)


def test_every_cheap_role_but_task_has_a_row():
    for site in cheap_classes.cheap_sites() - TASK_SLOT:
        assert site in agent_caps.CAPS, site
    assert not TASK_SLOT & set(agent_caps.CAPS)
    assert agent_caps.cap_for("council-ada") is agent_caps.CAPS["council-*"]


def test_scale_shrinks_the_span_axis_only():
    v = agent_caps.verdict
    assert v("review_finder", 300, 10, False, 0.25) == "wrap-up"  # soft 900 s * 0.25 = 225 s
    assert v("review_finder", 300, 10, True, 0.25) == "ok"        # hard 1500 s * 0.25 = 375 s
    assert v("review_finder", 300, 10, False, 0.2) == "stop"      # hard 1500 s * 0.2 = 300 s
    assert v("review_finder", 300, 10, False, 1.0) == "ok"
    assert v("review_finder", 300, 260_000, False, 1.0) == "stop"  # tokens unscaled
