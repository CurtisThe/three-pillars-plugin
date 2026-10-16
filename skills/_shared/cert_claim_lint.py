"""cert_claim_lint — check a claims file before any certifier dispatch (`certify.py lint`).

design: certifier-lean (Task 1.1; design.md Behaviors 1, 4).

A claim that `certify.prepare` would refuse for its shape or its resolution at the
certified SHA never reaches a certifier: `lint` reports one `<id>: <reason>` line for it
and drops it, keeping the passing claims in the auditor's order in a `--kept-out` doc.
Every reason comes from the same functions `prepare` uses (`certify_record.claim_reasons`,
`certify.guard_file_reasons`, `certify.read_guard_at_sha`, `certify.is_file_at`) — never a
re-implementation — plus `no-subjects`, the reason `certify_record` gives for a claim that
declares no subject allowlist (`prepare` reaches it only through a record). A file-level
reason (`file: <reason>`: a disposition that contradicts the file name, or `cap` past
`certify_record.MAX_CLAIMS`) drops every claim of the file.

On `light` (a `weight-class: light` design) two rules more apply, so such a design
certifies only guards its own diff touched: `light:subject-not-in-diff` when no subject is
a production file in the design diff (`is_production` — never a test module, a
`conftest.py` or a path under `three-pillars-docs/`), then `light:over-cap` past the 6th
passing claim (`LIGHT_CAP`), keeping the auditor's order. Without `light` neither rule
runs: a full design's count and selection are unchanged (Behavior 4).

CLI (registered by `certify_cli_lean`):

    certify.py lint --claims C --ref SHA [--repo P] [--name N]
                    [--light] [--diff F] [--kept-out K]

prints `{ok, lines, dropped}` and writes the kept doc to `--kept-out`; exit 0 with no
line, 1 with any, 2 on bad input (unreadable or malformed JSON, an unknown ref, `--light`
without `--diff`). `fold --kept` reads that kept doc, so a lint-dropped id is a PR note
and never folds `unverified` (`no-result`).
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import certify
import certify_cli
import certify_record
from certify_argv import guard_parts
from certify_cli import EXIT_INVALID, EXIT_OK, BadInput

LIGHT_CAP = 6
DOCS_ROOT = "three-pillars-docs"
LIGHT_NO_DIFF = "lint --light needs --diff <file of changed paths>"


def is_production(path) -> bool:
    """True when `path` is a production file: never a test module, a `conftest.py`,
    or anything under `three-pillars-docs/` (a light design certifies its code, not
    its tests or its own design record)."""
    parts = PurePosixPath(str(path)).parts
    if not parts or parts[0] == DOCS_ROOT:
        return False
    name = parts[-1]
    if name == "conftest.py" or name.endswith("_test.py"):
        return False
    return not (name.startswith("test_") and name.endswith(".py"))


def claim_lint(claim, *, repo, sha) -> list[str]:
    """One claim's reasons — every one a reason `certify.prepare` reports for it.

    Shape first; only a well-shaped claim is resolved at the SHA, in `prepare`'s order:
    `no-subjects`, the guard's path at `sha` (`guard-absent` / `guard-not-file`), the
    guard's text (`guard-undecodable`), then each declared subject (`subject-absent:<path>`).
    A reason that is not in that set is a lint bug this module's differential test fails."""
    out = certify_record.claim_reasons(claim)
    if out:
        return out
    subjects = claim.get("subjects") or []
    if not subjects:
        out.append("no-subjects")
    guard = str(claim.get("guard") or "")
    out += certify.guard_file_reasons(repo, sha, guard)
    _text, bad_text = certify.read_guard_at_sha(repo, sha, guard_parts(guard)[0])
    out += bad_text
    out += [f"subject-absent:{path}" for path in subjects
            if not certify.is_file_at(repo, sha, path)]
    return list(dict.fromkeys(out))


