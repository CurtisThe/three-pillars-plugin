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
                            "max_files": 3, "attempt_wall_clock_s": 1200,
                            "registry_files": []}
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


def test_attempt_wall_clock_s_validation(tmp_path):
    # Accepted: an int >= 60 (and the default).
    for ok in (60, 1200):
        cfg = lic.load(_write(tmp_path, {"local_implement": {"attempt_wall_clock_s": ok}}))
        assert cfg["attempt_wall_clock_s"] == ok
    # Refused: below 60, a bool, a non-integer.
    for bad in (30, True, "20m"):
        with pytest.raises(ValueError, match=r"attempt_wall_clock_s"):
            lic.load(_write(tmp_path, {"local_implement": {"attempt_wall_clock_s": bad}}))


def test_registry_files_validation(tmp_path):
    cfg = lic.load(_write(tmp_path, {"local_implement": {"registry_files": ["a/b.py"]}}))
    assert cfg["registry_files"] == ["a/b.py"]
    assert lic.load(_write(tmp_path, {"local_implement": {}}))["registry_files"] == []
    for bad in ("a.py", [1], [""], None):
        with pytest.raises(ValueError, match=r"registry_files"):
            lic.load(_write(tmp_path, {"local_implement": {"registry_files": bad}}))


def _cli(root: Path, mode: str, capability: Path | None = None):
    cmd = [sys.executable, str(SCRIPT), "--check", mode, "--root", str(root)]
    if capability is not None:
        cmd += ["--capability", str(capability)]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(root))


def test_cli_check_exit_codes(tmp_path):
    cap = tmp_path / "capability.json"
    cap.write_text(json.dumps({
        "checked": None, "claude_code_version": None,
        "main": {"background_spawn_ok": True, "done_detected": True},
        "nested": {"background_spawn_ok": True, "done_detected": True},
    }), encoding="utf-8")
    _write(tmp_path, {"schema_version": 1, "local_implement": {"enabled": True}})
    ok = _cli(tmp_path, "interactive", cap)
    assert ok.returncode == 0, ok.stderr
    assert ok.stdout == ""
    refused = _cli(tmp_path, "full_design", cap)
    assert refused.returncode == 1
    assert refused.stdout.strip() == ("--local refused: set local_implement.full_design=true "
                                      "in .three-pillars/config.json")
    _write(tmp_path, {"schema_version": 1,
                      "local_implement": {"enabled": True, "full_design": True}})
    assert _cli(tmp_path, "full_design", cap).returncode == 0
    # A malformed block fails closed with one line naming the problem.
    _write(tmp_path, {"local_implement": {"enabled": True, "typo": 1}})
    bad = _cli(tmp_path, "interactive", cap)
    assert bad.returncode == 1
    assert bad.stdout.startswith("--local refused:") and "typo" in bad.stdout
    assert len(bad.stdout.strip().splitlines()) == 1


def _ct(**over):
    return {"applied_at": None, "declined": False, "values": {}, **over}


def test_client_timeouts_block_accepted(tmp_path):
    cap = tmp_path / "capability.json"
    cap.write_text(json.dumps({m: {"background_spawn_ok": True, "done_detected": True}
                               for m in ("main", "nested")}), encoding="utf-8")
    four = _ct(applied_at="2026-10-02T00:00:00Z", values=dict.fromkeys(lic._TIMEOUT_KEYS, 9))
    for rec in (_ct(), _ct(declined=True), _ct(values={"API_TIMEOUT_MS": 5}), four):
        root = _write(tmp_path, {"local_implement": {"enabled": True, "full_design": True,
                                                     "client_timeouts": rec}})
        assert lic.load(root)["client_timeouts"] == rec
        assert _cli(root, "full_design", cap).returncode == 0
    assert "client_timeouts" not in lic.DEFAULTS


def test_client_timeouts_bad_shape_raises(tmp_path):
    bad = (_ct(extra=1), _ct(values={"NOPE_MS": 1}), _ct(values={"API_TIMEOUT_MS": "5"}),
           _ct(values={"API_TIMEOUT_MS": 0}), _ct(values={"API_TIMEOUT_MS": True}),
           _ct(declined="no"), _ct(applied_at=5), "x", {"applied_at": None, "declined": False},
           {"declined": False, "values": {}}, {"applied_at": None, "values": {}})
    for rec in bad:
        with pytest.raises(ValueError, match=r"client_timeouts"):
            lic.load(_write(tmp_path, {"local_implement": {"client_timeouts": rec}}))


def test_repo_config_md_names_client_timeouts():
    md = (Path(__file__).resolve().parent / "repo-config.md").read_text(encoding="utf-8")
    line = next(ln for ln in md.splitlines() if ln.startswith("- `local_implement`"))
    assert "client_timeouts" in line
