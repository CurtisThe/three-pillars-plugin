"""Tests for role_engine.resolve — role → engine / model / effort / note.

design: local-role-routing (Task 1.2), re-based on the run by one-cheap-engine
(Task 2.2). `resolve` follows the run (`local=`), not the `role_engines` block:
no `--local` is `sonnet`, `local` is honoured only when the local backend is
present (the `available` probe is injected, never mocked), the local model comes
from the `local_implement` block through `model_policy.agent_alias`, and every
engine role resolves alike. A role outside `ENGINE_ROLES` raises `ValueError` —
judgment roles have no engine key.
Run with: TMPDIR=/home/curtis/t python3 -m pytest -n 4 skills/_shared/test_role_engine_resolve.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import role_engine as re_  # noqa: E402

YES = lambda: True  # the backend is installed (injected probe, never mocked)
NO = lambda: False


def _local_repo(tmp_path, model):
    """A tmp repo whose `local_implement.model` is `model`; returns the root."""
    conf = tmp_path / ".three-pillars"
    conf.mkdir(parents=True, exist_ok=True)
    (conf / "config.json").write_text(
        json.dumps({"local_implement": {"enabled": True, "model": model}}),
        encoding="utf-8",
    )
    return tmp_path


# --- no --local → sonnet -----------------------------------------------------

def test_unset_role_resolves_sonnet_with_no_note():
    assert re_.resolve("council_member", {}, available=YES, local=False) == {
        "role": "council_member",
        "engine": "sonnet",
        "model": "sonnet",
        "effort": "high",
        "note": None,
    }


def test_none_config_and_absent_block_resolve_sonnet():
    for config in (None, {}, {"role_engines": None}, {"models": {"review": "opus"}}):
        got = re_.resolve("review_finder", config, available=YES, local=False)
        assert (got["engine"], got["model"], got["note"]) == ("sonnet", "sonnet", None)


# --- local with the backend present -----------------------------------------

def test_local_engine_with_backend_uses_the_local_implement_model(tmp_path):
    root = _local_repo(tmp_path, "haiku")
    got = re_.resolve("council_member", {}, root=root, available=YES, local=True)
    assert got == {
        "role": "council_member",
        "engine": "local",
        "model": "haiku",
        "effort": "medium",
        "note": None,
    }


def test_local_without_a_local_implement_block_uses_the_default_haiku(tmp_path):
    got = re_.resolve("council_member", {}, root=tmp_path, available=YES, local=True)
    assert (got["engine"], got["model"], got["note"]) == ("local", "haiku", None)


def test_full_local_model_id_normalises_to_its_alias(tmp_path):
    root = _local_repo(tmp_path, "claude-haiku-4-5-20251001")
    got = re_.resolve("review_finder", {}, root=root, available=YES, local=True)
    assert (got["engine"], got["model"], got["note"]) == ("local", "haiku", None)


def test_non_alias_local_model_falls_back_to_haiku_with_a_note(tmp_path):
    root = _local_repo(tmp_path, "qwen3-coder")
    got = re_.resolve("review_finder", {}, root=root, available=YES, local=True)
    assert got["engine"] == "local"
    assert got["model"] == "haiku"
    assert got["effort"] == "medium"
    assert got["note"] == (
        "role-engine: local model qwen3-coder is not an Agent alias; using haiku"
    )


# --- local with no backend → sonnet, with the note --------------------------

def test_local_without_backend_falls_back_to_sonnet_with_a_note(tmp_path):
    got = re_.resolve("council_member", {}, root=tmp_path, available=NO, local=True)
    assert (got["engine"], got["model"], got["effort"]) == ("sonnet", "sonnet", "high")
    assert "backend" in got["note"]


# --- every engine role resolves alike ---------------------------------------

def test_context_scout_resolves_like_any_other_role(tmp_path):
    root = _local_repo(tmp_path, "haiku")
    got = re_.resolve("context_scout", {}, root=root, available=YES, local=True)
    assert got == {
        "role": "context_scout",
        "engine": "local",
        "model": "haiku",
        "effort": "medium",
        "note": None,
    }


def test_role_engines_opus_does_not_pull_a_scout_off_the_run():
    cfg = {"role_engines": {"review_finder": "local", "context_scout": "opus"}}
    got = re_.resolve("context_scout", cfg, available=YES, local=False)
    assert (got["engine"], got["model"]) == ("sonnet", "sonnet")


def test_scout_without_backend_notes_the_missing_backend(tmp_path):
    got = re_.resolve("context_scout", {}, root=tmp_path, available=NO, local=True)
    assert got["engine"] == "sonnet"
    assert "backend" in got["note"]


# --- judgment roles have no engine key --------------------------------------

def test_role_outside_engine_roles_raises_value_error():
    with pytest.raises(ValueError) as exc:
        re_.resolve("synthesizer", {"role_engines": {"synthesizer": "local"}}, available=YES)
    assert "synthesizer" in str(exc.value)
