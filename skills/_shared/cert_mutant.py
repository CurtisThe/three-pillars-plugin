"""cert_mutant — re-run one claim's records: the cert-fix task's oracle.

design: certifier-lean (Task 1.4; Behaviors 2, 3). A `not-binding` or `false-red`
claim gets one ladder task ("strengthen <guard> so it fails each recorded RED pole and
passes each recorded GREEN pole"). Its proof is mechanical, not a model's judgement:

  `extract` cuts the one claim plus its record out of the design's claims file, so the
  task re-runs exactly that record and never the whole file;
  `oracle` runs that pair through `certify.certify_all` at a ref — no pole logic here,
  every status is the engine's — and reports whether it now binds;
  `merge` puts the re-run entry back into the ORIGINAL result, replacing only that
  claim's entry, so the fold sees `binds` with no new certifier pass.

The records are never edited anywhere on this path: `extract` and `merge` copy, and the
oracle reads the claims and records files. A re-run that still does not bind exits 1 and
the claim stays the cert-fix task's problem; a tree mutation is exit 3 (tampering,
never a gap), matching `certify.py run`.

CLI (`certify_cli_lean.MODULES`): `mutant-extract`, `mutant-oracle`, `mutant-merge`.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import certify
import certify_cli
from certify_cli import EXIT_INVALID, EXIT_MUTATED, EXIT_OK, BadInput

SUMMARY_KEYS = ("id", "status", "reasons", "binds", "tree_mutated")


def _claims_of(doc) -> list:
    """`doc["claims"]` when the doc is the `{disposition, claims: [...]}` shape."""
    if not isinstance(doc, dict) or not isinstance(doc.get("claims"), list):
        raise ValueError("claims doc must be {disposition, claims: [...]}")
    return doc["claims"]


def _result_of(res) -> dict:
    """A complete certify result (`complete` literally true, claims a list)."""
    if not isinstance(res, dict) or res.get("complete") is not True:
        raise ValueError("incomplete certify result (complete is not true)")
    if not isinstance(res.get("claims"), list):
        raise ValueError("certify result has no claims list")
    return res


# --- one claim out ---------------------------------------------------------------------------

def extract(doc, records, cid) -> tuple[dict, list]:
    """`({disposition, claims: [the claim]}, [its records])` for claim id `cid`.

    Copies, so the design's claims file and its records stay untouched (the task's
    proof is the same record, re-run). Unknown `cid` → ValueError; a claim with no
    record yields `[]` (the oracle then reads `unverified`, never `binds`).
    """
    claims = _claims_of(doc)
    if not isinstance(records, list):
        raise ValueError("records must be a JSON array")
    found = [c for c in claims if isinstance(c, dict) and c.get("id") == cid]
    if not found:
        raise ValueError(f"no claim {cid!r} in the claims file")
    doc1 = {"disposition": doc.get("disposition"), "claims": copy.deepcopy(found[:1])}
    return doc1, copy.deepcopy([r for r in records
                                if isinstance(r, dict) and r.get("id") == cid])


# --- re-run it -------------------------------------------------------------------------------

def oracle(doc1, records1, *, repo, sha, name, budget_s=480, watch_refs=None,
           runner=subprocess.run) -> dict:
    """`{id, status, reasons, binds, tree_mutated, result}` for one extracted claim.

    `certify.certify_all` is the whole engine: no pole, marker or exit rule is
    re-implemented here, so `binds` means exactly what it means in a full pass.
    """
    claims = _claims_of(doc1)
    if len(claims) != 1:
        raise ValueError("the oracle certifies exactly one claim")
    cid = claims[0].get("id") if isinstance(claims[0], dict) else None
    result = certify.certify_all(doc1, records1, repo=repo, sha=sha, name=name,
                                 budget_s=budget_s, watch_refs=watch_refs, runner=runner)
    entry = next((c for c in result["claims"] if c.get("id") == cid), None)
    if entry is None:
        raise ValueError(f"the result has no entry for claim {cid!r}")
    status = entry.get("status")
    return {"id": cid, "status": status, "reasons": list(entry.get("reasons") or []),
            "binds": status == "binds", "tree_mutated": bool(result["tree_mutated"]),
            "result": result}


# --- put the re-run back ---------------------------------------------------------------------

def merge(result, overrides) -> dict:
    """`result` with each override's claim entries substituted (a deep copy).

    An override id absent from `result` is a ValueError: a re-run certifies a claim the
    design already has, it never adds one. `statuses` is recomputed from the merged
    claims, and `tree_mutated` is true if any side saw a mutation (fail closed).
    """
    out = copy.deepcopy(_result_of(result))
    replacements: dict = {}
    for override in overrides:
        over = _result_of(override)
        for entry in over["claims"]:
            cid = entry.get("id") if isinstance(entry, dict) else None
            if not any(c.get("id") == cid for c in out["claims"] if isinstance(c, dict)):
                raise ValueError(f"override claim {cid!r} is not in the result")
            replacements[cid] = copy.deepcopy(entry)
        out["tree_mutated"] = bool(out.get("tree_mutated")) or bool(
            over.get("tree_mutated"))
    out["claims"] = [replacements.get(c["id"], c) if isinstance(c, dict) else c
                     for c in out["claims"]]
    out["statuses"] = [c["status"] for c in out["claims"] if isinstance(c, dict)]
    return out


# --- the subcommands -------------------------------------------------------------------------

def cmd_extract(args) -> int:
    doc = certify_cli.load_json(args.claims)
    records = certify_cli.load_json(args.records)
    try:
        doc1, records1 = extract(doc, records, args.id)
    except ValueError as exc:
        raise BadInput(str(exc)) from exc
    certify_cli.write_atomic(args.records_out, json.dumps(records1, indent=2) + "\n")
    certify_cli.emit(args.claims_out, doc1)
    return EXIT_OK


def cmd_oracle(args) -> int:
    doc = certify_cli.load_json(args.claims)
    records = certify_cli.load_json(args.records)
    sha = certify_cli.resolve_ref(args.repo, args.ref)
    try:
        out = oracle(doc, records, repo=args.repo, sha=sha,
                     name=args.name or Path(args.claims).name, budget_s=args.budget_s,
                     watch_refs=args.watch_ref or None)
    except ValueError as exc:
        raise BadInput(str(exc)) from exc
    if args.out:
        certify_cli.write_atomic(args.out, json.dumps(out["result"], indent=2) + "\n")
    certify_cli.emit(None, {key: out[key] for key in SUMMARY_KEYS})
    if out["tree_mutated"]:
        return EXIT_MUTATED
    return EXIT_OK if out["binds"] else EXIT_INVALID


def cmd_merge(args) -> int:
    result = certify_cli.load_json(args.result)
    overrides = [certify_cli.load_json(path) for path in args.override]
    try:
        merged = merge(result, overrides)
    except ValueError as exc:
        raise BadInput(str(exc)) from exc
    certify_cli.emit(args.out, merged)
    return EXIT_OK


def register(sub) -> None:
    """Add the three mutant subcommands (called by `certify_cli_lean`)."""
    extract_cmd = sub.add_parser("mutant-extract",
                                 help="cut one claim and its records out of a claims file")
    extract_cmd.add_argument("--claims", required=True)
    extract_cmd.add_argument("--records", required=True)
    extract_cmd.add_argument("--id", required=True)
    extract_cmd.add_argument("--claims-out", required=True)
    extract_cmd.add_argument("--records-out", required=True)
    extract_cmd.set_defaults(func=cmd_extract)
    oracle_cmd = sub.add_parser("mutant-oracle", help="re-run one claim's records at a ref")
    oracle_cmd.add_argument("--claims", required=True)
    oracle_cmd.add_argument("--records", required=True)
    oracle_cmd.add_argument("--repo", required=True)
    oracle_cmd.add_argument("--ref", required=True)
    oracle_cmd.add_argument("--name")
    oracle_cmd.add_argument("--watch-ref", action="append", default=[])
    oracle_cmd.add_argument("--budget-s", type=float, default=480)
    oracle_cmd.add_argument("--out")
    oracle_cmd.set_defaults(func=cmd_oracle)
    merge_cmd = sub.add_parser("mutant-merge", help="fold a re-run back into a result")
    merge_cmd.add_argument("--result", required=True)
    merge_cmd.add_argument("--override", action="append", default=[])
    merge_cmd.add_argument("--out")
    merge_cmd.set_defaults(func=cmd_merge)
