"""cert_mutant extract/merge and their CLI — one claim out, its re-run back in.

design: certifier-lean (Task 1.4; Behaviors 2, 3). Pure data: no repo, no runner, so
this file is tiered dev. `extract` cuts one claim plus its record out of the design's
claims file so the cert-fix task re-runs exactly that record; `merge` replaces only
that claim's entry in the original result, which is what lets the fold see `binds`
with no new certifier pass.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import cert_fold
import certify_cli
from cert_mutant import extract, merge

# dev-only fixture modules, guarded so a tree that ships without them skips.
test_certify_status = pytest.importorskip("test_certify_status")
claim = test_certify_status.claim
record = test_certify_status.record

# the fold keys a certification by (file, id) and only a `records/` name covers an
# envelope guard claim, so the fixture name is the design's own claims path.
NAME = "records/impl-audit.claims.json"


def doc(*claims) -> dict:
    return {"disposition": "verdict", "claims": list(claims)}


def result_from(*pairs) -> dict:
    """A certify result in `certify.certify_all`'s shape over `pairs` of (id, status)."""
    claims = [{"id": cid, "status": status, "reasons": [] if status == "binds" else ["why"],
               "evidence": {"red": [], "green": []}} for cid, status in pairs]
    return {"complete": True, "name": NAME, "sha": "a" * 40, "disposition": "verdict",
            "file_reasons": [], "claims": claims, "statuses": [s for _, s in pairs],
            "orphans": [], "tree_mutated": False}


def write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def cli(*argv) -> int:
    return certify_cli.main([str(a) for a in argv])


def by_id(result: dict) -> dict:
    return {c["id"]: c for c in result["claims"]}


# --- extract ---------------------------------------------------------------------------------

def test_extract_cuts_one_claim_and_its_record():
    c1, c2 = claim(id="c1"), claim(id="c2")
    r1, r2 = record(id="c1"), record(id="c2")
    one_doc, one_records = extract(doc(c1, c2), [r1, r2], "c2")
    assert one_doc == {"disposition": "verdict", "claims": [c2]}
    assert one_records == [r2]


def test_extract_never_edits_the_claims_file_or_the_records():
    """Behavior 2: the cert-fix task's proof is the same record, re-run, unedited."""
    input_doc = doc(claim(id="c1"), claim(id="c2"))
    input_records = [record(id="c1"), record(id="c2")]
    before = copy.deepcopy(input_doc), copy.deepcopy(input_records)
    extract(input_doc, input_records, "c1")
    assert (input_doc, input_records) == before


def test_extract_of_an_unknown_id_is_a_value_error():
    with pytest.raises(ValueError):
        extract(doc(claim()), [record()], "c9")


def test_extract_of_a_claim_with_no_record_has_no_records():
    one_doc, one_records = extract(doc(claim()), [], "c1")
    assert one_records == [] and len(one_doc["claims"]) == 1


def test_extract_of_a_malformed_doc_is_a_value_error():
    for bad in ({"disposition": "verdict"}, {"disposition": "verdict", "claims": "c1"}, None):
        with pytest.raises(ValueError):
            extract(bad, [record()], "c1")
    with pytest.raises(ValueError):
        extract(doc(claim()), {"id": "c1"}, "c1")


# --- merge -----------------------------------------------------------------------------------

def test_merge_replaces_only_the_override_claim():
    base = result_from(("c1", "not-binding"), ("c2", "binds"))
    merged = merge(base, [result_from(("c1", "binds"))])
    merged_claims = by_id(merged)
    assert merged_claims["c1"]["status"] == "binds"
    assert merged_claims["c1"]["reasons"] == []
    assert merged_claims["c2"] == by_id(base)["c2"]
    assert merged["statuses"] == ["binds", "binds"]
    assert merged["name"] == base["name"] and merged["complete"] is base["complete"]
    assert merged["sha"] == base["sha"]


def test_merge_never_edits_its_inputs():
    base, override = result_from(("c1", "not-binding")), result_from(("c1", "binds"))
    before = copy.deepcopy(base), copy.deepcopy(override)
    merge(base, [override])
    assert (base, override) == before


def test_merge_override_for_a_claim_the_result_lacks_is_a_value_error():
    with pytest.raises(ValueError):
        merge(result_from(("c1", "not-binding")), [result_from(("c9", "binds"))])


def test_merge_takes_the_tree_flag_from_either_side():
    mutated = result_from(("c1", "unverified"))
    mutated["tree_mutated"] = True
    base = result_from(("c1", "not-binding"))
    assert merge(base, [mutated])["tree_mutated"] is True
    assert merge(mutated, [result_from(("c1", "binds"))])["tree_mutated"] is True
    assert merge(base, [result_from(("c1", "binds"))])["tree_mutated"] is False


