"""Tests for child_profile.py — the profile rule for a child spawn, in one module.

child-spawn-profile-inherit task 1.1: a child `claude -p` spawned by the dispatcher must
inherit the orchestrator's profile. `profile_name` names a dir only when it sits directly
under `.claude-profiles`; `pin` adds `CLAUDE_LAUNCHER_FORCE_PROFILE=<name>` to a child env
from the parent's `CLAUDE_CONFIG_DIR` and is a no-op otherwise; `config_dir` resolves the
config dir like `child_transcript._cfg`; `candidate_dirs` lists the primary dir first then
its sibling profiles; `note_found` logs a found-under once per (key, dir) and only
off-primary; `polled_note` names every dir it would poll. Everything is fail-open.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_profile  # noqa: E402

CHILD_KEY = "c0ffee00"


@pytest.fixture(autouse=True)
def _clear_notes():
    child_profile._noted.clear()
    yield
    child_profile._noted.clear()


def test_profile_name_of_profile_dir(tmp_path):
    assert child_profile.profile_name(tmp_path / ".claude-profiles" / "aris") == "aris"


def test_profile_name_ignores_trailing_slash(tmp_path):
    assert child_profile.profile_name(str(tmp_path / ".claude-profiles" / "aris") + "/") == "aris"


@pytest.mark.parametrize("bad", ["", None])
def test_profile_name_none_for_non_profile_dirs(tmp_path, bad):
    cfg = tmp_path
    for path in [cfg / ".claude", cfg / ".claude-profiles",
                 cfg / ".claude-profiles" / "aris" / "sub", bad]:
        assert child_profile.profile_name(path) is None


def test_pin_adds_force_profile(tmp_path):
    parent = {"CLAUDE_CONFIG_DIR": str(tmp_path / ".claude-profiles" / "aris")}
    child = {"PATH": "p"}
    assert child_profile.pin(parent, child) == {
        "PATH": "p", "CLAUDE_LAUNCHER_FORCE_PROFILE": "aris"}


@pytest.mark.parametrize("parent", [
    {"CLAUDE_CONFIG_DIR": "/home/u/.claude"},
    {},
])
def test_pin_noop_without_profile(parent):
    out = child_profile.pin(parent, {"PATH": "p"})
    assert out == {"PATH": "p"}
    assert "CLAUDE_LAUNCHER_FORCE_PROFILE" not in out


def test_pin_does_not_mutate_inputs(tmp_path):
    parent = {"CLAUDE_CONFIG_DIR": str(tmp_path / ".claude-profiles" / "aris")}
    child = {"PATH": "p"}
    child_profile.pin(parent, child)
    assert parent == {"CLAUDE_CONFIG_DIR": str(tmp_path / ".claude-profiles" / "aris")}
    assert child == {"PATH": "p"}


def test_config_dir_from_env_and_default(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert child_profile.config_dir({"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")}) == tmp_path / "cfg"
    assert child_profile.config_dir({}) == Path.home() / ".claude"


def test_candidate_dirs_primary_then_sorted_siblings(tmp_path):
    profiles = tmp_path / ".claude-profiles"
    aris = profiles / "aris"
    aris.mkdir(parents=True)
    for name in ("work", "personal"):
        (profiles / name).mkdir()
    (profiles / "notes.txt").write_text("not a dir", encoding="utf-8")
    assert child_profile.candidate_dirs(aris) == [aris, profiles / "personal", profiles / "work"]


def test_candidate_dirs_non_profile_dir_lists_only_it(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (tmp_path / "other").mkdir()
    assert child_profile.candidate_dirs(cfg) == [cfg]


def test_candidate_dirs_unlistable_parent_returns_only_cfg(tmp_path, monkeypatch):
    aris = tmp_path / ".claude-profiles" / "aris"
    aris.mkdir(parents=True)

    def boom(self):
        raise OSError("cannot list")

    monkeypatch.setattr(Path, "iterdir", boom)
    assert child_profile.candidate_dirs(aris) == [aris]


def test_note_found_once_and_only_off_primary(tmp_path, capsys):
    profiles = tmp_path / ".claude-profiles"
    aris = profiles / "aris"
    personal = profiles / "personal"
    child_profile.note_found(CHILD_KEY, personal, aris)
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert CHILD_KEY in err and str(personal) in err and str(aris) in err
    child_profile.note_found(CHILD_KEY, personal, aris)
    assert capsys.readouterr().err == ""
    child_profile.note_found(CHILD_KEY, aris, aris)
    assert capsys.readouterr().err == ""


def test_polled_note_names_every_dir(tmp_path, monkeypatch):
    profiles = tmp_path / ".claude-profiles"
    aris = profiles / "aris"
    personal = profiles / "personal"
    aris.mkdir(parents=True)
    personal.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(aris))
    note = child_profile.polled_note()
    assert note.startswith(" (polled ")
    assert str(aris) in note and str(personal) in note
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    solo = child_profile.polled_note()
    assert str(tmp_path / "cfg") in solo
    assert str(personal) not in solo
