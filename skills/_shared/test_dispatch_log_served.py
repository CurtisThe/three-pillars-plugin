"""test_dispatch_log_served.py — the served-rung fields on `dispatch_log record`.

design: cheap-tier-local-routing (detailed-design.md §Interfaces `dispatch_log.py record`, Task 3.1)

`--requested-rung` makes the row carry `served_rung` / `fallback` from `served_rung.served(...)`
(evidence first: a mirror or partial-fallback run is never the local arm) and `agent8`;
`--lease-wait-s`, `--measure`, `--fallback-requests` ride along. Without any new flag the row
is byte-identical to today's. Every row read here is the one the CLI printed, asserted equal
to the line it appended to the ndjson.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

CLI = Path(__file__).resolve().parent / "dispatch_log.py"
NEW_KEYS = {"requested_rung", "served_rung", "fallback", "fallback_requests",
            "lease_wait_s", "agent8", "measure"}
LOCAL = ["--requested-rung", "local-medium", "--rung", "local-medium"]
MIRROR = ["--requested-rung", "local-medium", "--rung", "sonnet-medium"]


def _run(tmp_path, *extra):
    base = ["record", "--design-dir", str(tmp_path), "--role", "docs_draft", "--agent",
            "tp-drafter", "--reason", "x", "--outcome", "y", "--root", str(tmp_path),
            "--config-dir", str(tmp_path)]
    return subprocess.run([sys.executable, str(CLI), *base, *extra],
                          capture_output=True, text=True, timeout=60)


def _row(tmp_path, *extra):
    proc = _run(tmp_path, *extra)
    assert proc.returncode == 0, proc.stderr
    printed = json.loads(proc.stdout)
    rows = (tmp_path / "dispatch-telemetry.ndjson").read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[-1]) == printed
    return printed


def test_partial_fallback_is_a_mirror_row_never_the_local_arm(tmp_path):
    rec = _row(tmp_path, *LOCAL, "--local-requests", "3", "--fallback-requests", "2",
               "--agent-id", "agent-a8a5f599xyz")
    assert (rec["served_rung"], rec["fallback"], rec["agent8"]) == (
        "sonnet-mirror", "partial-fallback", "a8a5f599")
    assert (rec["requested_rung"], rec["fallback_requests"]) == ("local-medium", 2)


def test_a_clean_local_run_is_the_local_arm(tmp_path):
    rec = _row(tmp_path, *LOCAL, "--local-requests", "3", "--fallback-requests", "0")
    assert rec["served_rung"] == "local"
    assert rec.get("fallback") is None


def test_busy_mirror_row_keeps_its_reason(tmp_path):
    rec = _row(tmp_path, *MIRROR, "--fallback", "local-busy")
    assert (rec["served_rung"], rec["fallback"]) == ("sonnet-mirror", "local-busy")


def test_lease_wait_and_wall_are_stored_separately(tmp_path):
    rec = _row(tmp_path, *MIRROR, "--lease-wait-s", "240", "--wall-s", "90")
    assert (rec["lease_wait_s"], rec["wall_s"]) == (240.0, 90.0)


@pytest.mark.parametrize("value", ["owner", "other"])
def test_measure_owner_and_other_are_stored(tmp_path, value):
    assert _row(tmp_path, *MIRROR, "--measure", value)["measure"] == value


def test_an_epoch_string_started_at_is_stored_as_its_iso_stamp(tmp_path):
    # `attempt_watchdog.py arm` prints started_at as epoch seconds
    rec = _row(tmp_path, *MIRROR, "--started-at", "1790000000.5")
    assert rec["started_at"] == "2026-09-21T14:13:20.500000Z"


def test_an_iso_started_at_is_unchanged(tmp_path):
    rec = _row(tmp_path, "--started-at", "2026-01-01T00:00:00Z")
    assert rec["started_at"] == "2026-01-01T00:00:00Z"


def test_no_new_flag_and_measure_off_leave_the_row_byte_identical(tmp_path):
    legacy_dir, off_dir = tmp_path / "a", tmp_path / "b"
    legacy_dir.mkdir()
    off_dir.mkdir()
    legacy = _row(legacy_dir, "--rung", "local-medium", "--local-requests", "1")
    off = _row(off_dir, "--rung", "local-medium", "--local-requests", "1", "--measure", "off")
    assert NEW_KEYS.isdisjoint(legacy)
    assert json.dumps(off, sort_keys=True) == json.dumps(legacy, sort_keys=True)


def test_watchdog_error_record_exits_0_and_is_never_the_local_arm(tmp_path):
    proc = _run(tmp_path, *LOCAL, "--fallback", "watchdog-error")
    assert proc.returncode == 0, proc.stderr
    assert "local rung recorded without --local-requests" in proc.stderr
    rec = json.loads(proc.stdout)
    assert rec["fallback"] == "watchdog-error"
    assert rec["served_rung"] not in (None, "local")
    assert (tmp_path / "dispatch-telemetry.ndjson").read_text(encoding="utf-8").strip()
