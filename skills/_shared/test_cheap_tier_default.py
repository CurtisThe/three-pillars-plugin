"""test_cheap_tier_default.py — pure resolver behavior (no filesystem).

design: cheap-tier-default-flag-everywhere
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cheap_tier_default  # noqa: E402
import design_run_command  # noqa: E402


def _names(notes):
    """Each note's subject: the `deprecated: <switch>` head, a `warning:` line whole."""
    return [n.split(" is deprecated", 1)[0] for n in notes]


def test_default_mode_is_on_for_every_value():
    # The cheap tier is always on; `cheap_tier.default_run_flag` changes nothing.
    for cfg in (None, {}, {"cheap_tier": None}, {"cheap_tier": {}},
                {"cheap_tier": {"default_run_flag": "ab"}},
                {"cheap_tier": {"default_run_flag": "on"}},
                {"cheap_tier": {"default_run_flag": "off"}},
                {"cheap_tier": {"default_run_flag": "x"}},
                {"cheap_tier": {"default_run_flag": True}}, {"models": {"handoff": "x"}}):
        assert cheap_tier_default.default_mode(cfg) == "on"


def test_modes_match_the_launcher():
    assert cheap_tier_default.MODES == design_run_command.CHEAP_TIER_MODES


def test_is_drop_warning_matches_the_block_or_its_keys():
    assert cheap_tier_default.is_drop_warning("config: dropped cheap_tier (type 'object')")
    assert cheap_tier_default.is_drop_warning(
        "config: dropped cheap_tier.default_run_flag (not in ['on', 'ab'])")
    assert not cheap_tier_default.is_drop_warning("config: dropped cheap_tier_x (unknown key)")
    assert not cheap_tier_default.is_drop_warning("config: dropped models.task (type 'string')")


def test_resolve_unset_is_on():
    assert cheap_tier_default.resolve({}, []) == ("on", [])


def test_resolve_explicit_off_is_on():
    cfg = {"cheap_tier": {"default_run_flag": "off"}}
    mode, notes = cheap_tier_default.resolve(cfg, [])
    assert mode == "on" and _names(notes) == ["deprecated: cheap_tier.default_run_flag"]


def test_resolve_default_ab_is_on():
    mode, notes = cheap_tier_default.resolve({"cheap_tier": {"default_run_flag": "ab"}}, [])
    assert mode == "on" and _names(notes) == ["deprecated: cheap_tier.default_run_flag"]


def test_resolve_explicit_flags_change_nothing():
    cfg = {"cheap_tier": {"default_run_flag": "ab"}}
    mode, notes = cheap_tier_default.resolve(cfg, [], cheap_tier="on")
    assert mode == "on"
    assert _names(notes) == ["deprecated: --cheap-tier", "deprecated: cheap_tier.default_run_flag"]
    mode, notes = cheap_tier_default.resolve(cfg, [], no_cheap_tier=True)
    assert mode == "on"
    assert _names(notes) == ["deprecated: --no-cheap-tier",
                             "deprecated: cheap_tier.default_run_flag"]
    mode, notes = cheap_tier_default.resolve({}, [], cheap_tier="ab")
    assert (mode, _names(notes)) == ("on", ["deprecated: --cheap-tier=ab"])


def test_resolve_dropped_block_warns_then_resolves_on():
    warnings = ["config: dropped cheap_tier.default_run_flag (x)", "config: dropped models.task (y)"]
    assert cheap_tier_default.resolve({}, warnings) == (
        "on", ["warning: config: dropped cheap_tier.default_run_flag (x)"])
    mode, notes = cheap_tier_default.resolve({}, warnings, cheap_tier="ab")
    assert mode == "on"
    assert _names(notes) == ["warning: config: dropped cheap_tier.default_run_flag (x)",
                             "deprecated: --cheap-tier=ab"]


