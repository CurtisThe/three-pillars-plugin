"""cert_mutant.oracle and `certify.py mutant-oracle` — the cert-fix task's oracle.

design: certifier-lean (Task 1.4; Behavior 2). One claim and its record are cut out of
the design's claims file and re-run through the real engine (`certify.certify_all`) in
a real temp repo: a guard that stays silent on the violating input reads `not-binding`
(exit 1), the SAME record against the strengthened guard reads `binds` (exit 0), and the
records file is never edited. Real repos and the real runner (test_certify_scratch
helpers, git_env), so this file is tiered dev (P3).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import certify_cli
from cert_mutant import oracle

# dev-only fixture modules, guarded so a tree that ships without them skips.
test_certify_scratch = pytest.importorskip("test_certify_scratch")
test_certify_status = pytest.importorskip("test_certify_status")
make_repo = test_certify_scratch.make_repo
commit_files = test_certify_scratch.commit_files
FILES = test_certify_status.FILES
GUARD = test_certify_status.GUARD
MARKER = test_certify_status.MARKER
claim = test_certify_status.claim
record = test_certify_status.record

NAME = "impl-audit.claims.json"
# the weak guard names the marker in a comment but never fails: its RED pole passes.
WEAK = "import sys\n# " + MARKER + "\nsys.exit(0)\n"


def doc() -> dict:
    return {"disposition": "verdict", "claims": [claim()]}


def write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def cli(*argv) -> int:
    return certify_cli.main([str(a) for a in argv])


@pytest.fixture
def weak_repo(tmp_path):
    return make_repo(tmp_path / "caller", {**FILES, GUARD: WEAK})


@pytest.fixture
def inputs(tmp_path):
    scratch = tmp_path / "scratch"
    claims = write_json(scratch / NAME, doc())
    records = write_json(scratch / "records.json", [record()])
    return scratch, claims, records


# --- a weak guard is not-binding -------------------------------------------------------------

def test_weak_guard_is_not_binding(weak_repo, inputs):
    path, sha = weak_repo
    out = oracle(doc(), [record()], repo=path, sha=sha, name=NAME)
    assert out["id"] == "c1" and out["status"] == "not-binding"
    assert out["binds"] is False and out["tree_mutated"] is False
    assert out["reasons"] == ["red-guard-holds"]
    assert out["result"]["statuses"] == ["not-binding"]


def test_cli_weak_guard_exits_1(weak_repo, inputs, capsys):
    path, _sha = weak_repo
    _scratch, claims, records = inputs
    assert cli("mutant-oracle", "--claims", claims, "--records", records,
               "--repo", path, "--ref", "HEAD") == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "not-binding" and printed["binds"] is False
    assert "result" not in printed, "the pole evidence stays out of the summary"


# --- the strengthened guard binds ------------------------------------------------------------

def test_strengthened_guard_binds(weak_repo, inputs, capsys):
    """The same record, unedited, at a HEAD whose guard fails on the violating input."""
    path, weak_sha = weak_repo
    _scratch, claims, records = inputs
    before = records.read_bytes()
    assert oracle(doc(), [record()], repo=path, sha=weak_sha, name=NAME)["binds"] is False

    strong_sha = commit_files(path, {GUARD: test_certify_status.GUARD_TEXT})
    out = oracle(doc(), [record()], repo=path, sha=strong_sha, name=NAME)
    assert out["binds"] is True and out["status"] == "binds" and out["reasons"] == []

    result_out = _scratch / "oracle.result.json"
    code = cli("mutant-oracle", "--claims", claims, "--records", records, "--repo", path,
               "--ref", "HEAD", "--name", NAME, "--budget-s", "240", "--out", result_out)
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "binds" and printed["binds"] is True
    written = json.loads(result_out.read_text(encoding="utf-8"))
    assert written["statuses"] == ["binds"] and written["complete"] is True
    assert records.read_bytes() == before, "the oracle never edits the records"


# --- bad input -------------------------------------------------------------------------------

def test_unknown_ref_is_bad_input(weak_repo, inputs, capsys):
    path, _sha = weak_repo
    _scratch, claims, records = inputs
    assert cli("mutant-oracle", "--claims", claims, "--records", records,
               "--repo", path, "--ref", "deadbeef") == 2
    capsys.readouterr()


def test_unreadable_claims_is_bad_input(weak_repo, tmp_path):
    path, _sha = weak_repo
    assert cli("mutant-oracle", "--claims", tmp_path / "absent.claims.json",
               "--records", write_json(tmp_path / "r.json", [record()]),
               "--repo", path, "--ref", "HEAD") == 2


def test_a_claim_with_no_record_is_unverified_not_binding(weak_repo, tmp_path):
    """`not-binding` needs a record; without one the oracle reports unverified (exit 1)."""
    path, sha = weak_repo
    out = oracle(doc(), [], repo=path, sha=sha, name=NAME)
    assert (out["status"], out["reasons"]) == ("unverified", ["no-record"])
    assert out["binds"] is False
