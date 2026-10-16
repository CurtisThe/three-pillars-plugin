"""cert_route — turn one folded Step 2b return into one action (`certify.py route`).

design: certifier-lean (Task 1.3; design.md Behaviors 2, 3).

`decide` reads a folded envelope (the shape `cert_fold.fold` emits) plus the claim keys
that already spent their one follow-up run (`cert_once.followed`), and names the single
action the orchestrator takes:

- `escalate` — a tamper reason (`tree-mutated`, `claimant-records`, `records-handoff`)
  on an `unverified` claim, followed or not, or any `uncertified_phrases` entry:
  tampering, and certifying wording no claim covers, are never a gap.
- `retry` — an unfollowed `unverified` claim: mode `rerun` when every reason is
  transient (budget, red-timeout, `exception:*`) so its records can simply run again,
  else `reauthor` (`no-result` included: no record exists, so nothing can be re-run).
- `cert-fix` — an unfollowed `not-binding`/`false-red` claim: one ladder task
  (Behavior 2). `retry_with_advice` says whether the base verdict still needs it too.
- `cert-gap` — a followed `unverified` claim: its one retry was spent, so the run
  continues and the claim becomes the PR note + `tp:cert-gap` (Behavior 3).
- `proceed` — everything binds. A claim-shape `unverified` claim and a followed
  cert-fix claim are notes, never findings.

Precedence: escalate > retry > cert-fix > cert-gap > proceed, so the reported action
is the highest one present while every other finding stays listed.
`retry_with_advice` is the base verdict's own call (`certification_base == "NEEDS WORK"`
means findings other than the certification ones still drive the old path);
`continue_verdict` is what a `proceed` / `cert-gap` run continues with: `pass-with-notes`
when the auditor's own base is PASS WITH NOTES, a claim is `known-bypass`, or a gap or
note exists, else `pass`.
"""
from __future__ import annotations

import cert_fold
import cert_once
import certify_cli
from certify_cli import EXIT_OK, BadInput

TAMPER = ("tree-mutated", "claimant-records", "records-handoff")
TRANSIENT = ("budget", "red-timeout")
EXCEPTION_PREFIX = "exception:"
CERT_FIX = ("not-binding", "false-red")
UNCERTIFIED_PHRASE = "uncertified-phrase"
ESCALATE, RETRY, FIX, GAP, PROCEED = ("escalate", "retry", "cert-fix", "cert-gap", "proceed")


def _reasons(cert) -> list[str]:
    return [str(r) for r in cert.get("reasons") or []]


def _is_transient(reasons) -> bool:
    return bool(reasons) and all(
        r in TRANSIENT or r.startswith(EXCEPTION_PREFIX) for r in reasons)


def _classify(cert, followed) -> tuple[str, dict | None]:
    """(kind, payload) for one `certifications[]` entry (module docstring)."""
    entry = {"key": f"{cert['file']}#{cert['id']}", "file": cert["file"], "id": cert["id"]}
    status, reasons = cert.get("status"), _reasons(cert)
    if status == "unverified":
        tamper = next((r for r in reasons if r in TAMPER), None)
        if tamper is not None:
            return ESCALATE, {**entry, "reason": tamper}
        if cert_fold._all_claim_shape(reasons):
            return "note", {**entry, "status": status, "reasons": reasons}
        if entry["key"] in followed:
            return GAP, {**entry, "reasons": reasons}
        return RETRY, {**entry, "mode": "rerun" if _is_transient(reasons) else "reauthor"}
    if status in CERT_FIX:
        if entry["key"] in followed:
            return "note", {**entry, "status": status, "reasons": reasons}
        return FIX, entry
    return PROCEED, None


def decide(folded, *, followed=frozenset()) -> dict:
    """The one action for a folded envelope (module docstring)."""
    escalate = retry = cert_fix = None
    gaps: list[dict] = []
    notes: list[dict] = []
    for phrase in folded.get("uncertified_phrases") or ():
        if escalate is None:
            escalate = {"key": None,
                        "reason": str(phrase.get("reason") or UNCERTIFIED_PHRASE)}
    for cert in folded.get("certifications") or ():
        kind, payload = _classify(cert, followed)
        if kind == ESCALATE and escalate is None:
            escalate = payload
        elif kind == RETRY and retry is None:
            retry = payload
        elif kind == FIX and cert_fix is None:
            cert_fix = payload
        elif kind == GAP:
            gaps.append(payload)
        elif kind == "note":
            notes.append(payload)
    if escalate is not None:
        route = ESCALATE
    elif retry is not None:
        route = RETRY
    elif cert_fix is not None:
        route = FIX
    elif gaps:
        route = GAP
    else:
        route = PROCEED
    base = folded.get("certification_base")
    advice = base == "NEEDS WORK"
    noted = (gaps or notes or base == "PASS WITH NOTES"
             or any(c.get("status") == "known-bypass"
                    for c in folded.get("certifications") or ()))
    verdict = None
    if route in (PROCEED, GAP) and not advice:
        verdict = "pass-with-notes" if noted else "pass"
    return {"route": route, "escalate": escalate, "retry": retry, "cert_fix": cert_fix,
            "gaps": gaps, "notes": notes, "retry_with_advice": advice,
            "continue_verdict": verdict}


def cmd_route(args) -> int:
    folded = certify_cli.load_json(args.folded)
    if not isinstance(folded, dict):
        raise BadInput("--folded must be a JSON object")
    followed = cert_once.followed(args.design_dir) if args.design_dir else set()
    certify_cli.emit(args.out, decide(folded, followed=frozenset(followed)))
    return EXIT_OK


def register(sub) -> None:
    """Add `route` to `certify.py`'s subparsers (called by `certify_cli_lean`)."""
    route = sub.add_parser("route", help="one action for a folded Step 2b return")
    route.add_argument("--folded", required=True, help="the folded envelope JSON")
    route.add_argument("--design-dir", help="design dir holding the follow-up ledger")
    route.add_argument("--out", help="write the decision JSON here too")
    route.set_defaults(func=cmd_route)
