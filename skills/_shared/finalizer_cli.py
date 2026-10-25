#!/usr/bin/env python3
"""finalizer_cli.py — prepare / apply / escalate / clear for the one Fable finalizer.

design: fable-first-stops (Task 2.1)

The command line of the two-step contract in ``finalizer.py``: the calling prose runs
``prepare`` (dispatch spec, ``noop``, or refusal), spawns ``tp-finalizer`` itself, then
runs ``apply`` with the agent's reply. Every subcommand prints one JSON line.

  prepare  --stop S --ledger L [--decisions D] [--entry run|seat]
      exit 0: ``dispatch`` or ``noop`` (a finalizer for this target is in flight);
      exit 3: ``refused`` (already-finalized / nested / ledger-unreadable / agent-unresolved).
  apply    --stop S --ledger L --reply R --decisions D [--model-used fable|opus]
           [--fallback-reason T] [--state F] [--pr-url U] [--config C]
      (pr-iterate: ``--pr-url`` defaults to the stop's target; ``--state`` is required,
      and a grantable signal applied without it escalates ``extension-unwritable``)
      validate the reply -> post-hoc check -> grant (``pr-iterate`` only, only on that
      signal's budget terminal; limits from ``--config``, else the repo config) ->
      decisions entry -> resolution note, or diagnosis then label -> clear the marker.
      Prints ``{"outcome": "resolved", "extension": ...}`` or ``{"outcome": "escalate", ...}``.
      A second ``apply`` for the same key is a no-op. ``apply`` never writes ``phase``.
      A missing, empty or unreadable ``--reply`` exits 2 with nothing written;
      ``escalate --reason no-reply`` covers a finalizer that returned nothing.
  escalate --stop S --reason already-finalized|nested|... --decisions D [--pr-url U]
      escalate with no reply and no dispatch (the caller got a ``prepare`` refusal).
  clear    --ledger L --decisions D
      clear a crashed finalizer's in-flight marker on demand; logs ``stale-in-flight-cleared``.

``--stop`` is an inline JSON object or a path to a JSON file. Exit 2: a usage or
input error (nothing written before the failing step). Effects go through the
``finalizer_effects`` seams (fail open, one printed line); the diagnosis comment
always lands before the ``tp:needs-human-attention`` label.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

_SHARED = Path(__file__).resolve().parent
_PR_ITERATE = _SHARED.parent / "tp-pr-iterate" / "scripts"
for _p in (_SHARED, _PR_ITERATE):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))

import budget_extension  # noqa: E402
import finalizer as fin  # noqa: E402
import finalizer_cli_ruling as fcr  # noqa: E402
import finalizer_effects as fx  # noqa: E402
import finalizer_outcome as fo  # noqa: E402
import finalizer_ruling as fr  # noqa: E402
import project_root  # noqa: E402
import strict_json_reply  # noqa: E402
try:
    import ready_ping  # noqa: E402  # the stop ping: a notification, never a step
except Exception:
    ready_ping = None

LABEL = "tp:needs-human-attention"
_REASONS = {
    "already-finalized": "A finalizer already ran for this stop, so it goes to the operator.",
    "nested": "A finalizer is already in flight for another target; none runs inside another.",
    "ledger-unreadable": "The finalizer ledger is unreadable, so the run fails closed.",
    "agent-unresolved": "The tp-finalizer agent reference could not be resolved.",
    "unmappable-choice": "The ruling's choice maps to no option of the stop, so it goes to the operator.",
    "pillar-doc": "A deferred hunk in a pillar doc (vision.md or architecture.md) is the operator's, so no Fable dispatch.",
    "no-reply": "The finalizer returned no reply (Fable, then the Opus fallback), so it goes to the operator.",
    "no-proposal": "No zero-drop VERIFIED splice proposal, or the re-verify failed, so the hunk waits for the human.",
}
# The reply contract is strict and fails closed (PR #188 round-4 ruling "Strict fix"): the
# reply is exactly one JSON object, bare or inside ONE fence whose closer repeats the opener.
# Lenient extraction (rounds 1-3) let prose, a second object or a malformed envelope quoting
# `"outcome": "resolved"` be read as resolved; now any of those escalates as unparseable.
# UNPARSEABLE is not JSON, so `finalizer_outcome.validate` escalates it as unparseable. The raw text is never
# passed on instead: `validate` parses without the duplicate-key check.
UNPARSEABLE = "(non-conforming finalizer reply)"


class CliError(Exception):
    """A usage or input error: reported on stderr, exit 2, nothing written yet."""


def _seams(comment_fn, label_fn, resolve_fn, pr_state_fn, is_ancestor_fn, now,
         ping_fn=None) -> SimpleNamespace:
    return SimpleNamespace(
        comment=comment_fn or fx.default_comment_fn, label=label_fn or fx.default_label_fn,
        resolve=resolve_fn, pr_state=pr_state_fn, is_ancestor=is_ancestor_fn,
        ping=ping_fn, now=now if now is not None else time.time())


def _emit(obj) -> None:
    print(json.dumps(obj, sort_keys=True))


def _load_stop(arg: str) -> dict:
    text = arg
    if not arg.lstrip().startswith("{"):
        try:
            text = Path(arg).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise CliError(f"--stop is neither inline JSON nor a readable file ({exc})") from None
    try:
        stop = json.loads(text)
        fin.stop_key(stop)
    except ValueError as exc:  # JSONDecodeError and a malformed stop are both ValueError
        raise CliError(f"--stop: {exc}") from None
    return stop


def _append(path, text: str) -> None:
    """Append one decisions.md entry, blank-line separated; fail open with one line."""
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        lead = "\n" if target.exists() and target.stat().st_size > 0 else ""
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(lead + text)
    except OSError as exc:
        print(f"finalizer-cli: decisions entry not written ({exc.__class__.__name__})")


def _stale_entry(key: str, by: str) -> str:
    return (f"### [finalizer] stale-in-flight-cleared — {key}\n"
            "- **Decided**: stale-in-flight-cleared\n"
            f"- **Reasoning**: cleared by `{by}`; the finalizer for this stop never reported back.\n"
            "- **Confidence**: high\n")


def _safe(fn, *args) -> bool:
    try:
        return bool(fn(*args))
    except Exception as exc:  # an injected seam may raise; effects fail open
        print(f"finalizer-cli: {getattr(fn, '__name__', 'effect')} failed open "
              f"({exc.__class__.__name__})")
        return False


def _diagnosis_body(stop, result) -> str:
    lines = [f"Finalizer escalated for {stop.get('source')}/{stop.get('signal')}.",
             "", "Diagnosis: " + (result.get("diagnosis") or "(none given)")]
    if result.get("problems"):
        lines.append("Problems: " + "; ".join(result["problems"]))
    return "\n".join(lines) + "\n"


def _post(stop, result, extension, pr_url, s) -> None:
    if result["outcome"] == "resolved":
        _safe(s.comment, pr_url, fo.resolution_note(stop, result, extension))
        return
    _safe(s.comment, pr_url, _diagnosis_body(stop, result))  # the diagnosis first ...
    _safe(s.label, pr_url, LABEL)  # ... then the label, which is the operator's signal


def _escalated(result: dict, problem: str, why: str) -> dict:
    out = dict(result)
    out["outcome"] = "escalate"
    out["problems"] = [*result.get("problems", []), problem]
    prior = result.get("diagnosis") or ""
    out["diagnosis"] = (prior + "\n\n" if prior else "") + why
    return out


def _envelope(text: str):
    """The reply's JSON envelope under the strict contract (`strict_json_reply`), else
    ``UNPARSEABLE``. The result is never a string ``validate`` could decode a second time."""
    data = strict_json_reply.one_object(text)
    return UNPARSEABLE if data is None else data


def _read_reply(path):
    try:
        return _envelope(Path(path).read_text(encoding="utf-8-sig"))  # a BOM is not prose
    except (OSError, UnicodeDecodeError):
        return None


def _require_reply(path) -> None:
    try:
        why = "is empty" if not Path(path).read_text(encoding="utf-8-sig").strip() else None
    except OSError:
        why = "is missing or unreadable"
    except UnicodeDecodeError:
        why = "is not UTF-8"
    if why:
        raise CliError(f"reply file {path} {why}; save the finalizer's hand-back reply to it first "
                       "(nothing was written)")


def _config(path) -> dict:
    if path:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CliError(f"--config unreadable ({exc})") from None
        if not isinstance(data, dict):
            raise CliError("--config is not a JSON object")
        return data
    from repo_config_load import load_repo_config
    loaded = load_repo_config(Path.cwd())
    if loaded.status == "unreadable":
        raise CliError("; ".join(loaded.warnings) or "repo config unreadable")
    return loaded.config


def _insufficient(detail, configured, granted) -> str | None:
    """A reason when the grant, in the detail's units, does not exceed what was measured."""
    if not isinstance(detail, dict) or not configured or configured <= 0:
        return None
    limit, measured = detail.get("limit"), detail.get("measured")
    if not all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in (limit, measured)):
        return None
    scaled = limit * granted / configured
    if scaled > measured:
        return None
    return (f"the granted limit ({scaled:g} in the stop's units) does not exceed the "
            f"measured {measured:g}; the signal would fire again at once")


