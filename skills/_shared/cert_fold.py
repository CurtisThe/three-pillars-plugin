"""Fold certification results and phrase-scan hits into an audit-return envelope.

design: audit-pass-does-not-bind (Task 4.4; detailed-design.md §Interfaces [F2][E][R3];
N1, P4, P5). `fold` is called exactly once per audit return, with every
verdict-disposition certify result, so an envelope is never folded twice.

Order:
  1. strip any model-supplied `certifications`, `uncertified_phrases`,
     `certification_base` (status is never a model's call);
  2. base = VERDICT_FROM_ENVELOPE[verdict]; a model-supplied `unverified` or
     `known-bypass` becomes UNVERIFIED plus one `model-asserted` finding and one
     `uncertified_phrases` entry (so the schema's unverified rule holds);
  3. `certification_base` := base (traceability only, never read);
  4. `certifications[]` = one entry per claim of every verdict result, keyed
     (file, id); a `ledger` result (`certify_record.is_ledger_result`: sweep-named,
     no file reasons) never enters, any other result folds (F1), except [R9] the
     ledger claims whose guard path (before `::`) is in `verdict_guards` (the
     paths this candidate changed: `fold --verdict-guards`, F12; both sides compared in
     `certify_argv.norm` form, so `./a.py` / `a//a.py` match `a.py`). A (file, id) seen
     twice is a ValueError (F5): results need distinct names (e.g. a `records/`
     prefix). J1: each envelope `guard_claims[]` id with no entry from a
     `records/` result (the orchestrator-written claims path a candidate never
     carries, so a candidate file with the same id covers nothing) gets an
     `unverified` entry (file `guard_claims`, reason `no-result`): a lost result
     never drops a claim. `kept_ids` (certifier-lean B1, `fold --kept`) narrows that rule
     to the ids a claim lint kept, so a lint-dropped id folds nowhere at all.
     `uncertified_phrases[]` += each hit with `matched is False` (P5);
  5. verdict = combine_verdict(base, claim statuses + one "unverified" per
     counted hit). Status (N1/P4): `errored` / `handoff-pending` pass through
     for every folded verdict; otherwise status' = max(status, STATUS_FOR[verdict'])
     over pass < needs-work.

One finding per `not-binding`/`false-red` claim and per `unverified` claim whose
reasons are all claim-shape (`invalid:*`, `guard-is-subject`) — a note (category
`certification-note`, severity `minor`), never the finalizer path. Every other
`unverified` claim or counted hit keeps a `certification-unverified` finding.
A claim-shape-only `unverified` claim also folds like `not-binding` for the verdict
(never `unverified` — no record could bind a malformed claim), while its
`certifications[]` entry keeps status `unverified`. Other note categories leave the
folded verdict and status unchanged.
"""

from __future__ import annotations

import copy

from auto_verdict import combine_verdict
from certify_argv import norm
from certify_record import is_ledger_result

ENVELOPE_VERDICT = {
    "PASS": "pass",
    "PASS WITH NOTES": "pass-with-notes",
    "NEEDS WORK": "needs-work",
    "UNVERIFIED": "unverified",
    "KNOWN BYPASS": "known-bypass",
}
VERDICT_FROM_ENVELOPE = {
    "pass": "PASS",
    "pass-with-notes": "PASS WITH NOTES",
    "needs-work": "NEEDS WORK",
    "unverified": "UNVERIFIED",
    "known-bypass": "KNOWN BYPASS",
}
STATUS_FOR = {
    "pass": "pass",
    "pass-with-notes": "pass",
    "known-bypass": "pass",
    "needs-work": "needs-work",
    "unverified": "needs-work",
}
MODEL_ASSERTED = ("unverified", "known-bypass")
PASS_THROUGH_STATUSES = ("errored", "handoff-pending")
STATUS_RANK = {"pass": 0, "needs-work": 1}
STRIPPED = ("certifications", "uncertified_phrases", "certification_base")
GUARD_CLAIMS_FILE = "guard_claims"
NO_RESULT = "no-result"


def _finding(category: str, description: str, fix: str) -> dict:
    return {"confidence": "high", "category": category, "description": description,
            "suggested_fix": fix}


CLAIM_SHAPE_PREFIX = "invalid:"
CLAIM_SHAPE_REASONS = ("guard-is-subject",)


def _is_claim_shape(reason: str) -> bool:
    return reason.startswith(CLAIM_SHAPE_PREFIX) or reason in CLAIM_SHAPE_REASONS


def _all_claim_shape(reasons) -> bool:
    """True when a non-empty reason list is entirely about a malformed claim."""
    return bool(reasons) and all(_is_claim_shape(str(r)) for r in reasons)


def _note(description: str, fix: str) -> dict:
    finding = _finding("certification-note", description, fix)
    finding["severity"] = "minor"
    return finding


