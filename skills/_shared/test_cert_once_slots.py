"""Per-slot once-markers and the one-follow-up-per-claim ledger.

Design: certifier-lean 1.2 (Behaviors 3, 5). Slot 8 keeps today's marker name
and default behaviour; the Slot 8 full pass and the Slot 4 check pass get
separate markers, a light design never runs a Slot 4 full pass, and every
claim key buys at most one follow-up run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cert_once  # noqa: E402


def test_slot8_default_unchanged(tmp_path):
    assert cert_once.should_run(tmp_path) is True
    cert_once.mark(tmp_path)
    marker = tmp_path / "certify-once.json"
    assert marker.exists()
    assert json.loads(marker.read_text(encoding="utf-8"))["slot"] == 8
    assert cert_once.should_run(tmp_path) is False
    assert cert_once.should_run(tmp_path, slot=4) is True


def test_slot4_has_its_own_marker(tmp_path):
    cert_once.mark(tmp_path, slot=4)
    marker = tmp_path / "certify-once-slot4.json"
    assert marker.exists()
    assert json.loads(marker.read_text(encoding="utf-8"))["slot"] == 4
    assert cert_once.should_run(tmp_path, slot=4) is False
    assert cert_once.should_run(tmp_path, slot=8) is True


def test_light_never_runs_slot4(tmp_path):
    assert cert_once.should_run(tmp_path, slot=4, light=True) is False
    assert cert_once.should_run(tmp_path, slot=8, light=True) is True


def test_followup_once_per_claim(tmp_path):
    key1 = "records/impl-audit.claims.json#c1"
    key2 = "records/impl-audit.claims.json#c2"
    assert cert_once.followup(tmp_path, key1) is True
    assert cert_once.followup(tmp_path, key1) is False
    assert cert_once.followup(tmp_path, key2) is True
    assert cert_once.followed(tmp_path) == {key1, key2}
    ledger = tmp_path / "certify-retries.json"
    assert isinstance(json.loads(ledger.read_text(encoding="utf-8")), list)


def test_followed_empty_without_ledger(tmp_path):
    assert cert_once.followed(tmp_path) == set()


def test_cli_should_run_skips_light_slot4(tmp_path, capsys):
    code = cert_once.main(
        ["should-run", "--design-dir", str(tmp_path), "--slot", "4", "--light"]
    )
    assert code == 1
    assert "should-run: skip" in capsys.readouterr().out


def test_cli_mark_slot4_then_followup_once(tmp_path):
    assert cert_once.main(["mark", "--design-dir", str(tmp_path), "--slot", "4"]) == 0
    assert (tmp_path / "certify-once-slot4.json").exists()

    assert cert_once.main(["followup", "--design-dir", str(tmp_path), "--claim", "f#c1"]) == 0
    assert cert_once.main(["followup", "--design-dir", str(tmp_path), "--claim", "f#c1"]) == 1
    assert cert_once.followed(tmp_path) == {"f#c1"}


def test_cli_followup_missing_dir_exits_two(tmp_path):
    code = cert_once.main(
        ["followup", "--design-dir", str(tmp_path / "absent"), "--claim", "f#c1"]
    )
    assert code == 2


def test_cli_rejects_unknown_slot(tmp_path):
    try:
        cert_once.main(["should-run", "--design-dir", str(tmp_path), "--slot", "5"])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("--slot 5 accepted")
