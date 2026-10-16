"""cert_fix_plan — the cert-fix plan: one ladder task per `not-binding` claim.

design: certifier-lean (Task 1.5; Behavior 2). A `not-binding` or `false-red` claim
already has a record whose poles were observed; what failed is the guard, not the
record. So the fix is a dispatchable plan task, not a retry with advice: its **File**
is the guard alone, its **Targets** the guard's pytest target (or `none`), and its
**Red** carries every recorded pole verbatim, so the worker strengthens the guard
against the SAME record the certifier already ran. `certify.py mutant-oracle` (Task
1.4) is that task's `Done when`: exit 0 on the landed tree, no new certifier pass.

The text is written for the framework's own parsers, not for a human regex:
`task_eligibility.classify_phase` reads one dispatchable row per claim, `plan_files`
reads the **File** field as the guard path alone (never a subject), `task_oracle`
accepts the **Oracle** / **Entry point** pair (`none` only with **Targets** `none`).

CLI (`certify_cli_lean.MODULES`): `mutant-plan`.
"""

from __future__ import annotations

import json
import re

import certify_argv
import certify_cli
import ladder_rungs
from certify_cli import EXIT_OK, BadInput

PER_TASK_K = 20
INTRO = ("One ladder task per claim whose record was observed but whose guard did not "
         "bind: strengthen the guard so the recorded poles read as they already should.")
# A claim id is claimant-written and lands in a task heading the plan parsers read as
# structure, so only a plain token is ever rendered (every committed claims file fits).
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _claims_of(doc) -> dict:
    if not isinstance(doc, dict) or not isinstance(doc.get("claims"), list):
        raise ValueError("claims doc must be {disposition, claims: [...]}")
    return {c.get("id"): c for c in doc["claims"] if isinstance(c, dict)}


def _records_of(records) -> dict:
    if not isinstance(records, list):
        raise ValueError("records must be a JSON array")
    out: dict = {}
    for rec in records:
        if isinstance(rec, dict) and rec.get("id") not in out:
            out[rec["id"]] = rec
    return out


def _poles(rec) -> list[str]:
    return [json.dumps(pole, sort_keys=True) for pole in rec["red"] + rec["green"]]


def _markers(rec) -> list[str]:
    return [pole["expect"]["output_contains"] for pole in rec["red"]
            if pole.get("expect", {}).get("output_contains")]


def _task(k: int, claim: dict, rec: dict, start: str) -> str:
    guard = claim["guard"]
    path = guard.partition("::")[0]
    pytest_guard = certify_argv.is_pytest_guard(guard)
    targets = f"`{guard}`" if pytest_guard else "none"
    oracle = "example" if pytest_guard else "none"
    entry = f"`{guard}`" if pytest_guard else "none"
    poles = "\n".join(f"- `{pole}`" for pole in _poles(rec))
    markers = "\n".join(f"- `{marker}`" for marker in _markers(rec))
    return "\n".join([
        f"### Task 1.{k}: strengthen {path} (cert {claim.get('id')})",
        f"**File**: `{path}` (modify)",
        f"**Test**: the guard fails on each recorded RED pole below and passes on each "
        f"recorded GREEN pole and on the unmodified tree.",
        f"**Targets**: {targets}",
        f"**Oracle**: {oracle}",
        f"**Entry point**: {entry}",
        "**Red**: " + str(claim.get("property", "")) + " — the guard, not the record, is "
        "what failed. Every pole is recorded verbatim (RED then GREEN):",
        poles,
        "Rules: edit only the guard file. Each RED pole's failure output must contain its "
        "`expect.output_contains` marker, and that marker must stay literally in the guard "
        "file:",
        markers,
        "Never edit the subjects or the records.",
        "**Green**: None (one red-only commit)",
        f"**Start**: {start} — strengthen a guard against a recorded mutant",
        "**Done when**: Targets pass; `certify.py mutant-oracle` exits 0 on the landed tree.",
        "",
    ])


def plan_text(doc, records, ids, *, slug, start="local-xhigh") -> str:
    """The cert-fix plan: frontmatter, one phase, one task block per id."""
    if start not in ladder_rungs.RUNGS:
        raise ValueError(f"start {start!r} is not a ladder rung")
    claims, by_id = _claims_of(doc), _records_of(records)
    chosen = []
    for cid in ids:
        if not isinstance(cid, str) or not SAFE_ID.fullmatch(cid):
            raise ValueError(f"claim id {cid!r} is not a plain token")
        if cid not in claims:
            raise ValueError(f"no claim {cid!r} in the claims file")
        if cid not in by_id:
            raise ValueError(f"no record for claim {cid!r}")
        chosen.append((claims[cid], by_id[cid]))
    head = ["---", "weight-class: light", "plan-schema: 2", "---", "",
            f"# cert-fix plan for {slug}", "", INTRO, "",
            f"## Phase 1: cert-fix (~{PER_TASK_K * len(chosen)}k)", ""]
    body = [_task(k, claim, rec, start)
            for k, (claim, rec) in enumerate(chosen, start=1)]
    return "\n".join(head + body)


def cmd_plan(args) -> int:
    doc = certify_cli.load_json(args.claims)
    records = certify_cli.load_json(args.records)
    try:
        text = plan_text(doc, records, args.id, slug=args.slug, start=args.start)
    except ValueError as exc:
        raise BadInput(str(exc)) from exc
    certify_cli.write_atomic(args.out, text)
    return EXIT_OK


def register(sub) -> None:
    """Add `mutant-plan` (called by `certify_cli_lean`)."""
    plan = sub.add_parser("mutant-plan", help="render the cert-fix plan for claim ids")
    plan.add_argument("--claims", required=True)
    plan.add_argument("--records", required=True)
    plan.add_argument("--id", action="append", required=True)
    plan.add_argument("--slug", required=True)
    plan.add_argument("--start", default="local-xhigh")
    plan.add_argument("--out", required=True)
    plan.set_defaults(func=cmd_plan)
