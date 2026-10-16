"""cert_route — one action per folded Step 2b return (design certifier-lean, Behaviors 2, 3).

Table-driven: every case is a folded envelope in `cert_fold.fold`'s output shape and the
assertion is the action the orchestrator takes (Task 1.3). Pure function plus the
`certify.py route` CLI. Tiered dev (pure logic, no repo).
"""

from __future__ import annotations

import json

import pytest

import cert_route
import certify_cli
import cert_once
from cert_fold import GUARD_CLAIMS_FILE

FILE = "records/impl-audit.claims.json"
KEY = f"{FILE}#c1"


def cert(cid, status, *reasons, file=FILE):
    return {"file": file, "id": cid, "status": status, "reasons": list(reasons)}


def env(certs, base="PASS", phrases=()):
    return {"verdict": base, "status": "pass", "certification_base": base,
            "certifications": list(certs), "uncertified_phrases": list(phrases),
            "findings": []}


def decide(certs, base="PASS", phrases=(), followed=()):
    return cert_route.decide(env(certs, base, phrases), followed=frozenset(followed))


# --- every claim binds ---------------------------------------------------------------------

def test_all_binds_proceeds():
    out = decide([cert("c1", "binds"), cert("c2", "binds")])
    assert out["route"] == "proceed"
    assert out["continue_verdict"] == "pass"
    assert out["escalate"] is None and out["retry"] is None
    assert out["cert_fix"] is None and out["gaps"] == [] and out["notes"] == []


@pytest.mark.parametrize("base,certs", [
    ("PASS WITH NOTES", [cert("c1", "binds")]),  # the auditor's own notes
    ("PASS", [cert("c1", "binds"), cert("c2", "known-bypass")]),
])
def test_proceed_keeps_the_folded_notes_verdict(base, certs):
    out = decide(certs, base=base)
    assert out["route"] == "proceed"
    assert out["continue_verdict"] == "pass-with-notes"


def test_no_certifications_proceeds():
    out = cert_route.decide({"verdict": "PASS", "status": "pass",
                             "certification_base": "PASS", "uncertified_phrases": [],
                             "findings": []})
    assert out["route"] == "proceed"
    assert out["continue_verdict"] == "pass"


# --- Behavior 2: not-binding / false-red is one cert-fix task -------------------------------

@pytest.mark.parametrize("status,reason", [("not-binding", "red-guard-holds"),
                                           ("false-red", "green-guard-red")])
def test_not_binding_is_cert_fix(status, reason):
    out = decide([cert("c1", status, reason)])
    assert out["route"] == "cert-fix"
    assert out["cert_fix"] == {"key": KEY, "file": FILE, "id": "c1"}
    assert out["retry_with_advice"] is False
    assert out["continue_verdict"] is None
    assert out["retry"] is None


def test_not_binding_beside_other_findings_keeps_retry_with_advice():
    out = decide([cert("c1", "not-binding", "red-guard-holds")], base="NEEDS WORK")
    assert out["route"] == "cert-fix"
    assert out["retry_with_advice"] is True
    assert out["continue_verdict"] is None


@pytest.mark.parametrize("status", ["not-binding", "false-red"])
def test_followed_not_binding_is_a_note(status):
    out = decide([cert("c1", status, "red-guard-holds")], followed=[KEY])
    assert out["notes"] == [{"key": KEY, "file": FILE, "id": "c1", "status": status,
                             "reasons": ["red-guard-holds"]}]
    assert out["cert_fix"] is None
    assert out["route"] == "proceed"
    assert out["continue_verdict"] == "pass-with-notes"


# --- Behavior 3: unverified gets exactly one retry ------------------------------------------

@pytest.mark.parametrize("reasons,mode", [
    (["budget"], "rerun"),
    (["red-timeout"], "rerun"),
    (["exception:OSError"], "rerun"),
    (["no-record"], "reauthor"),
    (["marker-not-in-guard"], "reauthor"),
    (["budget", "no-record"], "reauthor"),
])
def test_unverified_retry_mode(reasons, mode):
    out = decide([cert("c1", "unverified", *reasons)])
    assert out["route"] == "retry"
    assert out["retry"] == {"key": KEY, "file": FILE, "id": "c1", "mode": mode}


