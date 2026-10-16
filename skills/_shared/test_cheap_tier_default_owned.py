"""test_cheap_tier_default_owned.py — a launcher-owned `TP_LOCAL` never cancels the repo default.

design: design-run-launch-fixes (Part: a seat's launcher-owned `TP_LOCAL=off` cancels the repo's
`--local` default). On the launch path (`ignore_launcher_owned=True`) a `TP_LOCAL` named in
`CLAUDE_LAUNCHER_OWNED` is the seat launcher's own route, so `resolve_local` falls through to
`local_implement.default_run_flag`; in-session readers do not pass it (see
`test_cheap_tier_default_owned_scope.py`). An operator-set
`TP_LOCAL` keeps its precedence and `--local`/`--no-local` still win.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cheap_tier_default as ctd  # noqa: E402
import launch_design_run as ldr  # noqa: E402
from test_launch_design_run import rig  # noqa: E402,F401  (fixture)

BLOCK = {"enabled": True, "full_design": True}
KEY_ON = {"local_implement": dict(BLOCK, default_run_flag="on")}
KEY_OFF = {"local_implement": dict(BLOCK)}
LAUNCH = {"ignore_launcher_owned": True}
OWNED = {"CLAUDE_LAUNCHER_OWNED": "CLAUDE_LAUNCHER_ROLE TP_LOCAL"}
VALUES = ["off", "on", "garbage", "ON"]


@pytest.fixture(autouse=True)
def gate_passes(monkeypatch):
    monkeypatch.setattr(
        ctd.lic, "load_capability",
        lambda path: {"nested": {"background_spawn_ok": True, "done_detected": True}})


def _owned(value, marker=OWNED["CLAUDE_LAUNCHER_OWNED"]):
    return {"TP_LOCAL": value, "CLAUDE_LAUNCHER_OWNED": marker}


# --- resolver -----------------------------------------------------------------

@pytest.mark.parametrize("marker", ["TP_LOCAL", "CLAUDE_LAUNCHER_ROLE TP_LOCAL",
                                    "CLAUDE_LAUNCHER_ROLE,TP_LOCAL"])
def test_owned_off_falls_through_to_the_repo_default(marker):
    assert ctd.resolve_local(KEY_ON, env=_owned("off", marker), **LAUNCH) is True


def test_operator_set_off_still_cancels_the_repo_default():
    assert ctd.resolve_local(KEY_ON, env={"TP_LOCAL": "off"}, **LAUNCH) is False
    other = {"TP_LOCAL": "off", "CLAUDE_LAUNCHER_OWNED": "CLAUDE_LAUNCHER_ROLE"}
    assert ctd.resolve_local(KEY_ON, env=other, **LAUNCH) is False


@pytest.mark.parametrize("cfg", [KEY_ON, KEY_OFF, {}])
@pytest.mark.parametrize("value", VALUES)
def test_owned_value_resolves_as_if_unset(cfg, value):
    owned = ctd.resolve_local(cfg, env=_owned(value), **LAUNCH)
    assert owned is ctd.resolve_local(cfg, env={}, **LAUNCH)


def test_owned_on_with_the_repo_default_off_adds_no_local():
    assert ctd.resolve_local(KEY_OFF, env=_owned("on"), **LAUNCH) is False


@pytest.mark.parametrize("env", [_owned("off"), {"TP_LOCAL": "off"}, _owned("on")])
def test_explicit_flags_beat_both(env):
    assert ctd.resolve_local(KEY_OFF, local=True, env=env, **LAUNCH) is True
    assert ctd.resolve_local(KEY_ON, no_local=True, env=env, **LAUNCH) is False


# --- note ---------------------------------------------------------------------

def test_owned_value_gives_the_note():
    note = ctd.env_local_note(KEY_ON, _owned("off"), **LAUNCH)
    assert note.startswith("note: TP_LOCAL=off ") and "ignored for the run" in note
    assert ctd.env_local_note(KEY_OFF, _owned("on"), **LAUNCH).startswith("note: TP_LOCAL=on ")


def test_note_is_for_the_owned_case_only():
    assert ctd.env_local_note(KEY_ON, {"TP_LOCAL": "off"}, **LAUNCH).startswith("warning:")
    assert ctd.env_local_note(KEY_ON, {"TP_LOCAL": "on"}, **LAUNCH) is None
    assert ctd.env_local_note(KEY_ON, {"CLAUDE_LAUNCHER_OWNED": "TP_LOCAL"}, **LAUNCH) is None
    for flags in ({"local": True}, {"no_local": True}):
        assert ctd.env_local_note(KEY_ON, _owned("off"), **LAUNCH, **flags) is None


def test_local_source_names_tp_local_only_when_the_operator_set_it_on():
    assert ctd.local_source({"TP_LOCAL": "on"}, **LAUNCH) == "TP_LOCAL"
    for env in (_owned("on"), {}, {"TP_LOCAL": "off"}):
        assert ctd.local_source(env, **LAUNCH) == "local_implement.default_run_flag"


# --- launcher (dry-run, env injected) -----------------------------------------

def _launch(rig, capsys, cfg, env_over):
    path = Path(rig["repo"]) / ".three-pillars" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, **cfg}), encoding="utf-8")
    env = dict(rig["env"], **env_over)
    rc = ldr.main(["foo", "--dry-run"], env=env, cwd=rig["repo"], help_probe=lambda e: "")
    cap = capsys.readouterr()
    assert rc == 0
    return cap.out.strip().splitlines()[-1], cap.err


def test_launcher_owned_off_keeps_the_repo_local_default(rig, capsys):
    cmd, err = _launch(rig, capsys, KEY_ON, _owned("off"))
    assert cmd.endswith("'/tp-run-full-design foo --local'; exec bash")
    assert any(ln.startswith("note: TP_LOCAL=off ") for ln in err.splitlines())
    assert 'TP_LOCAL="off"' not in err


def test_launcher_operator_off_still_wins(rig, capsys):
    cmd, err = _launch(rig, capsys, KEY_ON, {"TP_LOCAL": "off"})
    assert cmd.endswith("'/tp-run-full-design foo'; exec bash")
    assert 'warning: TP_LOCAL="off"' in err


@pytest.mark.parametrize("env_over,label", [
    (_owned("on"), "local_implement.default_run_flag"),
    ({"TP_LOCAL": "on"}, "TP_LOCAL"),
])
def test_launcher_source_label_follows_the_resolver(rig, capsys, monkeypatch, env_over, label):
    def bad_block(root):
        raise ValueError("schema says no")
    monkeypatch.setattr(ldr.lic, "load", bad_block)
    cmd, err = _launch(rig, capsys, KEY_ON, env_over)
    assert cmd.endswith("'/tp-run-full-design foo'; exec bash")
    assert f'warning: {label} "on" not applied: schema says no' in err