def test_resolve_warning_never_has_a_no_flag_tail():
    # Something is always added, so "; no --cheap-tier added" would be a lie.
    dropped = ["config: dropped cheap_tier.extra (unknown key)"]
    for cfg, kw in (({"cheap_tier": {"default_run_flag": "off", "extra": 1}}, {}),
                    ({"cheap_tier": {"default_run_flag": "ab"}}, {}), ({}, {"no_cheap_tier": True})):
        notes = cheap_tier_default.resolve(cfg, dropped, **kw)[1]
        assert notes[0] == "warning: config: dropped cheap_tier.extra (unknown key)"
        assert len(notes) == 2 and notes[1].startswith("deprecated: ")


def test_resolve_rejects_bad_input():
    with pytest.raises(ValueError):
        cheap_tier_default.resolve({}, [], cheap_tier="AB")
    with pytest.raises(ValueError):
        cheap_tier_default.resolve({}, [], cheap_tier="ab", no_cheap_tier=True)


# --- the per-repo `--local` default (local_implement.default_run_flag) ---------


def test_default_local_needs_the_flag_and_the_full_design_permission(monkeypatch):
    monkeypatch.setattr(
        cheap_tier_default.lic, "load_capability",
        lambda path: {"nested": {"background_spawn_ok": True, "done_detected": True}})
    assert cheap_tier_default.default_local(
        {"local_implement": {"default_run_flag": "on",
                             "enabled": True, "full_design": True}}) is True
    # Absent block / absent key / "off": never a default.
    for cfg in (None, {}, {"local_implement": None}, {"local_implement": {}},
                {"local_implement": {"default_run_flag": "off",
                                     "enabled": True, "full_design": True}},
                {"local_implement": {"default_run_flag": "yes",
                                     "enabled": True, "full_design": True}}):
        assert cheap_tier_default.default_local(cfg) is False
    # "on" alone is not enough: a default the run would only refuse is dropped.
    assert cheap_tier_default.default_local(
        {"local_implement": {"default_run_flag": "on", "enabled": False,
                             "full_design": True}}) is False
    assert cheap_tier_default.default_local(
        {"local_implement": {"default_run_flag": "on", "enabled": True}}) is False


def test_default_local_not_forwarded_when_the_capability_gate_refuses(monkeypatch):
    cfg = {"local_implement": {"default_run_flag": "on", "enabled": True, "full_design": True}}
    monkeypatch.setattr(cheap_tier_default.lic, "load_capability",
                        lambda path: {"nested": {"background_spawn_ok": None, "done_detected": None}})
    assert cheap_tier_default.default_local(cfg) is False
    assert cheap_tier_default.resolve_local(cfg, local=True) is True  # explicit --local still wins


def test_is_local_drop_warning_matches_only_that_key():
    assert cheap_tier_default.is_local_drop_warning(
        "config: dropped local_implement.default_run_flag (not in ['on', 'off'])")
    assert not cheap_tier_default.is_local_drop_warning(
        "config: dropped cheap_tier.default_run_flag (x)")
    assert not cheap_tier_default.is_local_drop_warning(
        "config: dropped local_implement.enabled (x)")


def test_is_local_drop_warning_matches_the_whole_block_too():
    assert cheap_tier_default.is_local_drop_warning(
        "config: dropped local_implement (type 'object')")


def test_resolve_local_precedence():
    on = {"local_implement": {"default_run_flag": "on",
                              "enabled": True, "full_design": True}}
    assert cheap_tier_default.resolve_local(on) is True          # the repo default
    assert cheap_tier_default.resolve_local({}, local=True) is True  # --local wins
    assert cheap_tier_default.resolve_local(on, no_local=True) is False  # --no-local wins
    assert cheap_tier_default.resolve_local({}, no_local=True) is False
    with pytest.raises(ValueError):
        cheap_tier_default.resolve_local(on, local=True, no_local=True)


def test_flag_arg():
    assert cheap_tier_default.flag_arg(None) == ""
    assert cheap_tier_default.flag_arg("on") == "--cheap-tier"
    assert cheap_tier_default.flag_arg("ab") == "--cheap-tier=ab"
    with pytest.raises(ValueError):
        cheap_tier_default.flag_arg("off")
