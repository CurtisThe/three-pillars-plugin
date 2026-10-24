#!/usr/bin/env python3
"""ruling_cli.py — answer/feedback/link/show/subject/card for a ruling file.

design: fable-escalation (Tasks 4.5, 4.6). Each subcommand prints one JSON
line, exit 0; bad input exits 2 with one ``ruling-cli: <why>`` stderr line,
nothing written. Root: project root else cwd. Stdlib only.

  answer   --id I --choice LABEL [--text T]
  feedback --id I agree|disagree --reason R
  link     --id I --explain REF
  show     --id I
  subject  --id I --out F   card  --id I [--html P]
  ask      --scope S --question Q --option L=D (2-4) --recommended L [--kind K] [--context T]
           (prints its JSON line, then `awaiting-operator: ruling <id>`, then the
           answer command)
  wait     --id I [--timeout S] [--interval S]  (read only; label on line 1,
           answer text on line 2 when present; exit 3 on timeout)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import finalizer_ruling as fr  # noqa: E402
import ruling_ask  # noqa: E402
import ruling_file as rf  # noqa: E402
from project_root import find_project_root  # noqa: E402


class CliError(Exception):
    """A usage or input error: exit 2, one stderr line, nothing written."""


VERDICTS = ("agree", "disagree")
RECOMMENDED = " (Recommended)"
STOP_RUN = {"label": "stop-run", "description": "Stop the run and leave it "
            "for the operator."}
PADS = (STOP_RUN, {"label": "answer-in-text", "description": "Type the "
                   "ruling yourself as free text; the run records it with "
                   "ruling_cli answer."})


def _root() -> Path:
    return find_project_root() or Path.cwd()


def _ruling_path(id_: str) -> Path:
    path = rf.find(_root(), id_)
    if path is None:
        raise CliError(f"no ruling for id {id_!r} under "
                       f"{_root() / rf.RULINGS_REL}")
    return path


def _emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _payload(path: Path) -> dict:
    parsed = rf.parse(path)
    return {"id": parsed["front"].get("id", path.stem),
            "path": str(path), "feedback": parsed["feedback"]}


def cmd_answer(args, **_):
    path = _ruling_path(args.id)
    line = f"answer: {args.choice}"
    if args.text:
        line += f" — {args.text}"
    rf.append_feedback(path, line)
    return _emit(_payload(path))


def cmd_feedback(args, **_):
    if args.verdict not in VERDICTS:
        raise CliError(f"verdict must be one of {'|'.join(VERDICTS)}, "
                       f"not {args.verdict!r}")
    path = _ruling_path(args.id)
    rf.append_feedback(path, f"{args.verdict} — {args.reason}")
    return _emit(_payload(path))


def cmd_link(args, **_):
    path = _ruling_path(args.id)
    rf.set_explain(path, args.explain)
    return _emit(_payload(path))


def cmd_show(args, **_):
    return _emit(rf.parse(_ruling_path(args.id)))


def _ruling_dict(parsed):
    """The six ruling keys: nested ``ruling`` dict, else the result dict."""
    result = parsed["ruling"] if isinstance(parsed.get("ruling"), dict) else {}
    inner = result.get("ruling")
    return inner if isinstance(inner, dict) else result


def _opts(ruling):
    return [o for o in ruling.get("options") or [] if isinstance(o, dict)]


def _decided(pick):
    label = str(pick.get("label") or "") if pick else ""
    desc = str(pick.get("description") or "") if pick else ""
    return f"{label} — {desc}" if label and desc else label or desc


def _stance(option_id, basis):
    return " ".join(f"{str(e.get('stance') or '').capitalize()} {e.get('doc')}"
                    f" § {e.get('section')}." for e in basis
                    if e.get("option") == option_id)


def _card_opt(o, basis, recommended):
    label = str(o.get("label") or o.get("id") or "Option")
    desc = f"{str(o.get('description') or '').strip()} " \
           f"{_stance(o.get('id'), basis)}".strip()
    return {"label": label + (RECOMMENDED if recommended else ""),
            "description": desc}


def _repo_root() -> Path:
    """The cwd's git repo root (resolved), else the cwd when git fails."""
    try:
        done = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, check=True)
        top = done.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        top = ""
    return Path(top or Path.cwd()).resolve()


def _confined(out: Path) -> Path:
    """``out`` resolved, refused unless it sits inside the repo root."""
    resolved = out.resolve()
    root = _repo_root()
    if resolved != root and root not in resolved.parents:
        raise CliError(f"--out {str(out)!r} resolves outside the repo "
                       f"{root}; use a path inside it")
    return resolved


