"""explainer/explain_cli_deliver.py — the delivery handlers behind the `explain_cli.py` subcommands.

Public API:
    FORGE                  the forge module every handler uses (default `forge`); a test swaps
                           it for a fake, so no handler reaches a network
    EXIT_CURRENT           1, the `refresh-needed` exit code when the brief is current
    cmd_brief / cmd_headline / cmd_post / cmd_refresh_needed / cmd_ruling_append /
    cmd_rulings_sync / cmd_rulings_fold / cmd_record_artifact
                           each takes the parsed `args`, returns an exit code
    fail_open(args, exc) -> int
                           the degrade for a bad input: one `explainer: <reason> — see <path>`
                           stderr line, nothing on stdout, EXIT_OK

Each handler prints one JSON line on stdout and exits 0 unless noted; a bad input raises
`explain_cli_cmds.CliError`, and `explain_cli.main` hands it to `fail_open`: a delivery
subcommand never fails its caller. `args.root` is the repo root, as in `explain_cli_cmds`.

    brief            writes `brief.md`, the offline HTML and the envelope JSON; {brief: path}.
                     It commits nothing.
    headline         prints the one-line PR-body headline (plain text, not JSON); prints
                     nothing and exits 0 when `explainer.enabled` is false, so the PR body
                     stays byte-identical with the explainer off
    post             posts or edits the one comment of `--kind` (default pr-brief) on `--pr`;
                     {posted, comment_id}. The pr-brief body is the stored `brief.md`; a first
                     pr-brief post stamps `posted_head` with the PR head from `pr_read`
                     (the marker head when that is unavailable). With
                     `--envelope` (the refresh form) the body is that envelope rendered at
                     the current HEAD: the comment is edited in place, the stored envelope and
                     HTML are replaced, `brief.md` is left alone and nothing is committed.
                     `--kind rulings` posts the rulings ledger like `rulings-sync`.
    refresh-needed   {stale}; exit 0 when the brief is stale, EXIT_CURRENT when it is current
    ruling-append    appends the auto-ruling envelope to the ledger; {ruling: "r<n>"}
    rulings-sync     {rulings: n, posted[, comment_id]}; a no-op on an empty ledger
    rulings-fold     {folded: n}, the late rows moved into the archived ledger
    record-artifact  stores `--url` as the kind's `artifact_url`; {artifact_url}

Fail-open: a forge that cannot be reached never fails the run. The degrade is one line on
stderr, `explainer: <reason> — see <path>` (`explain_deliver.degrade_line`), the exit code
stays 0 and the JSON reports `posted: false`. A bad input (a missing file, a bad slug) is the
same line with nothing on stdout; if storing the degrade fails (a bad slug), the line still
prints, unrecorded.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_card  # noqa: E402
import explain_cli_cmds as cmds  # noqa: E402
import explain_config  # noqa: E402
import explain_deliver  # noqa: E402
import explain_request  # noqa: E402
import explain_rulings  # noqa: E402
import explain_state  # noqa: E402
import forge  # noqa: E402

FORGE = forge
EXIT_CURRENT = 1
_UNKNOWN = "unknown"


def _read_text(path, what) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise cmds.CliError(f"cannot read {what} {path}: {exc}") from exc


def cmd_brief(args) -> int:
    env = cmds.load_object(args.envelope, "envelope")
    path = explain_deliver.write_brief(args.root, args.slug, env, evidence_head=args.head)
    cmds.emit({"brief": str(path)})
    return cmds.EXIT_OK


def cmd_headline(args) -> int:
    if not explain_config.load(args.root)["enabled"]:
        return cmds.EXIT_OK
    try:
        env = cmds.load_object(
            explain_deliver.envelope_path(args.root, args.slug), "stored envelope")
    except cmds.CliError:
        explain_deliver.degrade_line(
            args.root, args.slug, "pr-brief", "brief unavailable: no drafted brief")
        return cmds.EXIT_OK
    print(explain_card.headline(env, str(explain_deliver.brief_path(args.root, args.slug))))
    return cmds.EXIT_OK


def _outcome(args, kind, result) -> dict:
    """`{posted, comment_id}` for the forge `result` of `kind` (None: nothing was posted)."""
    ok = result is not None and result.status == "ok"
    stored = explain_state.delivery(args.root, args.slug, kind).get("comment_id")
    return {"posted": ok, "comment_id": stored if ok else None}


def _brief_body(args) -> str:
    if args.envelope:
        env = cmds.load_object(args.envelope, "envelope")
        head = explain_request._evidence_head(args.root) or _UNKNOWN
        return explain_deliver.write_artifacts(args.root, args.slug, env, evidence_head=head)
    return _read_text(explain_deliver.brief_path(args.root, args.slug), "brief")


def _stamp_pr_head(args) -> None:
    """Store the PR's head commit as `posted_head`; silent when it cannot be read."""
    read = getattr(FORGE, "pr_read", None)
    res = read(args.root, args.pr) if read else None
    head_sha = res.payload.get("head_sha") if res is not None and res.status == "ok" else None
    if head_sha:
        explain_state.delivery(args.root, args.slug, explain_deliver.PR_BRIEF_KIND,
                               update={"posted_head": head_sha})