def _grant(stop, key, result, args, s):
    """`(result, extension)`: one recorded grant on the matching budget terminal."""
    signal = stop["signal"]
    if stop["source"] != "pr-iterate" or signal not in budget_extension.SIGNAL_KEY:
        return result, None
    if not args.state:  # a resolved without a recorded grant would re-fire next round
        return _escalated(result, "extension-unwritable",
                          "No --state (the iterate-state file) was passed, so the extension "
                          "could not be recorded; the stop would fire again next round."), None
    import iterate_state
    import round_budget
    path = Path(args.state)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        return _escalated(result, "extension-unwritable",
                          f"The iterate state {path} could not be read ({exc}); nothing was granted."), None
    if not round_budget.is_budget_terminal(state) or state.get("termination_reason") != signal:
        return result, None  # already converged, or a different signal: nothing to lift
    try:  # prepare set the in-flight marker: a CliError here would exit 2 and leave it set
        lim = round_budget.limits(_config(args.config))
    except CliError as exc:
        return _escalated(result, "config-unreadable",
                          f"The repo config could not be read ({exc}); nothing was granted."), None
    at = datetime.fromtimestamp(s.now, tz=timezone.utc).isoformat()
    try:
        granted, extension = budget_extension.grant(state, signal, lim, key, at)
    except ValueError as exc:
        return _escalated(result, "extension-refused", f"{exc}; nothing was granted."), None
    if extension is None:  # this signal's one grant is spent: a resolved would lift nothing
        return _escalated(result, "extension-spent",
                          f"The one {signal} extension is already recorded, so the stop cannot "
                          "be lifted again; nothing was granted."), None
    configured = lim[budget_extension.SIGNAL_KEY[signal]]
    why = _insufficient(stop.get("detail"), configured, extension["to"])
    if why:
        return _escalated(result, "extension-insufficient", f"Extension insufficient: {why}."), None
    try:
        iterate_state.write_state_atomic(path, granted)
    except OSError as exc:
        return _escalated(result, "extension-unwritable",
                          f"The extension could not be written to {path} ({exc})."), None
    return result, extension


