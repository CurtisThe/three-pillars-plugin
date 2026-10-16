"""test_cheap_tier_default_cli.py — the CLI resolver over a temp repo.

design: cheap-tier-default-flag-everywhere
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cheap_tier_default  # noqa: E402


def _config(root: Path, block: dict) -> None:
    path = root / ".three-pillars" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, **block}), encoding="utf-8")


def _run(root: Path, argv):
    out, err = io.StringIO(), io.StringIO()
    code = cheap_tier_default.main(["--root", str(root), *argv], out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_cli_unset_prints_on(tmp_path):
    _config(tmp_path, {})
    code, out, err = _run(tmp_path, [])
    assert (code, out) == (0, "on\n")


def test_cli_default_ab_prints_on_with_a_deprecation_line(tmp_path):
    _config(tmp_path, {"cheap_tier": {"default_run_flag": "ab"}})
    code, out, err = _run(tmp_path, [])
    assert (code, out) == (0, "on\n")
    assert err.count("deprecated: cheap_tier.default_run_flag") == 1


def test_cli_explicit_flags_print_on(tmp_path):
    _config(tmp_path, {"cheap_tier": {"default_run_flag": "ab"}})
    for flag in ("--cheap-tier", "--cheap-tier=ab", "--no-cheap-tier"):
        code, out, err = _run(tmp_path, [flag])
        assert (code, out) == (0, "on\n")
        assert f"deprecated: {flag} " in err


def test_cli_invalid_config_dropped_warns_but_resolves_on(tmp_path):
    _config(tmp_path, {"cheap_tier": {"default_run_flag": "AB"}})
    code, out, err = _run(tmp_path, [])
    assert (code, out) == (0, "on\n")
    assert "warning: config: dropped cheap_tier" in err
    # The default path added the flag, so the "no --cheap-tier added" tail is wrong.
    assert "no --cheap-tier added" not in err


def test_cli_dropped_key_with_explicit_off_warns_without_a_tail(tmp_path):
    # The flag is always added, so the "no --cheap-tier added" tail never appears.
    _config(tmp_path, {"cheap_tier": {"default_run_flag": "off", "extra": 1}})
    code, out, err = _run(tmp_path, [])
    assert (code, out) == (0, "on\n")
    assert "warning: config: dropped cheap_tier.extra" in err
    assert "no --cheap-tier added" not in err
    assert "deprecated: cheap_tier.default_run_flag" in err


def test_cli_absent_config_prints_on(tmp_path):
    code, out, err = _run(tmp_path, [])
    assert (code, out) == (0, "on\n")


def test_cli_rejects_both_flags(tmp_path):
    with pytest.raises(SystemExit) as exc:
        _run(tmp_path, ["--cheap-tier", "--no-cheap-tier"])
    assert exc.value.code == 2


def test_cli_script_runs_as_subprocess(tmp_path):
    _config(tmp_path, {"cheap_tier": {"default_run_flag": "ab"}})
    script = Path(__file__).resolve().parent / "cheap_tier_default.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0
    assert proc.stdout == "on\n"
    assert proc.stderr.count("deprecated:") == 1
