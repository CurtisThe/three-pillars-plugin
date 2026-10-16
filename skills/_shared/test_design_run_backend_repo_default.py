"""This repo's design runs default to the direct backend (L208).

design: design-run-launch-fixes (Task 1.3). The three-pillars repo sets
`design_run_backend: "direct"` in its own `.three-pillars/config.json`, so its
design-run orchestrators talk to Anthropic directly. The code default is
unchanged: an empty config, or a consumer config without the key, still
resolves to `route`. The repo config is read through the real loader, from
the repo root found relative to this file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
_REPO_ROOT = _SHARED.parent.parent
sys.path.insert(0, str(_SHARED))

import design_run_backend as drb  # noqa: E402
import repo_config_load as rcl  # noqa: E402


def _repo_load():
    if not (_REPO_ROOT / ".three-pillars" / "config.json").is_file():
        pytest.skip("no .three-pillars/config.json in this tree")  # a plugin install ships none
    loaded = rcl.load_repo_config(_REPO_ROOT)
    assert loaded.status == "ok", loaded.warnings
    return loaded


def test_repo_config_sets_direct():
    cfg = _repo_load().config
    assert cfg.get("design_run_backend") == "direct"
    assert drb.resolve(cfg, direct=False) == "direct"


def test_repo_config_key_survives_prune():
    loaded = _repo_load()
    assert not [w for w in loaded.warnings if drb.is_backend_drop_warning(w)]


def test_empty_config_default_is_route():
    assert drb.resolve({}, direct=False) == "route"


def test_consumer_config_without_key_is_route():
    consumer = {"schema_version": 1, "models": {"design_run": "sonnet"}}
    assert drb.resolve(consumer, direct=False) == "route"