def cmd_subject(args, **_):
    path = _ruling_path(args.id)
    parsed = rf.parse(path)
    ruling = _ruling_dict(parsed)
    subject = {"question": parsed["question"], "options": [],
               "pillar_basis": [], "commits_to": [], "tie_breaker": None,
               "decided": _decided(fr.chosen(_opts(ruling)))}
    for k in ("options", "pillar_basis", "commits_to", "tie_breaker"):
        subject[k] = ruling.get(k, subject[k])
    out = Path(args.out)
    _confined(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(subject, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    return _emit({"id": path.stem, "out": str(out)})


def cmd_card(args, **_):
    path = _ruling_path(args.id)
    parsed = rf.parse(path)
    ruling = _ruling_dict(parsed)
    options = _opts(ruling)
    basis = [e for e in ruling.get("pillar_basis") or []
             if isinstance(e, dict)]
    pick = fr.chosen(options)
    ordered = [pick] + [o for o in options if o is not pick] \
        if pick else options[:]
    deduped, seen = [], set()
    for o in ordered:
        lab = str(o.get("label") or o.get("id") or "Option")
        if lab not in seen:
            seen.add(lab)
            deduped.append(o)
    ordered = deduped
    for pad in PADS:
        if len(ordered) < 2 and pad["label"] not in seen:
            ordered.append(dict(pad))
            seen.add(pad["label"])
    ordered = ordered[:4]
    question = parsed["question"] + (f" (Full explanation: {args.html})"
                                     if args.html else "")
    return _emit({"question": f"{question}\nruling: {path.stem}",
                  "options": [_card_opt(o, basis, o is pick)
                              for o in ordered]})


_sleep = time.sleep
_clock = time.monotonic


def _answer_text(parsed):
    """Text after the first `` — `` of the last ``answer:`` line, else None."""
    for line in reversed(parsed.get("feedback") or []):
        m = rf._ANSWER.match(line)
        if m:
            _, sep, text = m.group(1).partition(" — ")
            return text if sep and text else None
    return None


def cmd_wait(args, **_):
    path = _ruling_path(args.id)
    deadline = _clock() + args.timeout
    while True:
        parsed = rf.parse(path)
        label = rf.answer_of(parsed)
        if label:
            print(label)
            text = _answer_text(parsed)
            if text is not None:
                print(text)
            return 0
        if _clock() >= deadline:
            print(f"awaiting-operator: ruling {args.id} "
                  f"(no answer after {args.timeout:g}s)")
            return 3
        _sleep(args.interval)


def cmd_ask(args, **_):
    try:
        path = ruling_ask.ask(
            _root(), scope=args.scope, question=args.question,
            options=args.option or [], recommended=args.recommended,
            kind=args.kind, context=args.context)
    except ValueError as exc:
        raise CliError(str(exc)) from exc
    rid = path.stem
    _emit({"id": rid, "path": str(path), "kind": args.kind,
           "options": [ruling_ask.parse_option(t)[0] for t in args.option],
           "recommended": args.recommended})
    print(f"awaiting-operator: ruling {rid}")
    print('python3 "$TP_ROOT"/skills/_shared/ruling_cli.py answer '
          f"--id {rid} --choice <label>")
    return 0


_COMMANDS = {"ask": cmd_ask, "wait": cmd_wait, "answer": cmd_answer, "feedback": cmd_feedback, "link": cmd_link,
             "show": cmd_show, "subject": cmd_subject, "card": cmd_card}


def _parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(
        prog="ruling-cli", description="Feedback on a finalizer ruling file.")
    sub = top.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("answer", help="record the operator's choice")
    a.add_argument("--id", required=True)
    a.add_argument("--choice", required=True)
    a.add_argument("--text", default="")
    f = sub.add_parser("feedback", help="agree or disagree with the ruling")
    f.add_argument("--id", required=True)
    f.add_argument("verdict", help="agree|disagree")
    f.add_argument("--reason", required=True)
    l = sub.add_parser("link", help="point the ruling at its explain page")
    l.add_argument("--id", required=True)
    l.add_argument("--explain", required=True)
    s = sub.add_parser("show", help="print the parsed ruling")
    s.add_argument("--id", required=True)
    j = sub.add_parser("subject", help="write the explain subject dict")
    j.add_argument("--id", required=True)
    j.add_argument("--out", required=True)
    c = sub.add_parser("card", help="print the AskUserQuestion card")
    c.add_argument("--id", required=True)
    c.add_argument("--html", default="", help="explain page path")
    k = sub.add_parser("ask", help="write a run-asked ruling instead of a card")
    k.add_argument("--scope", required=True)
    k.add_argument("--question", required=True)
    k.add_argument("--option", action="append", default=None)
    k.add_argument("--recommended", default="")
    k.add_argument("--kind", default=ruling_ask.DEFAULT_KIND)
    k.add_argument("--context", default="")
    w = sub.add_parser("wait", help="poll for the operator's answer")
    w.add_argument("--id", required=True)
    w.add_argument("--timeout", type=float, default=270)
    w.add_argument("--interval", type=float, default=5)
    return top


def main(argv=None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        return _COMMANDS[args.cmd](args)
    except CliError as exc:
        print(f"ruling-cli: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ruling-cli: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
