"""test_certify_ledger_render.py — `ledger render` / `verify`, snapshot-pinned (N10).

design: audit-pass-does-not-bind (Task 9.4; detailed-design.md §Interfaces [B], N10).

One ledger row per inventory row; `unverified:cap` and `unverified:budget` are
distinct statuses; a `## Self-certification` table; a header carrying the
certified SHA and the inventory's sha256. `verify` re-renders from the
**committed** inventory + triage the header names (never a live scan of the
archive) and exits 1 on any mismatch. The `issues` half is pinned in
`test_certify_issues.py`.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import certify_ledger  # noqa: E402

SHA = "a" * 40
DATE = "2026-10-01"


def _row(n: int, design: str = "alpha") -> dict:
    return {"design": design, "file": f"three-pillars-docs/completed-tp-designs/{design}/x.md",
            "line": n, "phrase": "mutation-verified", "text": f"line {n} | mutation-verified"}


def _inventory() -> dict:
    rows = [_row(i) for i in range(1, 7)]
    return {"header": {"rows": len(rows), "designs": 1}, "rows": rows}


def _triage() -> dict:
    return {"claims": [{"id": s, "guard": f"skills/_shared/test_{s}.py", "property": "p",
                        "parameters": []} for s in ("s001", "s002", "s003", "s004")],
            "rows": [
                {"row": 1, "triage": "claim", "claim": "s001", "reason": "guard present"},
                {"row": 2, "triage": "claim", "claim": "s002", "reason": "guard present"},
                {"row": 3, "triage": "claim", "claim": "s003", "reason": "guard present"},
                {"row": 4, "triage": "not-a-claim", "reason": "a process note"},
                {"row": 5, "triage": "cap", "reason": "past the cap"},
                {"row": 6, "triage": "unverified", "reason": "guard vanished"},
            ]}


def _entry(cid: str, status: str, reasons=()) -> dict:
    return {"id": cid, "status": status, "reasons": list(reasons), "guard": f"g/{cid}.py"}


def _result(name: str, entries: list[dict], sha: str = SHA) -> dict:
    return {"complete": True, "name": name, "sha": sha, "disposition": "ledger",
            "claims": entries, "statuses": [e["status"] for e in entries], "orphans": [],
            "tree_mutated": False}


def _results() -> list[dict]:
    return [_result("sweep-01", [_entry("s001", "binds"), _entry("s002", "not-binding"),
                                 _entry("s003", "unverified", ["budget"])])]


def _self() -> dict:
    return _result("self", [_entry("c1", "binds"), _entry("c2", "unverified", ["cap"]),
                            _entry("c3", "known-bypass")])


def _stage(tmp_path: Path) -> tuple[Path, Path, Path]:
    design = tmp_path / "three-pillars-docs" / "tp-designs" / "demo"
    (design / "sweep").mkdir(parents=True)
    inv, tri = design / "sweep" / "inventory.json", design / "sweep" / "triage.json"
    inv.write_text(json.dumps(_inventory()), encoding="utf-8")
    tri.write_text(json.dumps(_triage()), encoding="utf-8")
    return design, inv, tri


def _render(tmp_path: Path, **kw) -> tuple[Path, str]:
    design, inv, tri = _stage(tmp_path)
    out = design / certify_ledger.LEDGER_NAME
    text = certify_ledger.render_ledger(inventory_path=inv, triage_path=tri, results=_results(),
                                        self_result=kw.get("self_result", _self()), out=out,
                                        date=DATE)
    out.write_text(text, encoding="utf-8")
    return out, text


def test_render_one_row_per_inventory_row_with_distinct_cap_and_budget(tmp_path):
    _out, text = _render(tmp_path)
    parsed = certify_ledger.parse_ledger(text)
    assert [r["row"] for r in parsed["rows"]] == list(range(1, 7))
    assert [r["status"] for r in parsed["rows"]] == [
        "binds", "not-binding", "unverified:budget", "not-a-claim", "unverified:cap", "unverified"]
    assert [r["claim"] for r in parsed["rows"]][:3] == ["sweep-01#s001", "sweep-01#s002",
                                                         "sweep-01#s003"]
    assert parsed["rows"][5]["reasons"] == "guard vanished"


def test_render_keys_a_claims_json_result_name_by_its_stem(tmp_path, monkeypatch):
    """T1: the certify-sweep runbook names results `sweep-NN.claims.json` / `self.claims.json`."""
    _out, bare = _render(tmp_path / "bare")
    named = [dict(r, name=f"{r['name']}.claims.json") for r in _results()]
    monkeypatch.setattr(sys.modules[__name__], "_results", lambda: named)
    _out, text = _render(tmp_path / "named", self_result=dict(_self(), name="self.claims.json"))
    assert text == bare and "sweep-01#s001" in text and ".claims.json#" not in text


def test_render_header_names_sha_and_inventory_digest(tmp_path):
    _out, text = _render(tmp_path)
    header = certify_ledger.parse_ledger(text)["header"]
    inv = tmp_path / "three-pillars-docs" / "tp-designs" / "demo" / "sweep" / "inventory.json"
    assert header["sha"] == SHA and header["date"] == DATE
    assert header["inventory"] == "sweep/inventory.json"
    assert header["inventory_sha256"] == hashlib.sha256(inv.read_bytes()).hexdigest()
    assert header["counts"]["unverified:cap"] == 1 and header["counts"]["unverified:budget"] == 1
    assert SHA in text and header["inventory_sha256"] in text


def test_render_self_certification_table(tmp_path):
    _out, text = _render(tmp_path)
    assert "\n## Self-certification\n" in text
    rows = certify_ledger.parse_ledger(text)["self_rows"]
    assert [(r["claim"], r["status"]) for r in rows] == [
        ("self#c1", "binds"), ("self#c2", "unverified:cap"), ("self#c3", "known-bypass")]


def test_render_parse_round_trips(tmp_path):
    _out, text = _render(tmp_path)
    parsed = certify_ledger.parse_ledger(text)
    model = certify_ledger.ledger_model(_inventory(), _triage(), _results(), _self())
    assert parsed["rows"] == model["rows"] and parsed["self_rows"] == model["self_rows"]
    assert parsed["rows"][0]["file"].endswith("x.md:1")


def test_render_escapes_pipes_in_cells(tmp_path):
    triage = _triage()
    triage["rows"][3]["reason"] = "a | b"
    model = certify_ledger.ledger_model(_inventory(), triage, _results(), None)
    text = certify_ledger.render_model(model, {"sha": SHA})
    assert certify_ledger.parse_ledger(text)["rows"][3]["reasons"] == "a | b"


def test_render_rejects_mixed_shas_and_untriaged_rows(tmp_path):
    design, inv, tri = _stage(tmp_path)

    def render(extra_sha: str) -> str:
        return certify_ledger.render_ledger(
            inventory_path=inv, triage_path=tri, self_result=None, out=design / "l.md",
            results=_results() + [_result("sweep-02", [], sha=extra_sha)], date=DATE)
    assert render(SHA)                    # the control: a second result at the same sha renders
    with pytest.raises(ValueError):
        render("b" * 40)
    certify_ledger.ledger_model(_inventory(), _triage(), _results(), None)  # the control
    short = _triage()
    short["rows"].pop()
    with pytest.raises(ValueError):
        certify_ledger.ledger_model(_inventory(), short, _results(), None)


def test_claim_row_without_a_result_is_unverified_no_result():
    model = certify_ledger.ledger_model(_inventory(), _triage(), [], None)
    assert model["rows"][0]["status"] == "unverified"
    assert model["rows"][0]["reasons"] == "no-result"


def _cli_verify(out: Path, tmp_path: Path, results=None, self_result=None) -> int:
    paths = []
    for i, res in enumerate(results if results is not None else _results()):
        p = tmp_path / f"r{i}.result.json"
        p.write_text(json.dumps(res), encoding="utf-8")
        paths += ["--result", str(p)]
    s = tmp_path / "self.result.json"
    s.write_text(json.dumps(self_result or _self()), encoding="utf-8")
    return certify_ledger.main(["ledger", "verify", "--ledger", str(out), *paths,
                                "--self-result", str(s)])


def test_verify_accepts_the_rendered_ledger(tmp_path):
    out, _text = _render(tmp_path)
    assert _cli_verify(out, tmp_path) == 0


def test_verify_exit_1_on_a_result_mismatch(tmp_path):
    out, _text = _render(tmp_path)
    flipped = _results()
    flipped[0]["claims"][1]["status"] = "binds"
    assert _cli_verify(out, tmp_path, results=flipped) == 1


def test_verify_exit_1_on_an_edited_ledger_or_inventory(tmp_path):
    out, text = _render(tmp_path)
    edited = re.sub(r"\|\s*not-binding\s*\|", "| binds |", text, count=1)
    assert edited != text
    out.write_text(edited, encoding="utf-8")
    assert _cli_verify(out, tmp_path) == 1
    out.write_text(text, encoding="utf-8")
    inv = out.parent / "sweep" / "inventory.json"
    inv.write_text(inv.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert _cli_verify(out, tmp_path) == 1


def test_verify_reads_the_committed_snapshot_not_a_live_inventory(tmp_path):
    """N10: a design archived after the snapshot, with certifying phrases, stays green."""
    out, _text = _render(tmp_path)
    late = tmp_path / "three-pillars-docs" / "completed-tp-designs" / "late-design"
    late.mkdir(parents=True)
    (late / "implementation-audit.md").write_text(
        "Every guard is mutation-verified and non-vacuous.\n", encoding="utf-8")
    assert _cli_verify(out, tmp_path) == 0


def test_render_cli_writes_the_ledger(tmp_path, capsys):
    design, inv, tri = _stage(tmp_path)
    res = tmp_path / "r.json"
    res.write_text(json.dumps(_results()[0]), encoding="utf-8")
    out = design / certify_ledger.LEDGER_NAME
    rc = certify_ledger.main(["ledger", "render", "--inventory", str(inv), "--triage", str(tri),
                              "--result", str(res), "--out", str(out), "--date", DATE])
    assert rc == 0
    assert certify_ledger.parse_ledger(out.read_text(encoding="utf-8"))["self_rows"] == []
    assert certify_ledger.main(["ledger", "verify", "--ledger", str(out),
                                "--result", str(res)]) == 0
