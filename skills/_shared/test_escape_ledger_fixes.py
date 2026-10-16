"""escape_ledger.py (impl-audit retry 2): staging, robustness, busy tag.

design: local-role-routing (Task 3.6). The ledger file name is one constant
`wrapup_paths.WRAPUP` stages; the CLI runs clean under `python3 -I`; a
non-UTF-8 check reply logs `ledger-incomplete` instead of raising; the
check-dir / reply literals equal `finder_round.CHECK_NAME` and
`round_scratch.REPLY` (the drift guard); and a round whose manifest tags a
finder `served: "sonnet-busy"` (Task 6.10's `mark-busy`) propagates that tag
onto the finder's escape rows, which `report` then excludes.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tp-pr-iterate" / "scripts"))

import escape_ledger  # noqa: E402
import finder_round  # noqa: E402
import round_scratch  # noqa: E402

ESCAPE_LEDGER_PY = HERE / "escape_ledger.py"


def test_ndjson_name_constant_and_wrapup_staging():
    import wrapup_paths

    assert escape_ledger.NDJSON_NAME == "escape-ledger.ndjson"
    assert escape_ledger.NDJSON_NAME in wrapup_paths.WRAPUP


def test_cli_runs_under_isolated_python(tmp_path):
    empty = tmp_path / "nothing.ndjson"
    result = subprocess.run(
        [sys.executable, "-I", str(ESCAPE_LEDGER_PY), "report", str(empty)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}


def test_check_dir_and_reply_literals_match_tp_pr_iterate():
    assert escape_ledger.CHECK_DIR == finder_round.CHECK_NAME
    assert escape_ledger.REPLY == round_scratch.REPLY


def _round(tmp_path, reply_bytes, manifest=None):
    r = tmp_path / "round-1"
    (r / escape_ledger.CHECK_DIR).mkdir(parents=True)
    (r / escape_ledger.CHECK_DIR / escape_ledger.REPLY).write_bytes(reply_bytes)
    if manifest is not None:
        (r / escape_ledger.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    return r


def test_non_utf8_reply_logs_incomplete_without_raising(tmp_path, capsys):
    r = _round(tmp_path, b"\xff\xfe not valid utf-8 \x80")
    rows = escape_ledger.from_review(r, "d")
    assert rows == []
    assert "ledger-incomplete" in capsys.readouterr().err


def test_manifest_sonnet_busy_tags_rows_and_report_excludes_them(tmp_path):
    reply = json.dumps({
        "findings": [
            {"class": "sec", "escape": {"from": "security#0", "disposition": "kept"}},
        ],
    }).encode("utf-8")
    manifest = {"angles": [{"name": "security", "served": "sonnet-busy"},
                           {"name": "perf"}]}
    r = _round(tmp_path, reply, manifest)

    rows = escape_ledger.from_review(r, "d")
    assert len(rows) == 1
    assert rows[0]["served"] == "sonnet-busy"

    ledger = tmp_path / "ledger.ndjson"
    ledger.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    out = escape_ledger.report([str(ledger)])
    # excluded from n/kept/dropped/escape_rate; counted only as sonnet_busy
    assert out["review_finder"]["sonnet_busy"] == 1
    assert out["review_finder"]["n"] == 0
    assert out["review_finder"]["kept"] == 0
    assert out["review_finder"]["escape_rate"] is None