def cmd_prepare(args, s) -> int:
    stop = _load_stop(args.stop)
    decisions = args.decisions or Path(args.ledger).parent / "decisions.md"
    out = fin.prepare(stop, args.ledger, resolve_fn=s.resolve, now=s.now, decisions_path=decisions,
                      entry=args.entry)
    for key in out.get("stale_cleared", []):
        _append(decisions, _stale_entry(key, "prepare"))
    _emit(out)
    return 3 if out["status"] == "refused" else 0


def _need_scope(args, stop) -> None:
    """A question stop is only ever finalized against a named scope (design 4.3)."""
    if stop["source"] == "question" and not fcr._ruling_scope(args, stop):
        raise CliError("question stop needs --scope")


def _settles_as_stop(stop, result) -> bool:
    """A review stop whose escalate `review_stop.settle` labels as `stop`: no ping."""
    try:
        import review_stop
        return (stop.get("source") == "question" and "://" in str(stop.get("target", ""))
                and review_stop.technicality_result(result))
    except Exception:  # the ping is the fail-safe
        return False


def _finish(stop, key, result, extension, args, s) -> int:
    model = getattr(args, "model_used", "fable")
    scope, ruling = fcr._ruling_scope(args, stop), None
    if scope:
        try:  # the ruling file lands before the decisions entry that names its id
            ruling = fcr.write_ruling(args, stop, key, result, model, scope)
        except (OSError, ValueError) as exc:
            print(f"finalizer-cli: ruling file not written ({exc})")
    else:
        print("finalizer-cli: no ruling scope")  # before the JSON, which stays last
    _append(args.decisions, fo.decision_entry(stop, result, model, getattr(args, "fallback_reason", None),
                                             ruling_id=ruling[0] if ruling else None))
    if args.pr_url:
        _post(stop, result, extension, args.pr_url, s)
    if getattr(args, "ledger", None):
        try:
            fin.clear_in_flight(args.ledger, key, result["outcome"])
        except (fin.LedgerError, OSError) as exc:
            print(f"finalizer-cli: ledger not updated ({exc})")
    out = ({"outcome": "resolved", "extension": extension} if result["outcome"] == "resolved"
           else {"outcome": "escalate", "problems": result["problems"], "extension": None})
    if ruling:
        out["ruling_id"], out["ruling_path"] = ruling
    if result["outcome"] == "escalate" and s.ping and not _settles_as_stop(stop, result):
        # the marked ping line goes to stderr, so the JSON stays last on stdout
        _safe(lambda: s.ping(stop, decisions=args.decisions))
    elif result["outcome"] == "escalate" and s.ping:
        print("finalizer-cli: pillar-technicality stop, no ping (review_stop settle labels it)")
    _emit(out)
    return 0


