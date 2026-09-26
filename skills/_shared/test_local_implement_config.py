"""Tests for local_implement_config.py — the `local_implement` block loader.

design: local-implement-and-review (Task 3.2).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_implement_config as lic  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "local_implement_config.py"


def _write(root: Path, config) -> Path:
    d = root / ".three-pillars"
    d.mkdir(parents=True, exist_ok=True)
    text = config if isinstance(config, str) else json.dumps(config)
    (d / "config.json").write_text(text, encoding="utf-8")
    return root


def test_defaults_merge(tmp_path):
    assert lic.DEFAULTS == {"enabled": False, "model": "haiku", "fallback_model": "sonnet",
                            "full_design": False, "escalate": True, "max_retries": 2,
                            "max_files": 3}
    # No config file, and a config without the block → None.
    assert lic.load(tmp_path) is None
    assert lic.load(_write(tmp_path, {"schema_version": 1})) is None
    # A partial block is merged over DEFAULTS; DEFAULTS itself is not mutated.
    cfg = lic.load(_write(tmp_path, {"schema_version": 1,
                                     "local_implement": {"enabled": True, "max_files": 5}}))
    assert cfg == dict(lic.DEFAULTS, enabled=True, max_files=5)
    assert lic.DEFAULTS["enabled"] is False
    # Malformed → ValueError: bad JSON, non-object block, unknown key, wrong type.
    for bad in ("{not json", json.dumps({"local_implement": []}),
                json.dumps({"local_implement": {"enabled": True, "typo": 1}}),
                json.dumps({"local_implement": {"enabled": "yes"}}),
                json.dumps({"local_implement": {"max_files": 0}}),
                json.dumps({"local_implement": {"max_retries": True}}),
                json.dumps({"local_implement": {"model": ""}}),
                json.dumps(["not", "an", "object"])):
        with pytest.raises(ValueError):
            lic.load(_write(tmp_path, bad))


def test_permission_error_lines():
    on = dict(lic.DEFAULTS, enabled=True)
    both = dict(on, full_design=True)
    assert lic.permission_error(on, "interactive") is None
    assert lic.permission_error(both, "full_design") is None
    assert lic.permission_error(both, "interactive") is None
    line = lic.permission_error(None, "interactive")
    assert line == ("--local refused: set local_implement.enabled=true "
                    "in .three-pillars/config.json")
    assert lic.permission_error(dict(lic.DEFAULTS), "interactive") == line
    only_fd = lic.permission_error(on, "full_design")
    assert only_fd == ("--local refused: set local_implement.full_design=true "
                       "in .three-pillars/config.json")
    only_en = lic.permission_error(dict(lic.DEFAULTS, full_design=True), "full_design")
    assert "local_implement.enabled=true" in only_en and "full_design=true" not in only_en
    none = lic.permission_error(None, "full_design")
    assert "local_implement.enabled=true" in none and "local_implement.full_design=true" in none
    for msg in (line, only_fd, only_en, none):
        assert "\n" not in msg
    with pytest.raises(ValueError):
        lic.permission_error(on, "bogus")


def _cli(root: Path, mode: str):
    return subprocess.run([sys.executable, str(SCRIPT), "--check", mode, "--root", str(root)],
                          capture_output=True, text=True, cwd=str(root))


def test_cli_check_exit_codes(tmp_path):
    _write(tmp_path, {"schema_version": 1, "local_implement": {"enabled": True}})
    ok = _cli(tmp_path, "interactive")
    assert ok.returncode == 0, ok.stderr
    assert ok.stdout == ""
    refused = _cli(tmp_path, "full_design")
    assert refused.returncode == 1
    assert refused.stdout.strip() == ("--local refused: set local_implement.full_design=true "
                                      "in .three-pillars/config.json")
    _write(tmp_path, {"schema_version": 1,
                      "local_implement": {"enabled": True, "full_design": True}})
    assert _cli(tmp_path, "full_design").returncode == 0
    # A malformed block fails closed with one line naming the problem.
    _write(tmp_path, {"local_implement": {"enabled": True, "typo": 1}})
    bad = _cli(tmp_path, "interactive")
    assert bad.returncode == 1
    assert bad.stdout.startswith("--local refused:") and "typo" in bad.stdout
    assert len(bad.stdout.strip().splitlines()) == 1
