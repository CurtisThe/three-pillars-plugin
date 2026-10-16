"""test_dispatch_log_vocab.py — `dispatch_log record`'s lenient flags never exit 2.

design: cheap-tier-local-routing (detailed-design.md §Module Structure `dispatch_log.py`, Task 3.1)

`--fallback`, `--measure` and `--lease-wait-s` are free text, so an unlisted or unrendered value
is one stderr note and a safe stored value, never an argparse exit 2 and never a dropped row
(telemetry never gates a dispatch). The consumer and router-down rows (no router at all) are
written as `sonnet-mirror` rows with their reason and a numeric `lease_wait_s`.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

CLI = Path(__file__).resolve().parent / "dispatch_log.py"
CONSUMER = ["--requested-rung", "local-medium", "--rung", "sonnet-medium",
            "--lease-wait-s", "0.0"]


def _run(tmp_path, *extra):
    base = ["record", "--design-dir", str(tmp_path), "--role", "docs_draft", "--agent",
            "tp-drafter", "--reason", "x", "--outcome", "y", "--root", str(tmp_path),
            "--config-dir", str(tmp_path)]
    proc = subprocess.run([sys.executable, str(CLI), *base, *extra],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr  # never exit 2
    rec = json.loads(proc.stdout)
    rows = (tmp_path / "dispatch-telemetry.ndjson").read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[-1]) == rec  # the row is never dropped
    return rec, proc.stderr


def test_an_unlisted_fallback_is_unrecorded_with_one_note(tmp_path):
    rec, err = _run(tmp_path, *CONSUMER, "--fallback", "made-up-reason")
    assert rec["fallback"] == "unrecorded"
    assert len([ln for ln in err.splitlines() if "made-up-reason" in ln]) == 1


def test_an_unlisted_fallback_without_a_requested_rung_is_still_unrecorded(tmp_path):
    rec, err = _run(tmp_path, "--fallback", "made-up-reason")
    assert rec["fallback"] == "unrecorded" and "made-up-reason" in err


def test_a_bogus_measure_is_ignored_with_a_note(tmp_path):
    rec, err = _run(tmp_path, *CONSUMER, "--measure", "bogus")
    assert "measure" not in rec
    assert "measure bogus ignored" in err


@pytest.mark.parametrize("value", ["bogus", "", "nan"])
def test_a_non_numeric_lease_wait_is_null_with_a_note(tmp_path, value):
    rec, err = _run(tmp_path, "--requested-rung", "local-medium", "--rung", "sonnet-medium",
                    "--lease-wait-s", value)
    assert "lease_wait_s" in rec and rec["lease_wait_s"] is None
    assert f"lease-wait-s {value} ignored" in err


def test_consumer_row_is_a_sonnet_mirror_with_its_reason(tmp_path):
    rec, err = _run(tmp_path, *CONSUMER, "--fallback", "unrouted")
    assert (rec["served_rung"], rec["fallback"], rec["lease_wait_s"]) == (
        "sonnet-mirror", "unrouted", 0.0)
    assert err == ""


def test_router_down_twin_is_a_sonnet_mirror_too(tmp_path):
    rec, _ = _run(tmp_path, *CONSUMER, "--fallback", "unreachable")
    assert (rec["served_rung"], rec["fallback"]) == ("sonnet-mirror", "unreachable")
