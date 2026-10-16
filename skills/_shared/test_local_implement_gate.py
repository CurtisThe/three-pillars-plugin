"""Tests for the runaway-ceiling gate in local_implement_config.py.

design: run-throughput (Task 1.4)
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
COMMITTED = Path(__file__).resolve().parent / "runaway_capability.json"
SPAWN_MAIN = "--local refused: runaway ceiling unavailable (background spawn, main)"
SPAWN_NESTED = "--local refused: runaway ceiling unavailable (background spawn, nested)"
DONE_MAIN = "--local refused: runaway ceiling unavailable (done detection, main)"


def _section(**kw) -> dict:
    base = {"background_spawn_ok": None, "done_detected": None,
            "taskstop_ok": None, "router_stats_agent_match": None}
    base.update(kw)
    return base


def _cap(main=None, nested=None) -> dict:
    return {"checked": None, "claude_code_version": None, "main": main, "nested": nested}


def test_committed_capability_file_is_well_formed_and_gates_as_recorded():
    # Task 1.8's live check is the only writer of `true`; before it runs the file is all
    # null. Either way the file carries every field and the gate follows its values.
    cap = lic.load_capability(COMMITTED)
    assert set(cap) == {"checked", "claude_code_version", "main", "nested"}
    for mode, sec in (("interactive", "main"), ("full_design", "nested")):
        s = cap[sec]
        assert set(s) == set(_section())
        if s["background_spawn_ok"] is not True:
            want = f"--local refused: runaway ceiling unavailable (background spawn, {sec})"
        elif s["done_detected"] is not True:
            want = f"--local refused: runaway ceiling unavailable (done detection, {sec})"
        else:
            want = None
        assert lic.runaway_ceiling_error(mode, cap) == want
    if cap["checked"] is None:
        assert cap["claude_code_version"] is None
        assert cap["main"] == _section() and cap["nested"] == _section()
    else:
        assert cap["claude_code_version"]


def test_all_null_capability_refuses_both_modes():
    cap = _cap(main=_section(), nested=_section())
    assert lic.runaway_ceiling_error("interactive", cap) == SPAWN_MAIN
    assert lic.runaway_ceiling_error("full_design", cap) == SPAWN_NESTED


def test_main_true_nested_null():
    cap = _cap(main=_section(background_spawn_ok=True, done_detected=True))
    assert lic.runaway_ceiling_error("interactive", cap) is None
    assert lic.runaway_ceiling_error("full_design", cap) == SPAWN_NESTED
    # A missing/non-object section refuses the same way as an all-null one.
    cap2 = _cap(main=None, nested=_section(background_spawn_ok=True, done_detected=True))
    assert lic.runaway_ceiling_error("interactive", cap2) == SPAWN_MAIN
    assert lic.runaway_ceiling_error("full_design", cap2) is None


def test_done_detection_order():
    cap = _cap(main=_section(background_spawn_ok=True, done_detected=False))
    assert lic.runaway_ceiling_error("interactive", cap) == DONE_MAIN


def test_missing_capability_file_refuses(tmp_path):
    cap = lic.load_capability(tmp_path / "absent.json")
    assert cap is None
    assert lic.runaway_ceiling_error("interactive", None) == SPAWN_MAIN
    assert lic.runaway_ceiling_error("full_design", None) == SPAWN_NESTED


def test_invalid_or_non_object_file_loads_none(tmp_path):
    for bad in ("{not json", json.dumps(["not", "an", "object"]), json.dumps(42)):
        p = tmp_path / "capability.json"
        p.write_text(bad, encoding="utf-8")
        assert lic.load_capability(p) is None
        assert lic.runaway_ceiling_error("interactive", None) == SPAWN_MAIN


def test_unrelated_fields_do_not_refuse():
    cap = _cap(main=_section(background_spawn_ok=True, done_detected=True,
                             taskstop_ok=False, router_stats_agent_match=False))
    assert lic.runaway_ceiling_error("interactive", cap) is None
    with pytest.raises(ValueError):
        lic.runaway_ceiling_error("bogus", cap)


def _enabled_root(tmp_path):
    d = tmp_path / ".three-pillars"
    d.mkdir(parents=True)
    (d / "config.json").write_text(
        json.dumps({"schema_version": 1,
                    "local_implement": {"enabled": True, "full_design": True}}),
        encoding="utf-8")
    return tmp_path


def test_cli_refuses_on_all_null_capability_file(tmp_path):
    root = _enabled_root(tmp_path)
    cap = tmp_path / "cap.json"
    cap.write_text(json.dumps(_cap(main=_section(), nested=_section())), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(SCRIPT), "--check", "interactive",
                           "--root", str(root), "--capability", str(cap)],
                          capture_output=True, text=True, cwd=str(root))
    assert proc.returncode == 1
    assert proc.stdout.strip() == SPAWN_MAIN
    assert len(proc.stdout.strip().splitlines()) == 1


@pytest.mark.parametrize("mode", ["interactive", "full_design"])
def test_cli_default_reads_committed_capability_file(tmp_path, mode):
    root = _enabled_root(tmp_path)
    want = lic.runaway_ceiling_error(mode, lic.load_capability(COMMITTED))
    proc = subprocess.run([sys.executable, str(SCRIPT), "--check", mode, "--root", str(root)],
                          capture_output=True, text=True, cwd=str(root))
    assert proc.returncode == (0 if want is None else 1)
    assert proc.stdout.strip() == (want or "")