def _claim_finding(file: str, claim: dict) -> dict | None:
    status = claim["status"]
    raw_reasons = [str(r) for r in claim.get("reasons") or []]
    reasons = ", ".join(raw_reasons) or "none given"
    where = f"{file} [cert:{claim['id']}]"
    if status in ("not-binding", "false-red"):
        return _note(f"{where}: guard claim is {status} ({reasons}).",
                     "Fix the guard so it goes red on the violating input and green "
                     "on the correct one, or withdraw the claim.")
    if status == "unverified":
        if _all_claim_shape(raw_reasons):
            return _note(f"{where}: guard claim is unverified ({reasons}).",
                         "The claim itself is malformed, so no record could bind it: fix "
                         "the claim shape (guard path, subjects) and re-run "
                         "certification, or withdraw the claim.")
        return _finding("certification-unverified",
                        f"{where}: guard claim is unverified ({reasons}).",
                        "Obtain a certifier record and re-run certification, or withdraw "
                        "the claim.")
    return None


def _fold_status(status: str, verdict: str) -> str:
    if status in PASS_THROUGH_STATUSES:
        return status
    if status not in STATUS_RANK:
        raise ValueError(f"unknown envelope status {status!r}")
    return max(status, STATUS_FOR[verdict], key=STATUS_RANK.__getitem__)


def folded_claims(res: dict, verdict_guards=None) -> list[dict]:
    """The claim entries of one certify result that fold (module docstring, step 4)."""
    claims = [c for c in res.get("claims", []) if isinstance(c, dict)]
    if not is_ledger_result(res):
        return claims
    guards = {norm(g) for g in verdict_guards or ()}
    return [c for c in claims
            if isinstance(c.get("guard"), str) and norm(c["guard"].partition("::")[0]) in guards]


def uncovered_guard_claims(env: dict, certifications, kept_ids=None) -> list[str]:
    """J1: envelope guard-claim ids no `records/` result certified (module docstring, step 4).

    `kept_ids` (certifier-lean B1) is the set of ids the claim lint kept for the design's
    claims file: an envelope id outside it was dropped before any certifier ran, so it is
    a PR note, never a `no-result` entry. None (no lint ran) keeps the rule whole."""
    covered = {c["id"] for c in certifications if str(c["file"]).startswith("records/")}
    ids = [c.get("id") if isinstance(c, dict) else None for c in env.get("guard_claims") or []]
    if kept_ids is not None:
        ids = [cid for cid in ids if cid in kept_ids]
    return [str(cid) for cid in ids if cid not in covered]  # an id-less claim is never covered


def fold(env: dict, results: list[dict], hits: list[dict], verdict_guards=None,
         kept_ids=None) -> dict:
    """Return the post-fold envelope; `env`, `results` and `hits` are not mutated."""
    out = copy.deepcopy(env)
    for key in STRIPPED:
        out.pop(key, None)
    model_verdict = out.get("verdict")
    if model_verdict not in VERDICT_FROM_ENVELOPE:
        raise ValueError(f"unknown envelope verdict {model_verdict!r}")
    findings = list(out.get("findings") or [])
    phrases: list[dict] = []
    base = VERDICT_FROM_ENVELOPE[model_verdict]
    if model_verdict in MODEL_ASSERTED:
        base = "UNVERIFIED"
        findings.append(_finding(
            "certification-unverified",
            f"model-asserted: the audit returned verdict {model_verdict!r}; "
            "certification verdicts are set only by the certification fold.",
            "Return pass, pass-with-notes or needs-work and list guard claims instead."))
        phrases.append({"text": model_verdict, "field": "verdict", "reason": "model-asserted"})
    out["certification_base"] = base

    certifications: dict[tuple[str, str], dict] = {}
    for res in results:
        file = res.get("name", "")
        for claim in folded_claims(res, verdict_guards):
            if (file, claim["id"]) in certifications:  # F5: never overwrite a status
                raise ValueError(f"duplicate certification {file}#{claim['id']}")
            certifications[(file, claim["id"])] = {
                "file": file, "id": claim["id"], "status": claim["status"],
                "reasons": list(claim.get("reasons") or [])}
    for cid in uncovered_guard_claims(env, certifications.values(), kept_ids):
        certifications[(GUARD_CLAIMS_FILE, cid)] = {
            "file": GUARD_CLAIMS_FILE, "id": cid, "status": "unverified", "reasons": [NO_RESULT]}
    statuses = []
    for entry in certifications.values():
        # a claim-shape-only `unverified` claim folds like `not-binding`: no record
        # could bind a malformed claim, so the verdict never goes `unverified` (F2).
        # The certification entry keeps the status it came back with.
        if entry["status"] == "unverified" and _all_claim_shape(entry["reasons"]):
            statuses.append("not-binding")
        else:
            statuses.append(entry["status"])
        finding = _claim_finding(entry["file"], entry)
        if finding:
            findings.append(finding)

    for h in hits:
        if h.get("matched") is False:
            text, field = str(h.get("text", "")), str(h.get("field", ""))
            phrases.append({"text": text, "field": field})
            statuses.append("unverified")
            findings.append(_finding(
                "certification-unverified",
                f"uncertified phrase in {field or 'an unnamed field'}: {text!r} "
                "has no matching record.",
                "Tag the sentence with [cert:<id>] for a certified claim, or remove the "
                "certifying wording."))

    verdict, _code = combine_verdict(base, statuses)
    out["verdict"] = ENVELOPE_VERDICT[verdict]
    out["status"] = _fold_status(out.get("status"), out["verdict"])
    out["findings"] = findings
    out["certifications"] = list(certifications.values())
    out["uncertified_phrases"] = phrases
    return out
