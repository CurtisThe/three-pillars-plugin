"""agent_caps.ledger_row and the escape ledger's `capped` count.

design: one-cheap-engine (Task 3.2). A capped agent gets one ledger row carrying
role, engine, design, span and tokens with `capped: true` and `kept: null` — the
Opus check step back-fills `kept` later (Task 3.4), so at cap time it is unknown.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_caps  # noqa: E402
import escape_ledger  # noqa: E402


def _row(**over):
    args = {"role": "review_finder", "engine": "local", "design": "one-cheap-engine",
            "span_s": 1610.5, "output_tokens": 262_143}
    args.update(over)
    return agent_caps.ledger_row(**args)


def test_ledger_row_fields():
    assert _row() == {"role": "review_finder", "engine": "local",
                      "design": "one-cheap-engine", "span_s": 1610.5,
                      "output_tokens": 262_143, "capped": True, "kept": None}


def test_ledger_row_rejects_a_role_with_no_cap_row():
    for role in ("tp-finalizer", "council-synth", "not-a-role"):
        try:
            _row(role=role)
        except (KeyError, ValueError):
            continue
        raise AssertionError(f"{role!r} has no cap row and must be refused")


def test_append_and_report_count_capped(tmp_path):
    d = tmp_path / "one-cheap-engine"
    finding_rows = [escape_ledger.row("review_finder", "local", "one-cheap-engine",
                                      "round-1", "perf#0", disp, "opus-check", None)
                    for disp in ("kept", "kept", "dropped")]
    escape_ledger.append(d, finding_rows + [_row()])
    lines = (d / escape_ledger.NDJSON_NAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    written = json.loads(lines[-1])
    assert written["capped"] is True and written["kept"] is None
    assert "disposition" not in written  # a cap row is not a finding disposition

    out = escape_ledger.report([d / escape_ledger.NDJSON_NAME])
    # The cap row is counted apart: it is not a finding disposition, so it is
    # outside n / kept / dropped and outside the escape rate.
    assert out["review_finder"] == {"n": 3, "kept": 2, "dropped": 1, "downgraded": 0,
                                    "opus_added": 0, "capped": 1, "escape_rate": 0.0}


def test_report_counts_a_capped_only_role(tmp_path):
    p = tmp_path / "l.ndjson"
    p.write_text(json.dumps(_row(role="council_member", engine="local")) + "\n",
                 encoding="utf-8")
    out = escape_ledger.report([p])
    assert out["council_member"]["capped"] == 1
    assert out["council_member"]["n"] == 0
    assert out["council_member"]["escape_rate"] is None


def test_capped_key_absent_when_nothing_was_capped(tmp_path):
    p = tmp_path / "l.ndjson"
    p.write_text(json.dumps(escape_ledger.row(
        "review_finder", "local", "d", "round-1", "perf#0", "kept",
        "opus-check", None)) + "\n", encoding="utf-8")
    assert "capped" not in escape_ledger.report([p])["review_finder"]
