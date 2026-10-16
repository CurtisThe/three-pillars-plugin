"""test_run_round_config_load.py — run_round._load_repo_config routes through the
shared repo_config_load.load_repo_config (schema pruning), not a raw disk read.

design: consumer-repo-parity (Task 1.4)

Covers the three-way contract:
  - a valid working-tree config with one invalid key: pruned dict, valid sibling kept
  - a config missing schema_version: {} (the fatal schema_version rule; status="ok")
  - a missing or unreadable file: None (fail-open — the caller falls back to strict
    expects_copilot/expects_github_checks defaults, unchanged from before the rewire)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _write_config(repo_root: Path, config: dict) -> None:
    cfgdir = repo_root / ".three-pillars"
    cfgdir.mkdir(parents=True, exist_ok=True)
    (cfgdir / "config.json").write_text(json.dumps(config))


def test_pruned_dict_keeps_valid_sibling(tmp_path):
    """One invalid key (require_review_proof: "no", not a boolean) is pruned; the
    valid sibling (automation_identities) survives — same pruning loader as the gate."""
    import run_round

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_config(repo_root, {
        "schema_version": 1,
        "review": {"require_review_proof": "no", "automation_identities": ["keep-me"]},
    })

    loaded = run_round._load_repo_config(repo_root)
    assert loaded is not None
    assert "require_review_proof" not in loaded.get("review", {})
    assert loaded.get("review", {}).get("automation_identities") == ["keep-me"]


def test_missing_schema_version_returns_empty_dict(tmp_path):
    """A config missing schema_version fails the fatal rule -> {} (status="ok",
    NOT None — the caller's config=None strict-default fallback must NOT fire here)."""
    import run_round

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_config(repo_root, {"review": {"expects_copilot": False}})

    loaded = run_round._load_repo_config(repo_root)
    assert loaded == {}


def test_missing_file_returns_none(tmp_path):
    """No .three-pillars/config.json at all -> None (absent; fail-open)."""
    import run_round

    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    loaded = run_round._load_repo_config(repo_root)
    assert loaded is None


def test_unreadable_bad_json_returns_none(tmp_path):
    """Bad JSON -> None (unreadable; fail-open), same as a missing file."""
    import run_round

    repo_root = tmp_path / "repo"
    cfgdir = repo_root / ".three-pillars"
    cfgdir.mkdir(parents=True)
    (cfgdir / "config.json").write_text("{not valid json}")

    loaded = run_round._load_repo_config(repo_root)
    assert loaded is None
