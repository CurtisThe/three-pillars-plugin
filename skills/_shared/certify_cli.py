"""certify_cli — the `certify.py` command line: `validate`, `run` and `fold`.

design: audit-pass-does-not-bind (Tasks 3.6, 5.3; detailed-design.md §Interfaces, N13, R3, P5).

    certify.py validate --claims C [--records R] --ref SHA [--repo P] [--name N]
    certify.py run --claims C (--records R | --unverified REASON) --repo P --ref SHA
                   [--name N] [--watch-ref GLOB]... [--max-claims N] [--budget-s S]
                   [--artifact A] [--out F]
    certify.py fold --envelope E [--result R]... --slot {4|8}
                    [--member-summaries M] [--verdict-guards G] [--kept K] --out F
    certify.py lint --claims C --ref SHA [--repo P] [--name N]
                    [--light] [--diff F] [--kept-out K]

`fold` [R3] is the only caller of `cert_fold.fold`, once per audit return:
strip the model-supplied certification keys → `cert_phrase_scan.scan_envelope`
→ one `fold` over every result. A result whose `complete` is not `true` is bad
input (exit 2) and nothing is folded. A `[cert:<id>]` tag can match only a
claim that has a verdict result (fail-closed), and the tag alone binds [R9];
the claim's guard path (which a council member field must name) comes from the
result entry, else from the envelope's `guard_claims`. `--verdict-guards G` is a
file of repo paths, one per line (`git diff --no-renames --name-only tp/{slug}...S`,
so a guard renamed away is listed at its old path): a ledger claim whose guard path
is listed folds as verdict [R9]. `fold` reads no repo: Slot 4 and Slot 8 keep
every hit alike. `run --artifact A` prints `{result, hits, verdict, code}`: the
markdown phrase scan of A plus `combine_verdict(PASS, statuses + one
unverified per counted hit)` (interactive audits).

Every path argument (`--claims`, `--records`, `--out`, `--result` ...) is a FILE, never a
directory: `--records` is a JSON list of records, `fold --out` a file written atomically.
Each subcommand's `--help` says so (`state_shapes`).

`validate` is the certifier's dry-run gate: without `--records` it checks claim
shape + disposition only (no repo access); with `--records` it also validates
each claim's record against the guard text at `--ref`. Exit 1 on any invalid.

`run` certifies every claim (`certify.certify_all`) and prints the result JSON.
`run --unverified {records-handoff,claimant-records}` reads no records and runs
no pole: every claim is `unverified` with that reason, the fail-closed result a
handoff or claimant-record failure folds as (F6). `handoff`, `claimant-check`
and `scan` live in `certify_cli_checks`.
Exit 0 completed, 2 bad input (unreadable / malformed JSON, unknown ref,
argparse errors, an unwritable `--out`), 3 caller tree mutated. `--out` is written only on
completion and atomically [N13]: the after-fingerprint is taken first (inside
`certify_all`), then a temp file is created in `--out`'s own directory (made if missing) and
`os.replace`d into place — so an `--out` inside `--repo` never reads as a
mutation, a killed run leaves no `--out`, and no cross-filesystem rename is
needed; if the rename still reports EXDEV, the bytes are copied to a second
temp file in the destination dir and that one is replaced atomically.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cert_fold
import cert_phrase_scan
import certify
import certify_record
import certify_scratch
from auto_verdict import combine_verdict

EXIT_OK, EXIT_INVALID, EXIT_BAD_INPUT, EXIT_MUTATED = 0, 1, 2, 3


class BadInput(Exception):
    """Input the CLI cannot certify at all (exit 2)."""


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise BadInput(f"{path}: {exc}") from exc


def resolve_ref(repo, ref) -> str:
    try:
        out = certify_scratch.git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                                  cwd=repo, env=certify_scratch.scrubbed_env())
    except (OSError, subprocess.SubprocessError) as exc:
        raise BadInput(f"cannot resolve --ref {ref} in {repo}") from exc
    return out.strip()


def write_atomic(out, text: str) -> None:
    """Temp file in `out`'s directory (created if missing), then `os.replace` (EXDEV:
    copy, replace). Any OSError is bad input (exit 2), never a traceback."""
    try:
        _write_atomic(Path(out), text)
    except OSError as exc:
        raise BadInput(f"cannot write --out {out}: {exc}") from exc


def _write_atomic(out: Path, text: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    temps = []
    try:
        fd, tmp = tempfile.mkstemp(prefix=f".{out.name}.", suffix=".tmp", dir=out.parent)
        temps.append(tmp)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.replace(tmp, out)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            fd2, tmp2 = tempfile.mkstemp(prefix=f".{out.name}.", suffix=".tmp", dir=out.parent)
            os.close(fd2)
            temps.append(tmp2)
            shutil.copyfile(tmp, tmp2)
            os.replace(tmp2, out)
    finally:
        for path in temps:
            if os.path.exists(path):
                os.unlink(path)


def _claims(doc) -> list:
    claims = doc.get("claims") if isinstance(doc, dict) else None
    return claims if isinstance(claims, list) else []


def cmd_validate(args) -> int:
    doc = load_json(args.claims)
    name = args.name or Path(args.claims).name
    report = {"file": certify_record.validate_claims_doc(doc, name), "claims": []}
    if args.records:
        records = load_json(args.records)
        if not isinstance(records, list):
            raise BadInput("--records must be a JSON array")
        sha = resolve_ref(args.repo, args.ref)
        by_id = {r.get("id"): r for r in records if isinstance(r, dict)}
        for claim in _claims(doc):
            cid = claim.get("id") if isinstance(claim, dict) else None
            _valid, _text, reasons = certify.prepare(claim, by_id.get(cid), repo=args.repo,
                                                     sha=sha)
            report["claims"].append({"id": cid, "reasons": reasons})
    print(json.dumps(report, indent=2))
    invalid = report["file"] or any(c["reasons"] for c in report["claims"])
    return EXIT_INVALID if invalid else EXIT_OK


def load_result(path) -> dict:
    """A certify result; `complete` must be literally `true` (else exit 2, no fold)."""
    res = load_json(path)
    if not isinstance(res, dict) or res.get("complete") is not True:
        raise BadInput(f"{path}: incomplete certify result (complete is not true)")
    if not isinstance(res.get("claims"), list):
        raise BadInput(f"{path}: certify result has no claims list")
    return res


def returned_claims(env: dict, results: list[dict], verdict_guards=None) -> list[dict]:
    """`{id, guard}` for every claim with a verdict result — the only matchable tags.

    `guard` (None when neither the result nor `guard_claims` names one) is read only
    for council member fields; a tag binds by id alone [R9]."""
    declared = {c.get("id"): c.get("guard") for c in env.get("guard_claims") or []
                if isinstance(c, dict)}
    out = []
    for res in results:
        for item in cert_fold.folded_claims(res, verdict_guards):
            guard = item.get("guard") or declared.get(item.get("id"))
            out.append({"id": item.get("id"), "guard": guard if isinstance(guard, str) else None})
    return out


def counted(hits: list[dict]) -> list[dict]:
    """Hits that escalate (P5): the unmatched ones."""
    return [h for h in hits if h.get("matched") is False]


def artifact_report(result: dict, text: str) -> dict:
    hits = cert_phrase_scan.scan(text, returned_claims({}, [result]))
    statuses = [] if certify_record.is_ledger_result(result) else list(result["statuses"])
    verdict, code = combine_verdict("PASS", statuses + ["unverified"] * len(counted(hits)))
    return {"result": result, "hits": hits, "verdict": verdict, "code": code}


def emit(out, payload) -> None:
    text = json.dumps(payload, indent=2) + "\n"
    if out:
        write_atomic(out, text)
    sys.stdout.write(text)


def cmd_fold(args) -> int:
    env = load_json(args.envelope)
    if not isinstance(env, dict):
        raise BadInput("--envelope must be a JSON object")
    results = [load_result(path) for path in args.result]
    members = load_json(args.member_summaries) if args.member_summaries else []
    if not isinstance(members, list):
        raise BadInput("--member-summaries must be a JSON array")
    guards = None
    if args.verdict_guards:
        try:
            text = Path(args.verdict_guards).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise BadInput(f"{args.verdict_guards}: {exc}") from exc
        guards = {line.strip() for line in text.splitlines() if line.strip()}
    kept_ids = None
    if args.kept:
        kept = load_json(args.kept)
        kept_ids = {c.get("id") for c in _claims(kept) if isinstance(c, dict)}
    stripped = {k: v for k, v in env.items() if k not in cert_fold.STRIPPED}
    try:
        hits = cert_phrase_scan.scan_envelope(stripped, members, slot=args.slot,
                                              claims=returned_claims(stripped, results, guards))
        folded = cert_fold.fold(env, results, hits, verdict_guards=guards,
                                kept_ids=kept_ids)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise BadInput(f"cannot fold: {exc}") from exc
    emit(args.out, folded)
    return EXIT_OK


def cmd_run(args) -> int:
    doc = load_json(args.claims)
    if bool(args.records) == bool(args.unverified):
        raise BadInput("run needs exactly one of --records or --unverified")
    records = load_json(args.records) if args.records else []
    artifact = None
    if args.artifact:
        try:
            artifact = Path(args.artifact).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise BadInput(f"{args.artifact}: {exc}") from exc
    sha = resolve_ref(args.repo, args.ref)
    try:
        result = certify.certify_all(
            doc, records, repo=args.repo, sha=sha, name=args.name or Path(args.claims).name,
            max_claims=args.max_claims, budget_s=args.budget_s,
            watch_refs=args.watch_ref or None, unverified=args.unverified,
        )
    except ValueError as exc:
        raise BadInput(str(exc)) from exc
    emit(args.out, result if artifact is None else artifact_report(result, artifact))
    return EXIT_MUTATED if result["tree_mutated"] else EXIT_OK


# Path arguments, for `--help` only (no argument is added, removed or retyped): flag -> the help
# used when its subcommand gives none. Every one is a FILE; the two DIR flags name a directory.
FILE_HELP = {
    "--claims": "claims FILE: one JSON claims document",
    "--records": "records FILE: a JSON list of records",
    "--out": "FILE to write",
    "--result": "a certify result FILE",
    "--envelope": "audit envelope JSON FILE",
    "--artifact": "markdown artifact FILE",
    "--member-summaries": "FILE holding a JSON list of member summaries",
    "--verdict-guards": "FILE of repo paths, one per line",
    "--certifier-return": "certifier return envelope JSON FILE",
    "--claims-out": "FILE to write the claims document to",
    "--records-out": "FILE to write the JSON list of records to",
    "--override": "a re-run result FILE (repeatable)",
}
FILE_FLAGS = (*FILE_HELP, "--kept", "--kept-out", "--diff", "--folded", "--route", "--lint",
              "--cert-path")
DIR_HELP = {"--design": "design directory, relative to --repo", "--design-dir": "design directory"}


def state_shapes(sub) -> None:
    """Make each subcommand's `--help` say which arguments are files (never directories).

    Runs last in `build_parser`, so it also covers the subcommands that sibling modules register."""
    for parser in sub.choices.values():
        files = []
        for act in parser._actions:
            flag = act.option_strings[0] if act.option_strings else ""
            if flag in FILE_FLAGS:
                act.metavar, act.help = "FILE", act.help or FILE_HELP.get(flag)
                files.append(flag)
            elif flag in DIR_HELP:
                act.metavar, act.help = "DIR", act.help or DIR_HELP[flag]
        if files:
            parser.epilog = "Path arguments are files, not a directory." + (
                " A records FILE is a JSON list of records." if any("records" in f for f in files)
                else "")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="certify.py", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    val = sub.add_parser("validate", help="validate a claims file (and its records)")
    val.add_argument("--claims", required=True)
    val.add_argument("--records")
    val.add_argument("--ref", required=True)
    val.add_argument("--repo", default=".")
    val.add_argument("--name")
    val.set_defaults(func=cmd_validate)
    run = sub.add_parser("run", help="certify every claim of one claims file")
    run.add_argument("--claims", required=True)
    run.add_argument("--records")
    run.add_argument("--unverified", choices=certify.FORCED_REASONS)
    run.add_argument("--repo", required=True)
    run.add_argument("--ref", required=True)
    run.add_argument("--name")
    run.add_argument("--watch-ref", action="append", default=[])
    run.add_argument("--max-claims", type=int, default=certify_record.MAX_CLAIMS)
    run.add_argument("--budget-s", type=float, default=480)
    run.add_argument("--artifact")
    run.add_argument("--out")
    run.set_defaults(func=cmd_run)
    fold = sub.add_parser("fold", help="scan and fold every result into one audit return")
    fold.add_argument("--envelope", required=True)
    fold.add_argument("--result", action="append", default=[])
    fold.add_argument("--slot", type=int, choices=cert_phrase_scan.SLOTS, required=True)
    fold.add_argument("--member-summaries")
    fold.add_argument("--verdict-guards")
    fold.add_argument("--kept", help="a lint --kept-out doc: only its ids can be uncovered")
    fold.add_argument("--out", required=True)
    fold.set_defaults(func=cmd_fold)
    import certify_cli_checks  # deferred: it imports this module

    certify_cli_checks.register(sub)
    import certify_cli_lean  # deferred: each lean module imports this one

    certify_cli_lean.register(sub)
    state_shapes(sub)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BadInput as exc:
        print(f"certify: bad input: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
