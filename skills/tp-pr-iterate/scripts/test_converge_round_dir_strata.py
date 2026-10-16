"""converge --round-dir over parse_required pairs (local-role-routing 6.7)."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import converge  # noqa: E402
import converge_rounddir  # noqa: E402
import round_scratch  # noqa: E402

PR = "https://github.com/o/r/pull/7"
CLEAN = '{"findings": []}'
NOTE = {"file": "a.py", "line_range": [1, 2], "summary": "tighten", "verdict": "minor",
        "blocking": False, "class": "T"}


def _angle(name, check=False):
    if check:
        return {"name": name, "prompt": "p", "role": "confirmer", "model": "opus"}
    return {"name": name, "prompt": "p", "role": "finder", "model": "local",
            "advisory": True}


def _round(tmp_path, names, *, check=True):
    proof = tmp_path / "proof"
    angs = [_angle(n) for n in names] + ([_angle("opus-check", True)] if check else [])
    r = round_scratch.prepare(
        proof, PR, angs, base="b0", head="h1", effort="high",
        state_path=str(proof / "iterate-state.7.v1.json"),
        log_path=str(proof / "iterate-log.7.md"))
    (r / "tail" / "findings.json").write_text("[]", encoding="utf-8")
    m = json.loads((r / "angles.json").read_text(encoding="utf-8"))
    for e in m["angles"]:
        Path(e["reply_path"]).write_text(CLEAN, encoding="utf-8")
    return r, m


def _mutate(r, name, *, reply=None, **flags):
    mp = r / "angles.json"
    m = json.loads(mp.read_text(encoding="utf-8"))
    for e in m["angles"]:
        if e["name"] == name:
            e.update(flags)
            if reply is not None:
                Path(e["reply_path"]).write_text(reply, encoding="utf-8")
    mp.write_text(json.dumps(m), encoding="utf-8")


def _run(r, monkeypatch):
    seen = {}

    def finish(**kw):
        seen.update(kw)
        kw["out"].write(json.dumps({"converged": True}) + "\n")
        return 0

    monkeypatch.setattr(converge, "_finish_clean", finish)
    out = io.StringIO()
    rc = converge_rounddir.run(r, config={}, seams={"out": out, "err": io.StringIO(),
                                                    "repo_root": r})
    return rc, out.getvalue(), seen


def test_finders_without_check_refuse_no_confirmer(tmp_path, monkeypatch):
    r, _ = _round(tmp_path, ["a", "b"], check=False)
    rc, out, _ = _run(r, monkeypatch)
    assert rc == 2 and json.loads(out)["reason"] == "no-confirmer"


def test_finders_plus_parseable_check_sign(tmp_path, monkeypatch):
    r, _ = _round(tmp_path, ["a", "b"])
    rc, _out, seen = _run(r, monkeypatch)
    assert rc == 0 and len(seen["texts"]) == 3


def test_unmarked_unparseable_finder_refuses_naming_it(tmp_path, monkeypatch):
    for i, bad in enumerate(("prose only", "", '{"findings": [{"file"')):
        r, _ = _round(tmp_path / str(i), ["a", "b"])
        _mutate(r, "b", reply=bad)
        rc, out, _ = _run(r, monkeypatch)
        doc = json.loads(out)
        assert rc == 2 and doc["reason"] == "unparseable-review-angle"
        assert doc["detail"] == "b"


def test_marked_unparseable_finder_signs_and_digest_says_so(tmp_path, monkeypatch):
    r, _ = _round(tmp_path, ["a", "b"])
    _mutate(r, "b", reply="prose only", unparseable="re-covered-by-opus-check")
    rc, _out, seen = _run(r, monkeypatch)
    assert rc == 0
    labels = dict(seen["label_counts"])
    assert labels["b[local/finder] [unparseable: re-covered by opus-check]"] == 0
    assert "prose only" in seen["texts"]  # every text reaches the proof unchanged


def test_skipped_entry_between_finders_keeps_counts_on_own_name(tmp_path, monkeypatch):
    r, _ = _round(tmp_path, ["a", "mid", "c"])
    _mutate(r, "mid", skipped="out-of-scope")
    _mutate(r, "a", reply=json.dumps({"findings": [NOTE]}))
    _mutate(r, "c", reply=json.dumps({"findings": [NOTE, NOTE]}))
    rc, _out, seen = _run(r, monkeypatch)
    assert rc == 0
    counts = {k.split("[")[0]: v for k, v in seen["label_counts"]}
    assert (counts["a"], counts["mid"], counts["c"]) == (1, 0, 2)