def cmd_post(args) -> int:
    if args.kind == explain_rulings.RULINGS_KIND:  # sync_rulings prints its own degrade line
        result = explain_rulings.sync_rulings(
            args.root, args.slug, args.pr, context=args.context, forge_mod=FORGE)
    else:
        result = explain_deliver.post_or_edit(
            args.root, args.slug, args.pr, _brief_body(args), kind=args.kind,
            context=args.context, forge_mod=FORGE)
        if result.status != "ok":
            explain_deliver.degrade_line(args.root, args.slug, args.kind, result.line)
        elif args.kind == explain_deliver.PR_BRIEF_KIND and not args.envelope:
            _stamp_pr_head(args)
    cmds.emit(_outcome(args, args.kind, result))
    return cmds.EXIT_OK


def cmd_refresh_needed(args) -> int:
    stale = explain_deliver.refresh_needed(args.root, args.slug, args.pr, forge_mod=FORGE)
    cmds.emit({"stale": stale})
    return cmds.EXIT_OK if stale else EXIT_CURRENT


def cmd_ruling_append(args) -> int:
    env = cmds.load_object(args.envelope, "envelope")
    cmds.emit({"ruling": explain_rulings.append_ruling(args.root, args.slug, env)})
    return cmds.EXIT_OK


def cmd_rulings_sync(args) -> int:
    count = len(explain_rulings.all_rows(args.root, args.slug))
    result = explain_rulings.sync_rulings(
        args.root, args.slug, args.pr, context=args.context, forge_mod=FORGE)
    reply = {"rulings": count, "posted": False}  # sync_rulings printed any degrade line
    if result is not None:
        reply = {"rulings": count,
                 **_outcome(args, explain_rulings.RULINGS_KIND, result)}
    cmds.emit(reply)
    return cmds.EXIT_OK


def cmd_rulings_fold(args) -> int:
    cmds.emit({"folded": explain_rulings.fold_late(args.root, args.slug)})
    return cmds.EXIT_OK


def cmd_record_artifact(args) -> int:
    explain_state.delivery(args.root, args.slug, args.kind, update={"artifact_url": args.url})
    cmds.emit({"artifact_url": args.url})
    return cmds.EXIT_OK


def fail_open(args, exc) -> int:
    """Print `exc` as one degrade line, nothing on stdout, and return EXIT_OK."""
    kind = getattr(args, "kind", None) or explain_deliver.PR_BRIEF_KIND
    reason = str(exc)
    try:
        explain_deliver.degrade_line(args.root, args.slug, kind, reason)
    except (cmds.CliError, ValueError, RuntimeError, OSError):
        see = Path(args.root).joinpath(*explain_deliver._DESIGN_DIR, str(args.slug), "brief.md")
        print(f"explainer: {' '.join(reason.split())} — see {see}", file=sys.stderr)
    return cmds.EXIT_OK
