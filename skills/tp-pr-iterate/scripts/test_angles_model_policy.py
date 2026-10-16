"""Tests for angles.py M3/Q5 — the review floor, `fable` a Claude tier, local skip.

design: consumer-repo-parity (Task 7.4)

`tier()` calls every `model_policy.AGENT_ALIASES` member `claude` (so `fable` is a
Claude tier); `_validate` applies the review floor (`models.review` sets the
minimum, `opus` always passes); a local finder is skipped when the local backend
is absent and the digest renders the skip. Stdlib only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import angles  # noqa: E402


def _angle(name="a", role="confirmer", model="opus", prompt="look"):
    return {"name": name, "prompt": prompt, "role": role, "model": model}


def _cfg(*entries):
    return {"review": {"angles": list(entries)}}


# --- tier: every Agent alias is a Claude tier -------------------------------

@pytest.mark.parametrize("model", [
    "opus", "sonnet", "haiku", "fable",
    "claude-opus-4-1", "claude-sonnet-4-6", "Opus", "Claude-Haiku-4-5",
])
def test_tier_every_alias_is_claude(model):
    assert angles.tier({"model": model}) == "claude"


def test_tier_claude_family_not_an_alias_is_local():
    assert angles.tier({"model": "claude-3-opus-20240229"}) == "local"


def test_tier_local_model_is_local():
    assert angles.tier({"model": "qwen-coder"}) == "local"


# --- the review floor: models.review sets the minimum, opus always passes ---

def test_default_angles_opus_when_review_unset():
    got = angles.load_angles(None)
    assert all(a["model"] == "opus" and a["role"] == "confirmer" for a in got)


def test_default_angles_follow_models_review_fable():
    got = angles.load_angles({"models": {"review": "fable"}})
    assert all(a["model"] == "fable" and a["role"] == "confirmer" for a in got)


def test_review_sonnet_allows_declared_sonnet():
    got = angles.load_angles({"models": {"review": "sonnet"},
                              "review": {"angles": [_angle(model="sonnet")]}})
    assert got[0]["model"] == "sonnet"


def test_default_config_rejects_declared_sonnet_confirmer():
    with pytest.raises(ValueError):
        angles.load_angles(_cfg(_angle(model="sonnet")))


def test_default_config_rejects_declared_haiku_finder():
    with pytest.raises(ValueError):
        angles.load_angles(_cfg(_angle(role="finder", model="haiku")))


def test_default_config_accepts_claude_opus_id():
    got = angles.load_angles(_cfg(_angle(model="claude-opus-4-1")))
    assert got[0]["model"] == "claude-opus-4-1"


def test_review_fable_accepts_declared_opus():
    got = angles.load_angles({"models": {"review": "fable"},
                              "review": {"angles": [_angle(model="opus")]}})
    assert got[0]["model"] == "opus"


def test_one_m_suffixed_opus_is_a_claude_angle_never_skipped(monkeypatch):
    """`opus[1m]` maps to `opus` via agent_alias: a Claude tier, dispatched
    as `opus`, never classified local and skipped when the backend is absent."""
    monkeypatch.setattr(angles.local_backend, "available", lambda **k: False)
    assert angles.tier({"model": "opus[1m]"}) == "claude"
    assert angles.tier({"model": "claude-opus-4-8[1m]"}) == "claude"
    got = angles.load_angles(_cfg(_angle(role="finder", model="opus[1m]")))
    assert "skipped" not in got[0] and got[0]["model"] == "opus[1m]"


def test_unrecognised_claude_id_is_local_and_refused():
    assert angles.tier({"model": "claude-3-opus-20240229"}) == "local"
    with pytest.raises(ValueError):
        angles.load_angles(_cfg(_angle(model="claude-3-opus-20240229")))


# --- a local finder is skipped when the local backend is absent -------------

def test_local_finder_skipped_when_backend_absent(monkeypatch):
    monkeypatch.setattr(angles.local_backend, "available", lambda **k: False)
    got = angles.load_angles(_cfg(_angle(role="finder", model="local-llm")))
    assert got[0]["skipped"] == "local backend absent"
    assert got[0]["role"] == "finder"  # kept in the list, not dropped


def test_local_finder_not_skipped_when_backend_present(monkeypatch):
    monkeypatch.setattr(angles.local_backend, "available", lambda **k: True)
    got = angles.load_angles(_cfg(_angle(role="finder", model="local-llm")))
    assert "skipped" not in got[0]


def test_claude_finder_never_skipped(monkeypatch):
    monkeypatch.setattr(angles.local_backend, "available", lambda **k: False)
    got = angles.load_angles(_cfg(_angle(role="finder", model="opus")))
    assert "skipped" not in got[0]


def test_digest_labels_renders_skipped():
    m = {"angles": [{"name": "scan", "role": "finder", "model": "local-llm",
                     "skipped": "local backend absent"}]}
    label, count = angles.digest_labels(m, {"scan": 0})[0]
    assert label.endswith("[skipped: no local backend]")
    assert count == 0
