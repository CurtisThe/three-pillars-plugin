"""test_cheap_tier_default_owned_scope.py — a launcher-owned `TP_LOCAL` is ignored at the launch only.

design: design-run-launch-fixes (audit patch). The seat->run launch passes
`ignore_launcher_owned=True`; every in-session reader (`resolve_local` as `cheap_engine` and
`role_engine` call it) keeps honouring `TP_LOCAL`, owned or not, as it did before the launch fix.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cheap_engine  # noqa: E402
import cheap_tier_default as ctd  # noqa: E402

BLOCK = {"enabled": True, "full_design": True}
KEY_ON = {"local_implement": dict(BLOCK, default_run_flag="on")}
KEY_OFF = {"local_implement": dict(BLOCK)}
MARKER = "CLAUDE_LAUNCHER_ROLE TP_LOCAL"


@pytest.fixture(autouse=True)
def gate_passes(monkeypatch):
    monkeypatch.setattr(
        ctd.lic, "load_capability",
        lambda path: {"nested": {"background_spawn_ok": True, "done_detected": True}})


def _owned(value):
    return {"TP_LOCAL": value, "CLAUDE_LAUNCHER_OWNED": MARKER}


def test_owned_off_is_honoured_without_the_keyword():
    assert ctd.resolve_local(KEY_ON, env=_owned("off")) is False


def test_owned_on_is_honoured_without_the_keyword():
    assert ctd.resolve_local(KEY_OFF, env=_owned("on")) is True


def test_the_keyword_flips_both_owned_cases():
    assert ctd.resolve_local(KEY_ON, env=_owned("off"), ignore_launcher_owned=True) is True
    assert ctd.resolve_local(KEY_OFF, env=_owned("on"), ignore_launcher_owned=True) is False


def test_no_note_and_the_real_source_without_the_keyword():
    assert ctd.env_local_note(KEY_ON, _owned("off")).startswith("warning:")
    assert ctd.env_local_note(KEY_OFF, _owned("on")) is None
    assert ctd.local_source(_owned("on")) == "TP_LOCAL"


@pytest.mark.parametrize("cfg,value,expected", [(KEY_ON, "off", False), (KEY_OFF, "on", True)])
def test_in_session_engine_honours_an_owned_tp_local(cfg, value, expected):
    assert cheap_engine.resolve_run(cfg, env=_owned(value))["local"] is expected