def _default_pr_url(stop, args) -> None:
    """A pr-iterate stop's target is its PR URL: the default for ``--pr-url``."""
    if not args.pr_url and stop["source"] == "pr-iterate":
        args.pr_url = stop["target"]


def cmd_apply(args, s) -> int:
    stop = _load_stop(args.stop)
    _need_scope(args, stop)
    key = fin.stop_key(stop)
    _default_pr_url(stop, args)
    if stop["source"] == "question":
        args.pr_url = None  # a question stop has no PR: nothing is ever posted
    try:
        seen = fin.load_ledger(args.ledger)["seen"]
    except fin.LedgerError as exc:
        result = {"outcome": "escalate", "problems": ["ledger-unreadable"], "demoted": [],
                  "diagnosis": f"The finalizer ledger is unreadable ({exc}).", "reasoning": ""}
        return _finish(stop, key, result, None, args, s)
    if key in seen:
        _emit({"status": "noop", "reason": "already-applied", "outcome": seen[key]})
        return 0
    _require_reply(args.reply)
    root = project_root.find_project_root() or Path.cwd()
    result = fo.validate(
        _read_reply(args.reply), fr.load_pillars(root),
        kind=stop["signal"] if stop["source"] == "question" else None,
        source=stop["source"])
    if result["outcome"] == "resolved" and args.pr_url:
        check = fx.posthoc(stop, args.pr_url, s.pr_state, s.is_ancestor)
        if not check["ok"]:
            result = _escalated(result, f"finalizer-violation: {check['violation']}",
                                f"Post-hoc check failed ({check['violation']}); nothing was granted.")
        elif check.get("unverified"):
            result["reasoning"] = (result["reasoning"] + f" [post-hoc unverified: {check['unverified']}]").strip()
    extension = None
    if result["outcome"] == "resolved":
        result, extension = _grant(stop, key, result, args, s)
    return _finish(stop, key, result, extension, args, s)


