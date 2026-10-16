"""escape_ledger.from_audit: synth envelope -> council_member rows."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import escape_ledger  # noqa: E402


def _env(items):
    return {"schema": "audit-return.v1", "escape_dispositions": items}


def test_three_rows_from_members_and_opus_added():
    env = _env([
        {"from": "skeptic#0", "disposition": "kept", "defect_class": "logic"},
        {"from": "pm#1", "disposition": "dropped"},
        {"from": None, "disposition": "opus-added", "defect_class": "gap"},
    ])
    rows = escape_ledger.from_audit(env, "plan-audit", "d1")
    assert len(rows) == 3
    for r in rows:
        assert r["role"] == "council_member"
        assert r["caught_by"] == "synth"
        assert r["step"] == "plan-audit"
        assert r["design"] == "d1"
        assert r["engine"] == "local"
    assert [r["finding_id"] for r in rows] == ["skeptic#0", "pm#1", None]
    assert rows[2]["disposition"] == "opus-added"
    assert rows[0]["defect_class"] == "logic"
    assert rows[1]["defect_class"] is None


def test_absent_key_gives_empty():
    assert escape_ledger.from_audit({"schema": "audit-return.v1"}, "s", "d") == []


def test_non_list_gives_empty():
    assert escape_ledger.from_audit(_env("nope"), "s", "d") == []


def test_bad_disposition_skipped_with_stderr_note(capsys):
    env = _env([
        {"from": "a#0", "disposition": "bogus"},
        "notadict",
        {"from": "a#1", "disposition": "kept"},
    ])
    rows = escape_ledger.from_audit(env, "s", "d")
    assert len(rows) == 1 and rows[0]["finding_id"] == "a#1"
    err = capsys.readouterr().err
    assert "escape_ledger: skipped escape_dispositions[0]:" in err
    assert "escape_ledger: skipped escape_dispositions[1]:" in err


def test_served_sonnet_busy_carried_and_absent_otherwise():
    env = _env([
        {"from": "a#0", "disposition": "kept", "served": "sonnet-busy"},
        {"from": "a#1", "disposition": "kept"},
    ])
    rows = escape_ledger.from_audit(env, "s", "d")
    assert rows[0]["served"] == "sonnet-busy"
    assert "served" not in rows[1]
