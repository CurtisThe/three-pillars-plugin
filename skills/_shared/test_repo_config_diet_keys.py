"""Schema rows for the ceremony-diet keys retro.enabled and fleet.max_live (Task 1.4).

Run with: python3 -m pytest skills/_shared/test_repo_config_diet_keys.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import repo_config_load as rcl  # noqa: E402

DOC = Path(__file__).resolve().parent / "repo-config.md"


def _load(tmp_path, **extra):
    (tmp_path / ".three-pillars").mkdir()
    cfg = {"schema_version": 1}
    cfg.update(extra)
    (tmp_path / ".three-pillars" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return rcl.load_repo_config(tmp_path)


def test_valid_keys_kept_without_warning(tmp_path):
    res = _load(tmp_path, retro={"enabled": True}, fleet={"max_live": 4, "diff_balloon_factor": 5})
    assert res.warnings == []
    assert res.config["retro"] == {"enabled": True}
    assert res.config["fleet"] == {"max_live": 4, "diff_balloon_factor": 5}


def test_max_live_zero_pruned_balloon_survives(tmp_path):
    res = _load(tmp_path, fleet={"max_live": 0, "diff_balloon_factor": 5})
    assert len(res.warnings) == 1
    assert "max_live" not in res.config.get("fleet", {})
    assert res.config["fleet"]["diff_balloon_factor"] == 5


def test_retro_enabled_string_pruned(tmp_path):
    res = _load(tmp_path, retro={"enabled": "yes"})
    assert res.warnings
    assert "enabled" not in res.config.get("retro", {})


def test_doc_names_both_keys():
    text = DOC.read_text(encoding="utf-8")
    assert "retro.enabled" in text
    assert "fleet.max_live" in text