def cmd_escalate(args, s) -> int:
    stop = _load_stop(args.stop)
    _need_scope(args, stop)
    _default_pr_url(stop, args)
    diagnosis = " ".join(filter(None, [_REASONS[args.reason], args.detail]))
    result = {"outcome": "escalate", "problems": [args.reason], "diagnosis": diagnosis,
              "reasoning": f"no finalizer dispatched: {args.reason}", "demoted": []}
    args.model_used, args.fallback_reason = "none", None
    args.ledger = getattr(args, "ledger", None)
    return _finish(stop, fin.stop_key(stop), result, None, args, s)


def cmd_clear(args, s) -> int:
    try:
        ledger = fin.load_ledger(args.ledger)
    except fin.LedgerError as exc:
        raise CliError(str(exc)) from None
    flight = ledger["in_flight"]
    if flight is None:
        _emit({"status": "none"})
        return 0
    ledger["in_flight"] = None
    ledger["stale_cleared"].append(flight["key"])
    fin.save_ledger(args.ledger, ledger)
    _append(args.decisions, _stale_entry(flight["key"], "clear"))
    _emit({"status": "cleared", "key": flight["key"]})
    return 0


def _parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="finalizer_cli.py", description=__doc__.split("\n")[0])
    sub = top.add_subparsers(dest="cmd", required=True)

    def add(name, *flags):
        p = sub.add_parser(name)
        for flag, required in flags:
            p.add_argument(flag, required=required)
        return p

    add("prepare", ("--stop", True), ("--ledger", True), ("--decisions", False)).add_argument(
        "--entry", choices=("run", "seat"), default="run")
    ap = add("apply", ("--stop", True), ("--ledger", True), ("--reply", True), ("--decisions", True),
             ("--state", False), ("--pr-url", False), ("--config", False), ("--fallback-reason", False))
    ap.add_argument("--model-used", choices=("fable", "opus"), default="fable")
    es = add("escalate", ("--stop", True), ("--decisions", True), ("--pr-url", False), ("--detail", False),
             ("--ledger", False))
    es.add_argument("--reason", required=True, choices=sorted(_REASONS))
    for p in (ap, es):  # the ruling scope and its entry point (design 4.3)
        p.add_argument("--scope", default=None)
        p.add_argument("--entry", choices=("run", "seat"), default="run")
    add("clear", ("--ledger", True), ("--decisions", True))
    return top


_COMMANDS = {"prepare": cmd_prepare, "apply": cmd_apply, "escalate": cmd_escalate, "clear": cmd_clear}


def main(argv=None, comment_fn=None, label_fn=None, resolve_fn=None, pr_state_fn=None,
         is_ancestor_fn=None, now=None, ping_fn=None) -> int:
    seams = _seams(comment_fn, label_fn, resolve_fn, pr_state_fn, is_ancestor_fn, now,
                   ping_fn=ping_fn)
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    for name in ("decisions", "ledger"):  # an archived run writes under completed-tp-designs/
        if getattr(args, name, None):
            setattr(args, name, fcr.archived_path(getattr(args, name)))
    try:
        return _COMMANDS[args.cmd](args, seams)
    except CliError as exc:
        print(f"finalizer-cli: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(ping_fn=ready_ping.ping_stop if ready_ping else None))
