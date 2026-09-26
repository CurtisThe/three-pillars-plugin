"""certify_cli_checks — the `certify.py` caller checks: `handoff`, `claimant-check`, `scan`.

design: audit-pass-does-not-bind (impl-audit F2, F6; detailed-design.md §Interfaces [A][R11][R12]).

    certify.py handoff --certifier-return E --records F
    certify.py claimant-check --base B --ref S --design D [--repo P]
    certify.py scan --artifact A [--out F]

`handoff` runs `certify_handoff.check_handoff` on the caller's copy `F` of the
certifier's `records_file`: prints `{ok, reasons}`; exit 1 on a missing copy, a
sha256 or `record_count` mismatch, or a certifier `status` other than `pass`
(reason `records-handoff`). `claimant-check` runs
`certify_record.candidate_path_violations` over
`git diff --no-renames --name-only B...S` in `--repo`: prints `{ok, reason:
"claimant-records", violations}`; exit 1 on any violation. `--design` is taken relative to `--repo`'s top level (an absolute path
is made relative to it); outside the repo, or with no `{design}/design.md` blob at
S (an ancestor dir, the repo top, a file), it is bad input (exit 2), so a
mis-spelled design can never pass a forged record. On either failure the caller certifies that claims file with
`certify.py run --unverified <reason>` (every claim `unverified`, no poles run)
and folds it, so the audit verdict is UNVERIFIED. `scan` is the phrase scan of a
markdown artifact with no claims (an interactive audit that makes no guard
claim): prints `{hits, verdict, code}`, `verdict = combine_verdict(PASS, one
unverified per counted hit)`, exit 0. Every subcommand exits 2 on bad input
(unreadable / malformed JSON, an unknown ref, an unreadable artifact).
"""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

import cert_phrase_scan
import certify_cli
import certify_record
import certify_scratch
from auto_verdict import combine_verdict
from certify_argv import norm
from certify_cli import EXIT_INVALID, EXIT_OK, BadInput
from certify_handoff import check_handoff

CLAIMANT_REASON = "claimant-records"


def cmd_handoff(args) -> int:
    env = certify_cli.load_json(args.certifier_return)
    if not isinstance(env, dict):
        raise BadInput("--certifier-return must be a JSON object")
    reasons = check_handoff(env, args.records)
    certify_cli.emit(None, {"ok": not reasons, "reasons": reasons})
    return EXIT_INVALID if reasons else EXIT_OK


def diff_paths(repo, base: str, ref: str) -> list[str]:
    """`git diff --no-renames --name-only -z base...ref` in `repo` (both refs resolved first).

    `-z` (J3): without it git C-quotes a non-ASCII path (`"…/r\\303\\251.json"`), which
    then matches no `{design}/` prefix and a forged record passes. `--no-renames` (PR #162
    r4): with rename detection on, `--name-only` lists only a rename's NEW path, so a
    record `git mv`-ed out of `{design}/certifications/` passed where the same `git rm`
    fails; without it a rename is a delete of the old path plus an add of the new one."""
    base_sha = certify_cli.resolve_ref(repo, base)
    ref_sha = certify_cli.resolve_ref(repo, ref)
    try:
        out = certify_scratch.git(["diff", "--no-renames", "--name-only", "-z",
                                   f"{base_sha}...{ref_sha}"],
                                  cwd=repo, env=certify_scratch.scrubbed_env())
    except (OSError, subprocess.SubprocessError) as exc:
        raise BadInput(f"cannot diff {base}...{ref} in {repo}") from exc
    return [path for path in out.split("\0") if path]


def design_path(repo, design: str, ref: str) -> str:
    """`design` as a repo-relative path holding a `design.md` blob at `ref` (else BadInput).

    The blob, not a mere tree, is what rules out an ancestor dir, the repo top or a file."""
    env = certify_scratch.scrubbed_env()
    try:
        top = Path(certify_scratch.git(["rev-parse", "--show-toplevel"], cwd=repo,
                                       env=env).strip()).resolve()
        rel = Path(design)
        if rel.is_absolute():
            rel = rel.resolve().relative_to(top)
        rel = norm(rel.as_posix())
        if not rel or rel == ".." or rel.startswith("../"):
            raise ValueError(design)
        doc = PurePosixPath(rel, "design.md").as_posix()
        kind = certify_scratch.git(["cat-file", "-t", f"{ref}:{doc}"], cwd=repo, env=env)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise BadInput(f"--design {design}: outside {repo} or no design.md at {ref}") from exc
    if kind.strip() != "blob":
        raise BadInput(f"--design {design}: {rel}/design.md is not a file at {ref}")
    return rel


def cmd_claimant_check(args) -> int:
    paths = diff_paths(args.repo, args.base, args.ref)
    design = design_path(args.repo, args.design, certify_cli.resolve_ref(args.repo, args.ref))
    violations = certify_record.candidate_path_violations(paths, design)
    certify_cli.emit(None, {"ok": not violations, "reason": CLAIMANT_REASON,
                            "violations": violations})
    return EXIT_INVALID if violations else EXIT_OK


def scan_report(text: str) -> dict:
    hits = cert_phrase_scan.scan(text, [])
    verdict, code = combine_verdict("PASS", ["unverified"] * len(certify_cli.counted(hits)))
    return {"hits": hits, "verdict": verdict, "code": code}


def cmd_scan(args) -> int:
    try:
        text = Path(args.artifact).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise BadInput(f"{args.artifact}: {exc}") from exc
    certify_cli.emit(args.out, scan_report(text))
    return EXIT_OK


def register(sub) -> None:
    """Add the three subcommands to `certify.py`'s subparsers."""
    hand = sub.add_parser("handoff", help="check the caller's copy of a certifier records file")
    hand.add_argument("--certifier-return", required=True)
    hand.add_argument("--records", required=True)
    hand.set_defaults(func=cmd_handoff)
    claim = sub.add_parser("claimant-check", help="refuse records/ledger in a candidate diff")
    claim.add_argument("--base", required=True)
    claim.add_argument("--ref", required=True)
    claim.add_argument("--design", required=True)
    claim.add_argument("--repo", default=".")
    claim.set_defaults(func=cmd_claimant_check)
    scan = sub.add_parser("scan", help="phrase-scan an artifact that makes no guard claim")
    scan.add_argument("--artifact", required=True)
    scan.add_argument("--out")
    scan.set_defaults(func=cmd_scan)