def test_merge_recomputes_statuses_from_the_claims():
    base = result_from(("c1", "binds"), ("c2", "not-binding"))
    base["statuses"] = ["not-binding", "not-binding"]
    merged = merge(base, [result_from(("c2", "binds"))])
    assert merged["statuses"] == [c["status"] for c in merged["claims"]]


def test_merge_refuses_an_incomplete_result():
    for bad in ({"complete": False, "claims": []}, {"complete": True}, []):
        with pytest.raises(ValueError):
            merge(bad, [])
    with pytest.raises(ValueError):
        merge(result_from(("c1", "binds")), [{"complete": False, "claims": []}])


def test_merged_result_folds_the_claim_as_binding():
    """Behavior 2: the fold sees `binds` for the re-run claim, no new certifier pass."""
    base = result_from(("c1", "not-binding"))
    unmerged = cert_fold.fold({"verdict": "pass", "status": "pass", "findings": []},
                              [base], [])
    assert unmerged["verdict"] == "needs-work"
    assert [f["category"] for f in unmerged["findings"]] == ["certification-note"]

    folded = cert_fold.fold({"verdict": "pass", "status": "pass", "findings": []},
                            [merge(base, [result_from(("c1", "binds"))])], [])
    assert folded["verdict"] == "pass" and folded["findings"] == []
    assert [(c["file"], c["id"], c["status"]) for c in folded["certifications"]] == [
        (NAME, "c1", "binds")]


# --- mutant-extract --------------------------------------------------------------------------

def test_cli_extract_writes_both_files(tmp_path, capsys):
    claims = write_json(tmp_path / NAME, doc(claim(id="c1"), claim(id="c2")))
    records = write_json(tmp_path / "records.json", [record(id="c1"), record(id="c2")])
    claims_out = tmp_path / "one.claims.json"
    records_out = tmp_path / "one.records.json"
    code = cli("mutant-extract", "--claims", claims, "--records", records, "--id", "c2",
               "--claims-out", claims_out, "--records-out", records_out)
    assert code == 0
    assert json.loads(claims_out.read_text(encoding="utf-8")) == doc(claim(id="c2"))
    assert json.loads(records_out.read_text(encoding="utf-8")) == [record(id="c2")]
    assert json.loads(capsys.readouterr().out)["claims"][0]["id"] == "c2"


def test_cli_extract_unknown_id_is_exit_2_and_writes_nothing(tmp_path):
    claims = write_json(tmp_path / NAME, doc(claim()))
    records = write_json(tmp_path / "records.json", [record()])
    claims_out = tmp_path / "one.claims.json"
    records_out = tmp_path / "one.records.json"
    code = cli("mutant-extract", "--claims", claims, "--records", records, "--id", "c9",
               "--claims-out", claims_out, "--records-out", records_out)
    assert code == 2
    assert not claims_out.exists() and not records_out.exists()


# --- mutant-merge ----------------------------------------------------------------------------

def test_cli_merge_writes_and_prints_the_merged_result(tmp_path, capsys):
    base = result_from(("c1", "not-binding"), ("c2", "binds"))
    out = tmp_path / "merged.json"
    code = cli("mutant-merge", "--result", write_json(tmp_path / "base.json", base),
               "--override", write_json(tmp_path / "over.json", result_from(("c1", "binds"))),
               "--out", out)
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["statuses"] == ["binds", "binds"]
    assert json.loads(out.read_text(encoding="utf-8")) == printed


def test_cli_merge_takes_several_overrides(tmp_path, capsys):
    base = result_from(("c1", "not-binding"), ("c2", "false-red"))
    code = cli("mutant-merge", "--result", write_json(tmp_path / "base.json", base),
               "--override", write_json(tmp_path / "o1.json", result_from(("c1", "binds"))),
               "--override", write_json(tmp_path / "o2.json", result_from(("c2", "binds"))),
               "--out", tmp_path / "m.json")
    assert code == 0
    assert json.loads(capsys.readouterr().out)["statuses"] == ["binds", "binds"]


def test_cli_merge_refuses_an_incomplete_result(tmp_path):
    bad = result_from(("c1", "binds"))
    bad["complete"] = False
    out = tmp_path / "m.json"
    code = cli("mutant-merge", "--result", write_json(tmp_path / "b.json", bad), "--out", out)
    assert code == 2
    assert not out.exists()