def test_no_result_is_reauthor():
    out = decide([cert("c1", "unverified", "no-result", file=GUARD_CLAIMS_FILE)])
    assert out["route"] == "retry"
    assert out["retry"] == {"key": f"{GUARD_CLAIMS_FILE}#c1", "file": GUARD_CLAIMS_FILE,
                            "id": "c1", "mode": "reauthor"}


def test_followed_unverified_is_a_gap():
    out = decide([cert("c1", "unverified", "no-record")], followed=[KEY])
    assert out["route"] == "cert-gap"
    assert out["gaps"] == [{"key": KEY, "file": FILE, "id": "c1", "reasons": ["no-record"]}]
    assert out["retry"] is None
    assert out["continue_verdict"] == "pass-with-notes"


# --- tamper and unmatched phrases escalate --------------------------------------------------

@pytest.mark.parametrize("reason", ["tree-mutated", "claimant-records", "records-handoff"])
@pytest.mark.parametrize("is_followed", [False, True])
def test_escalations(reason, is_followed):
    followed = [KEY] if is_followed else []
    out = decide([cert("c1", "unverified", reason)], followed=followed)
    assert out["route"] == "escalate"
    assert out["escalate"]["reason"] == reason
    assert out["retry"] is None and out["gaps"] == []


def test_uncertified_phrase_escalates():
    phrase = {"text": "verified by the guard", "field": "summary",
              "reason": "uncertified-phrase"}
    out = decide([cert("c1", "binds")], phrases=[phrase])
    assert out["route"] == "escalate"
    assert out["escalate"]["reason"] == "uncertified-phrase"


def test_claim_shape_unverified_is_a_note():
    out = decide([cert("c1", "unverified", "invalid:guard")])
    assert out["notes"] and out["notes"][0]["key"] == KEY
    assert out["retry"] is None and out["gaps"] == []
    assert out["route"] == "proceed"


# --- precedence ------------------------------------------------------------------------------

def test_precedence():
    escalate_first = cert_route.decide(env([cert("c1", "unverified", "tree-mutated"),
                                            cert("c2", "not-binding", "red-guard-holds")]))
    assert escalate_first["route"] == "escalate"

    retry_first = cert_route.decide(env([cert("c1", "unverified", "no-record"),
                                         cert("c2", "not-binding", "red-guard-holds")]))
    assert retry_first["route"] == "retry"
    assert retry_first["cert_fix"] == {"key": "records/impl-audit.claims.json#c2",
                                       "file": FILE, "id": "c2"}

    fix_first = cert_route.decide(env([cert("c1", "not-binding", "red-guard-holds"),
                                       cert("c2", "unverified", "no-record")]),
                                  followed={"records/impl-audit.claims.json#c2"})
    assert fix_first["route"] == "cert-fix"


# --- the CLI ---------------------------------------------------------------------------------

def test_cli(tmp_path, capsys):
    design = tmp_path / "design"
    design.mkdir()
    folded = tmp_path / "folded.json"
    payload = env([cert("c1", "unverified", "no-record")])
    folded.write_text(json.dumps(payload), encoding="utf-8")

    assert cert_once.followup(design, KEY) is True
    code = certify_cli.main(["route", "--folded", str(folded),
                             "--design-dir", str(design)])
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["route"] == "cert-gap"
    assert printed["gaps"][0]["key"] == KEY

    out_file = tmp_path / "route.json"
    code = certify_cli.main(["route", "--folded", str(folded),
                             "--design-dir", str(design), "--out", str(out_file)])
    assert code == 0
    capsys.readouterr()
    assert json.loads(out_file.read_text(encoding="utf-8")) == printed

    missing = certify_cli.main(["route", "--folded", str(tmp_path / "nope.json"),
                                "--design-dir", str(design)])
    assert missing == 2
