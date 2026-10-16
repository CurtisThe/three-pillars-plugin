"""explainer/explain_cli_cmds.py — the handlers behind the `explain_cli.py` subcommands.

Public API:
    EXIT_OK, EXIT_OFF, EXIT_USAGE, EXIT_GATE   the exit codes: 0, 1, 2, 3
    CliError                                   a bad input; `explain_cli.main` prints it
    emit(obj) -> None                          print one JSON line on stdout
    load_object(path, what) -> dict            read a JSON object file, else CliError
    cmd_enabled / cmd_request / cmd_gate / cmd_finalize / cmd_render /
    cmd_telemetry / cmd_report                 each takes the parsed `args`, returns an exit code

The delivery handlers (brief, post, rulings ...) live in `explain_cli_deliver.py`.

Every handler prints exactly one JSON line on stdout. `args.root` is the repo root (the
global `--root`); it goes to every `explain_state` / `explain_request` call, so state lands
in that repo's git common dir and never in the cwd's. A bad input raises `CliError`.

    enabled     {"enabled": bool}; exit 1 when `explainer.enabled` is false
    request     writes `--out` (the explain request); {request, drafter, needs_check}; it
                also resets the gate's attempt counter for that file
    gate        {pass, failures, diagrams_ok, diagram_reasons, rewrite_prompt, next}; exit 0
                on a pass, exit 3 on a fail; the rewrite prompt states each diagram reason.
                The first failing call per request file returns the rewrite prompt and
                next "rewrite"; every later one returns null and next "finalize"
                (the attempts live in the sidecar `<request>.gate-attempts`)
    finalize    writes `--out` (the envelope to render); {out, facts_only, check_outcome}.
                With `--checked` the Opus-checked envelope ships and `check_outcome` is the
                prose-diff verdict of the draft against it, else null; the `--envelope`
                file's own "diagram omitted" notes ride along (`explain_degrade.merge_notes`)
    render      {format, text} for html / markdown / log, {format, card} for card
    telemetry   appends one `--row` JSON object; {row}
    report      {report: {engine: {n, rewrite_rate, check_rewritten_rate}}}

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_card  # noqa: E402
import explain_config  # noqa: E402
import explain_degrade  # noqa: E402
import explain_engine  # noqa: E402
import explain_gate  # noqa: E402
import explain_html  # noqa: E402
import explain_markdown  # noqa: E402
import explain_request  # noqa: E402
import explain_state  # noqa: E402
import explainer_marker  # noqa: E402
import role_engine  # noqa: E402

EXIT_OK = 0
EXIT_OFF = 1
EXIT_USAGE = 2
EXIT_GATE = 3
ATTEMPTS_SUFFIX = ".gate-attempts"
_UNKNOWN = "unknown"


class CliError(Exception):
    """A bad input to a subcommand; `explain_cli.main` prints it and exits 2."""


def emit(obj) -> None:
    """Print `obj` as the one JSON line a subcommand writes on stdout."""
    print(json.dumps(obj))


def _load(path, what):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CliError(f"cannot read {what} {path}: {exc}") from exc


def load_object(path, what) -> dict:
    data = _load(path, what)
    if not isinstance(data, dict):
        raise CliError(f"{what} {path} is not a JSON object")
    return data


def _write_json(path, data) -> Path:
    dest = Path(path)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise CliError(f"cannot write {path}: {exc}") from exc
    return dest


def _attempts_path(request_path) -> Path:
    return Path(str(request_path) + ATTEMPTS_SUFFIX)


def _bump_attempts(request_path) -> int:
    """Count one failed gate run for `request_path`; return the new total."""
    side = _attempts_path(request_path)
    try:
        spent = int(side.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        spent = 0
    try:
        side.write_text(str(spent + 1), encoding="utf-8")
    except OSError as exc:
        raise CliError(f"cannot write {side}: {exc}") from exc
    return spent + 1


def cmd_enabled(args) -> int:
    on = explain_config.load(args.root)["enabled"]
    emit({"enabled": on})
    return EXIT_OK if on else EXIT_OFF


def cmd_request(args) -> int:
    if args.kind not in explain_request.KINDS:
        raise CliError(f"unknown kind {args.kind!r}; expected one of "
                       f"{', '.join(explain_request.KINDS)}")
    subject = load_object(args.subject, "subject") if args.subject else None
    request = explain_request.build_request(
        args.root, kind=args.kind, slug=args.slug, subject=subject, base=args.base,
        review_digest=args.review_digest)
    config = role_engine.load_config(args.root)
    drafter = explain_engine.resolve_drafter(args.kind, config, args.root)
    out = _write_json(args.out, request)
    _attempts_path(out).unlink(missing_ok=True)
    emit({"request": str(out), "drafter": drafter,
          "needs_check": explain_engine.needs_check(args.kind)})
    return EXIT_OK


def cmd_gate(args) -> int:
    request = load_object(args.request, "request")
    env = _load(args.envelope, "envelope")
    result = explain_gate.run_gates(env, request)
    reply = {"pass": result["pass"], "failures": result["failures"],
             "diagrams_ok": result["diagrams_ok"],
             "diagram_reasons": result["diagram_reasons"], "rewrite_prompt": None,
             "next": "finalize"}
    if result["pass"]:
        emit(reply)
        return EXIT_OK
    if _bump_attempts(args.request) == 1:
        reply["rewrite_prompt"] = explain_gate.rewrite_prompt(result["failures"],
                                                           result["diagram_reasons"])
        reply["next"] = "rewrite"
    emit(reply)
    return EXIT_GATE


def _keep_prior_notes(final: dict, draft) -> dict:
    """``final`` with the `--envelope` notes of our own form ahead of its own.

    A facts-only result has no notes key and gets none.
    """
    key = explain_degrade.DIAGRAM_NOTES
    if key in final:
        prior = draft.get(key) if isinstance(draft, dict) else None
        final[key] = explain_degrade.merge_notes(prior, final[key])
    return final


def cmd_finalize(args) -> int:
    request = load_object(args.request, "request")
    draft = _load(args.envelope, "envelope")
    final = explain_degrade.finalize(draft, request, explain_gate.run_gates(draft, request))
    outcome = None
    if args.checked:
        checked = _load(args.checked, "checked envelope")
        outcome = explain_degrade.check_outcome(final, checked)
        final = _keep_prior_notes(explain_degrade.finalize(
            checked, request, explain_gate.run_gates(checked, request)), draft)
    out = _write_json(args.out, final)
    emit({"out": str(out), "facts_only": final.get(explain_degrade.FACTS_ONLY) is True,
          "check_outcome": outcome})
    return EXIT_OK


def _head(args) -> str:
    return args.head or explain_request._evidence_head(args.root) or _UNKNOWN


def cmd_render(args) -> int:
    env = load_object(args.envelope, "envelope")
    kind = env.get("kind") if isinstance(env.get("kind"), str) else _UNKNOWN
    if args.format == "card":
        emit({"format": "card", "card": explain_card.render_card(env, args.html_path)})
    elif args.format == "log":
        emit({"format": "log", "text": explain_card.render_log_entry(env)})
    elif args.format == "html":
        text = explain_html.render_html(
            env, head=_head(args), title=args.title or f"Explainer: {kind}")
        emit({"format": "html", "text": text})
    else:
        mark = explainer_marker.marker(kind, args.slug or _UNKNOWN, _head(args))
        emit({"format": "markdown",
              "text": explain_markdown.render_markdown(env, head=_head(args), marker=mark)})
    return EXIT_OK


def cmd_telemetry(args) -> int:
    try:
        row = json.loads(args.row)
    except ValueError as exc:
        raise CliError(f"--row is not valid JSON: {exc}") from exc
    if not isinstance(row, dict):
        raise CliError("--row must be a JSON object")
    emit({"row": explain_state.telemetry_append(args.root, row)})
    return EXIT_OK


def cmd_report(args) -> int:
    emit({"report": explain_state.report(args.root)})
    return EXIT_OK
