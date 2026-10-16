"""Tests for review_prep_cli_ab.py — the `shadow` and `ab-record` subcommands.

design: cheap-tier-review-prep (Task 7.5)
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_prep_cli    # noqa: E402 — first: it puts skills/_shared on sys.path
import dispatch_log       # noqa: E402
import round_scratch as rs  # noqa: E402

PR = "https://github.com/o/r/pull/42"
A1, A2 = "correctness-leak", "edge-cases"
SLICE = {"hunks": [{"file": "a.py", "hunk": "@@ -1 +1 @@\n-a\n+b\n"}]}
REFS  = {"refs":  [{"path": "a.py", "line": 1, "note": "n"}]}
DIFF  = "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n"
SPECS = {"review_slice": {"rung": "local-medium"},
         "review_refs":  {"rung": "local-medium"}}
VALID_REPLY = '```json\n{"findings": [{"file": "a.py", "class": "c1"}]}\n```\n'
PROSE_REPLY = "Looks fine, no issues found.\n"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _round(tmp_path):
    angles = [
        {"name": A1, "role": "confirmer", "model": "opus", "prompt": "Hunt leaks."},
        {"name": A2, "role": "finder",    "model": "opus", "prompt": "Hunt edge cases."},
    ]
    return rs.prepare(
        tmp_path / "proof", PR, angles,
        base="b0", head="h1", effort="high",
        state_path=str(tmp_path / "s.json"), log_path=str(tmp_path / "l.md"),
    )


def _work(tmp_path, accepted):
    adir = tmp_path / "W" / "accepted"
    adir.mkdir(parents=True, exist_ok=True)
    for name, obj in accepted.items():
        (adir / name).write_text(json.dumps(obj), encoding="utf-8")
    (tmp_path / "W" / "diff.patch").write_text(DIFF, encoding="utf-8")
    return tmp_path / "W"


def _specs_file(tmp_path):
    p = tmp_path / "specs.json"
    p.write_text(json.dumps(SPECS), encoding="utf-8")
    return p


def _setup_shadow(tmp_path):
    """Build round + shadow arm; returns (R, srep_by_name, real_by_name)."""
    R = _round(tmp_path)
    W = _work(tmp_path, {f"review_slice--{A1}.json": SLICE,
                         f"review_slice--{A2}.json": SLICE,
                         "review_refs--_.json": REFS})
    # Discard the shadow call's JSON line so only the ab-record line reaches capsys.
    with contextlib.redirect_stdout(io.StringIO()):
        review_prep_cli.main([
            "shadow", "--round-dir", str(R), "--work", str(W),
            "--specs", str(_specs_file(tmp_path)), "--root", str(tmp_path),
        ])
    shadow_man = json.loads((R / "prep" / "shadow" / "angles.json").read_text(encoding="utf-8"))
    real_man   = json.loads((R / "angles.json").read_text(encoding="utf-8"))
    return (R,
            {e["name"]: e for e in shadow_man["angles"]},
            {e["name"]: e for e in real_man["angles"]})


def _write_replies(R, srep, real, reply_map):
    """reply_map: {angle: {"real": text, "shadow": text}}"""
    for name, pair in reply_map.items():
        Path(real[name]["reply_path"]).write_text(pair["real"],   encoding="utf-8")
        Path(srep[name]["reply_path"]).write_text(pair["shadow"], encoding="utf-8")


def _ids_file(R, ids):
    (R / "prep" / "shadow" / "ids.json").write_text(json.dumps(ids), encoding="utf-8")


def _ndjson_rows(design):
    p = design / dispatch_log.NDJSON_NAME
    if not p.is_file():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _valid_pair():
    return {"real": VALID_REPLY, "shadow": VALID_REPLY}


# ---------------------------------------------------------------------------
# shadow
# ---------------------------------------------------------------------------

def test_shadow_moves_work_and_writes_manifest(tmp_path, capsys):
    R     = _round(tmp_path)
    W     = _work(tmp_path, {f"review_slice--{A1}.json": SLICE,
                             "review_refs--_.json": REFS})
    specs = _specs_file(tmp_path)
    rc = review_prep_cli.main(
        ["shadow", "--round-dir", str(R), "--work", str(W),
         "--specs", str(specs), "--root", str(tmp_path)])
    assert rc == 0
    res = json.loads(capsys.readouterr().out)
    assert res == {"shadow": str(R / "prep" / "shadow" / "angles.json")}
    assert (R / "prep" / "shadow" / "angles.json").is_file()
    assert not W.exists()
    assert (R / "prep" / "work" / "accepted").is_dir()


# ---------------------------------------------------------------------------
# ab-record — both angles valid
# ---------------------------------------------------------------------------

def test_ab_record_writes_paired_rows(tmp_path, capsys):
    R, srep, real = _setup_shadow(tmp_path)
    _write_replies(R, srep, real, {A1: _valid_pair(), A2: _valid_pair()})
    _ids_file(R, {
        A1: {"real": "agent-r1", "shadow": "agent-p1"},
        A2: {"real": "agent-r2", "shadow": "agent-p2"},
    })
    design = tmp_path / "design"
    design.mkdir()

    rc = review_prep_cli.main(["ab-record", "--round-dir", str(R),
                               "--design-dir", str(design)])
    assert rc == 0
    out = capsys.readouterr()
    # stdout is exactly one JSON line
    assert out.out.count("\n") == 1
    res = json.loads(out.out)
    assert sorted(res["recorded"]) == sorted([A1, A2])
    assert res["skipped"] == []

    rows = _ndjson_rows(design)
    for angle in (A1, A2):
        pair = f"rp:42:r1:{angle}"
        angle_rows = [r for r in rows if r.get("ab_pair") == pair]
        assert len(angle_rows) == 2, f"expected 2 rows for {angle}, got {len(angle_rows)}"
        assert {r["ab_arm"] for r in angle_rows} == {"base", "prep"}
        for r in angle_rows:
            assert r["oracle"] == "pass"
            assert r["rung"] == "opus"
            assert isinstance(r["findings"], dict)


# ---------------------------------------------------------------------------
# ab-record — one angle has an unparseable shadow reply
# ---------------------------------------------------------------------------

def test_ab_record_unparseable_shadow_reply(tmp_path, capsys):
    R, srep, real = _setup_shadow(tmp_path)
    _write_replies(R, srep, real, {
        A1: _valid_pair(),
        A2: {"real": VALID_REPLY, "shadow": PROSE_REPLY},  # unparseable
    })
    _ids_file(R, {
        A1: {"real": "agent-r1", "shadow": "agent-p1"},
        A2: {"real": "agent-r2", "shadow": "agent-p2"},
    })
    design = tmp_path / "design"
    design.mkdir()

    rc = review_prep_cli.main(["ab-record", "--round-dir", str(R),
                               "--design-dir", str(design)])
    assert rc == 0
    out = capsys.readouterr()
    res = json.loads(out.out)
    assert A1 in res["recorded"]
    assert A2 in res["skipped"]

    # Log records the unparseable angle
    log_path = json.loads((R / "angles.json").read_text(encoding="utf-8"))["paths"]["log_path"]
    assert f"ab-unparseable: {A2}" in Path(log_path).read_text(encoding="utf-8")

    # No ndjson row for A2's pair; A1's pair IS present
    rows = _ndjson_rows(design)
    assert not any(r.get("ab_pair") == f"rp:42:r1:{A2}" for r in rows)
    assert any(r.get("ab_pair") == f"rp:42:r1:{A1}"  for r in rows)
