"""escape_ledger.report and the CLI."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import escape_ledger  # noqa: E402


def _r(disp, role="review_finder", served=None):
    return escape_ledger.row(role, "local", "d", "s", "f", disp, "opus-check",
                             None, served=served)


def _ledger(tmp_path, rows, name="l.ndjson"):
    p = tmp_path / name
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


BASE = [_r("kept")] * 3 + [_r("dropped"), _r("opus-added")]


def test_counts_and_escape_rate(tmp_path):
    out = escape_ledger.report([_ledger(tmp_path, BASE)])
    assert out == {"review_finder": {"n": 5, "kept": 3, "dropped": 1,
                                     "downgraded": 0, "opus_added": 1,
                                     "escape_rate": 0.25}}


def test_rate_none_without_kept_or_added(tmp_path):
    out = escape_ledger.report([_ledger(tmp_path, [_r("dropped")])])
    assert out["review_finder"]["escape_rate"] is None
    assert out["review_finder"]["n"] == 1


def test_busy_rows_excluded_and_counted(tmp_path):
    rows = BASE + [_r("kept", served="sonnet-busy"),
                   _r("opus-added", served="sonnet-busy")]
    out = escape_ledger.report([_ledger(tmp_path, rows)])
    assert out["review_finder"] == {"n": 5, "kept": 3, "dropped": 1,
                                    "downgraded": 0, "opus_added": 1,
                                    "escape_rate": 0.25, "sonnet_busy": 2}


def test_all_busy_role(tmp_path):
    rows = [_r("kept", "council_member", "sonnet-busy")] * 3
    out = escape_ledger.report([_ledger(tmp_path, rows)])
    assert out["council_member"]["n"] == 0
    assert out["council_member"]["escape_rate"] is None
    assert out["council_member"]["sonnet_busy"] == 3


def test_skips_bad_lines_and_missing_files(tmp_path):
    p = tmp_path / "l.ndjson"
    bad = dict(_r("kept"), disposition="weird")
    p.write_text("\nnot json\n" + json.dumps(bad) + "\n"
                 + json.dumps(_r("kept")) + "\n", encoding="utf-8")
    out = escape_ledger.report([p, tmp_path / "nope.ndjson"])
    assert out["review_finder"]["n"] == 1


def test_main_report_prints_json(tmp_path, capsys):
    p = _ledger(tmp_path, BASE)
    assert escape_ledger.main(["report", str(p)]) == 0
    assert json.loads(capsys.readouterr().out)["review_finder"]["n"] == 5


def test_main_append_audit(tmp_path, capsys):
    env = tmp_path / "env.json"
    env.write_text(json.dumps({"escape_dispositions": [
        {"from": "a#0", "disposition": "kept"}]}), encoding="utf-8")
    d = tmp_path / "des"
    rc = escape_ledger.main(["append-audit", "--envelope", str(env),
                             "--slot", "plan-audit", "--design-dir", str(d)])
    assert rc == 0
    assert "appended 1" in capsys.readouterr().out
    lines = (d / "escape-ledger.ndjson").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["step"] == "plan-audit"
    assert json.loads(lines[0])["design"] == "des"


def test_main_append_audit_bad_envelope(tmp_path, capsys):
    rc = escape_ledger.main(["append-audit", "--envelope",
                             str(tmp_path / "missing.json"), "--slot", "s",
                             "--design-dir", str(tmp_path / "des")])
    assert rc == 1
    assert capsys.readouterr().err


def test_main_append_review(tmp_path, capsys):
    rd = tmp_path / "round-1"
    (rd / "opus-check").mkdir(parents=True)
    (rd / "opus-check" / "reply.md").write_text(json.dumps({"findings": [
        {"escape": {"from": "x#0", "disposition": "kept"}}]}), encoding="utf-8")
    (rd / "opus-check" / "dispositions.json").write_text(
        json.dumps({"dropped": []}), encoding="utf-8")
    d = tmp_path / "des"
    rc = escape_ledger.main(["append-review", "--round-dir", str(rd),
                             "--design-dir", str(d)])
    assert rc == 0
    assert "appended 1" in capsys.readouterr().out
    assert (d / "escape-ledger.ndjson").exists()