def _file_reasons(doc, name) -> list[str]:
    """The file-level reasons of `doc` named `name`, incl. the claims cap."""
    reasons = list(certify_record.file_reasons(doc, name))
    claims = doc.get("claims") if isinstance(doc, dict) else None
    if isinstance(claims, list) and len(claims) > certify_record.MAX_CLAIMS:
        reasons.append("cap")
    return reasons


def _claim_lines(claim, reasons) -> list[str]:
    cid = claim.get("id") if isinstance(claim, dict) else None
    return [f"{cid}: {reason}" for reason in reasons]


def lint(doc, name, *, repo, sha, light: bool = False, diff_paths=None) -> dict:
    """`{ok, lines, dropped, kept}` for claims file `doc` named `name` at `sha`.

    `kept` is a claims doc of the passing claims in input order — what `fold --kept`
    is later told, so a dropped id never folds `no-result`. `light` needs `diff_paths`
    (the design diff); without it the light rules cannot be evaluated (ValueError)."""
    if light and diff_paths is None:
        raise ValueError(LIGHT_NO_DIFF)
    claims = doc.get("claims") if isinstance(doc, dict) else None
    claims = claims if isinstance(claims, list) else []
    file_reasons = _file_reasons(doc, name)
    lines = [f"file: {reason}" for reason in file_reasons]
    dropped: list = []
    if file_reasons:
        kept, dropped = [], list(claims)
    else:
        kept = _passing(claims, repo, sha, light, diff_paths, lines, dropped)
        if light:
            over, kept = kept[LIGHT_CAP:], kept[:LIGHT_CAP]
            dropped += over
            lines += [line for claim in over for line in _claim_lines(claim, ["light:over-cap"])]
    disposition = doc.get("disposition") if isinstance(doc, dict) else None
    return {"ok": not lines, "lines": lines, "dropped": dropped,
            "kept": {"disposition": disposition, "claims": kept}}


def _passing(claims, repo, sha, light, diff_paths, lines, dropped) -> list:
    """The claims with no lint line, in input order; each other claim is dropped, with
    its reasons in `lines`."""
    production = {str(path) for path in diff_paths or () if is_production(path)}
    kept = []
    for claim in claims:
        reasons = claim_lint(claim, repo=repo, sha=sha)
        subjects = claim.get("subjects") if isinstance(claim, dict) else None
        if not reasons and light and not set(map(str, subjects or ())) & production:
            reasons = ["light:subject-not-in-diff"]
        if reasons:
            lines += _claim_lines(claim, reasons)
            dropped.append(claim)
        else:
            kept.append(claim)
    return kept


def read_path_list(path) -> list[str]:
    """One path per line (a design diff), or bad input when unreadable."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise BadInput(f"{path}: {exc}") from exc
    return [line.strip() for line in text.splitlines() if line.strip()]


def cmd_lint(args) -> int:
    doc = certify_cli.load_json(args.claims)
    diff_paths = read_path_list(args.diff) if args.diff else None
    sha = certify_cli.resolve_ref(args.repo, args.ref)
    try:
        report = lint(doc, args.name or Path(args.claims).name, repo=args.repo, sha=sha,
                      light=args.light, diff_paths=diff_paths)
    except ValueError as exc:
        raise BadInput(str(exc)) from exc
    if args.kept_out:
        certify_cli.write_atomic(args.kept_out, json.dumps(report["kept"], indent=2) + "\n")
    certify_cli.emit(None, {key: report[key] for key in ("ok", "lines", "dropped")})
    return EXIT_INVALID if report["lines"] else EXIT_OK


def register(sub) -> None:
    """Add `lint` to `certify.py`'s subparsers (called by `certify_cli_lean`)."""
    claim = sub.add_parser("lint", help="check a claims file before any certifier dispatch")
    claim.add_argument("--claims", required=True)
    claim.add_argument("--ref", required=True)
    claim.add_argument("--repo", default=".")
    claim.add_argument("--name")
    claim.add_argument("--light", action="store_true")
    claim.add_argument("--diff", help="file of the design's changed paths, one per line")
    claim.add_argument("--kept-out", help="write the kept claims doc here")
    claim.set_defaults(func=cmd_lint)
