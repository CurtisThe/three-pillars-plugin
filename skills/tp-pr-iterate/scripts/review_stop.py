"""review_stop — the converge-time decision stop.

design: seat-escalate-first (Phase 1, Tasks 1.2-1.3)

At a two-stable converge with non-blocking notes left, `due` returns one
`question`/`decision` finalizer stop ("stop here, or fix these notes first?")
naming the notes, never the head, so `finalizer.stop_key` is the same for the
same notes at any head. Per-head coverage is only the iterate-state
`review_stop` record: a `stop` on the same head covers (the label re-run); a
`fix` covers nothing.

`notes` and `due` are pure: no config read, no I/O, no label. `follow-up.json`
residue is not an input. `settle` applies the stop's ruling: it reads the
ruling file and the iterate state, writes the `review_stop` record and the
decisions entries, and returns one action, never a dead end:

  label     a `stop` (or a `fix` at the round cap); the notes seed the follow-up
  fix       the notes re-tagged for the inline-fix contract (commit on a frozen bar)
  card      an unanswered `escalate` ruling: the operator card, `ruling: <id>` last;
            an `escalate` ruling that picked `stop` and whose only problems are
            pillar technicalities settles as `label`, its lesson logged apart
  escalate  a `resolved` choice that maps to no option (`unmappable-choice`)
  halt      an answer that maps to no option (`stop-run`, a pad, free text)

CLI: `review_stop.py settle --id I --state S --decisions D [--config C] [--root R]`
prints one JSON line, exit 0; an unknown id or unreadable input exits 2 with one
`review-stop: <why>` stderr line. Like `finalizer_cli.main`, it re-points a
`tp-designs/<slug>/` `--decisions` path at `completed-tp-designs/<slug>/` once the
Tier 5.6 archive moved the run (`finalizer_cli_ruling.archived_path`). Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED = _HERE.parents[1] / "_shared"
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_SHARED) not in sys.path:
    sys.path.append(str(_SHARED))

import finalizer_cli_ruling  # noqa: E402
import finalizer_ruling  # noqa: E402
import finding_class  # noqa: E402
import iterate_state  # noqa: E402
import project_root  # noqa: E402
import round_budget  # noqa: E402
import ruling_file  # noqa: E402

OPTIONS = (
    {"id": "stop", "label": "Stop here"},
    {"id": "fix", "label": "Fix these notes first"},
)

QUESTION = "The review converged with notes left: stop here, or fix these notes first?"


def notes(findings) -> list:
    """The non-blocking, non-sentinel findings."""
    return [
        f for f in findings
        if isinstance(f, dict)
        and f.get("verdict") != "structural"
        and not finding_class.is_sentinel(f)
    ]


def _name(note: dict) -> str:
    title = str(note.get("title") or "").strip()
    summary = str(note.get("summary") or "").strip()
    if title and summary:
        return f"{title}: {summary}"
    return title or summary or str(note.get("file") or "(unnamed note)")


def _covered(state, head) -> bool:
    record = (state or {}).get("review_stop")
    return (
        isinstance(record, dict)
        and record.get("choice") == "stop"
        and record.get("head") == head
    )


def due(state, findings, *, pr_url, head):
    """One decision stop for the leftover notes, or None."""
    leftover = notes(findings)
    if not leftover or _covered(state, head):
        return None
    lines = "\n".join(f"- {_name(n)}" for n in leftover)
    return {
        "source": "question",
        "signal": "decision",
        "target": pr_url,
        "head": head,
        "detail": {
            "question": f"{QUESTION}\nNotes:\n{lines}",
            "options": [dict(o) for o in OPTIONS],
            "notes": leftover,
        },
    }


# ---------- settle: apply the stop's ruling ----------

UNMAPPABLE = "unmappable-choice"
_IDS = tuple(o["id"] for o in OPTIONS)
_BY_LABEL = {o["label"]: o["id"] for o in OPTIONS}


class SettleError(Exception):
    """An input error: exit 2, one stderr line, nothing written."""


def _map(id_, label):
    """`stop` / `fix` by id, then by label, against `OPTIONS`; else None."""
    if id_ in _IDS:
        return id_
    return _BY_LABEL.get(str(label or "").strip())


def _options(parsed) -> list:
    """The ruling's own options: its nested `ruling` dict, else the result itself."""
    result = parsed.get("ruling") if isinstance(parsed.get("ruling"), dict) else {}
    inner = result.get("ruling")
    options = (inner if isinstance(inner, dict) else result).get("options")
    return options if isinstance(options, list) else []


TECHNICALITIES = ("pillar-change:", "pillar-basis-missing:")


def _technicality_stop(parsed) -> bool:
    """An `escalate` ruling that picked `stop` and has only pillar-technicality problems."""
    result = parsed.get("ruling")
    problems = result.get("problems") if isinstance(result, dict) else None
    if not isinstance(problems, list) or not problems:
        return False
    if not all(isinstance(p, str) and p.startswith(TECHNICALITIES) for p in problems):
        return False
    pick = finalizer_ruling.chosen(_options(parsed))
    return bool(pick) and _map(pick.get("id"), pick.get("label")) == "stop"


def _retag(note: dict) -> dict:
    """A note re-tagged for the inline-fix contract: passes `partition` frozen or not."""
    return {**note, "verdict": "structural", "source": "code-review",
            "comment_id": None, "review_stop": True}


def _load_json(path, flag: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SettleError(f"{flag} unreadable ({exc})") from None
    if not isinstance(data, dict):
        raise SettleError(f"{flag} is not a JSON object")
    return data


def _log(decisions, title: str, rid: str, lines) -> None:
    """Append one `### [review-stop] …` decisions entry; fail open on stderr."""
    text = f"### [review-stop] {title} — {rid}\n" + "".join(f"- {ln}\n" for ln in lines)
    target = Path(decisions)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        lead = "\n" if target.exists() and target.stat().st_size > 0 else ""
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(lead + text)
    except OSError as exc:
        print(f"review-stop: decisions entry not written ({exc.__class__.__name__})",
              file=sys.stderr)


def _apply(choice: str, rid: str, state_path, decisions, config) -> dict:
    """Record `choice` for the state's head and return `label` or `fix`."""
    if config is not None and not isinstance(config, dict):
        config = _load_json(config, "--config")
    state = _load_json(state_path, "--state")
    head = state.get("last_codereview_head_sha")
    if not isinstance(head, str) or not head:
        raise SettleError("--state has no last_codereview_head_sha")
    leftover = notes(state.get("last_codereview_findings") or [])
    iteration = state.get("iteration")
    iteration = iteration if isinstance(iteration, int) and iteration >= 0 else 0
    cap = round_budget.limits(config, state)["round_cap"]
    if choice == "fix" and iteration >= cap:
        choice = "stop"
        _log(decisions, "fix downgraded: round cap", rid, [
            f"**Decided**: label; iteration {iteration} has reached the round cap {cap}.",
            "**Reasoning**: a fix round would exceed the cap, so the notes seed the "
            "follow-up instead."])
    state["review_stop"] = {"choice": choice, "head": head, "ruling_id": rid,
                            "iteration": iteration}
    if choice == "fix":  # N2: a fix that commits nothing still spends a round
        state["budget_last_action"] = "fix"
    iterate_state.write_state_atomic(Path(state_path), state)
    if choice == "fix":
        return {"action": "fix", "notes": [_retag(n) for n in leftover]}
    _log(decisions, "follow-up seed notes", rid, [
        f"**Decided**: stop at head {head[:12]}; these notes seed the follow-up.",
        *(f"note: {_name(n)}" for n in leftover)])
    return {"action": "label"}


def settle(root, rid, *, state_path, decisions, config=None) -> dict:
    """Apply the review-stop ruling `rid` under `root`: one action dict.

    The choice is the operator's answer (`ruling_file.answer_of`) when there is
    one, else the chosen option of a `resolved` ruling, mapped to `stop`/`fix` by
    id, then by label. `config` is a dict, a JSON path or None (the defaults).
    Raises `SettleError` on an unknown id or unreadable input.
    """
    path = ruling_file.find(root, rid)
    if path is None:
        raise SettleError(f"no ruling for id {rid!r} under "
                          f"{Path(root) / ruling_file.RULINGS_REL}")
    try:
        parsed = ruling_file.parse(path)
    except (ValueError, OSError) as exc:  # a corrupt `## Ruling` block, an unreadable file
        raise SettleError(f"ruling {rid!r} unreadable ({exc.__class__.__name__})") from None
    answer = ruling_file.answer_of(parsed)
    outcome = parsed["front"].get("outcome")
    if answer is not None:
        choice = _map(answer, answer)
        if choice is None:  # stop-run, a pad or free text: halt, never a re-ask
            _log(decisions, f"halt: {answer}", rid, [
                "**Decided**: halt; the answer maps to no review-stop option, so the "
                "loop stops for the operator (tp:needs-human-attention)."])
            return {"action": "halt", "answer": answer}
    elif outcome == "resolved":
        pick = finalizer_ruling.chosen(_options(parsed))
        choice = _map(pick.get("id"), pick.get("label")) if pick else None
        if choice is None:
            return {"action": "escalate", "reason": UNMAPPABLE}
    elif outcome == "escalate" and _technicality_stop(parsed):
        inner = parsed["ruling"].get("ruling")
        lesson = inner.get("lesson_proposal") if isinstance(inner, dict) else None
        _log(decisions, "lesson filed separately", rid, [
            "**Decided**: settle as stop; the escalation was a pillar technicality, "
            "not a blocker.",
            *(f"problem: {p}" for p in parsed["ruling"]["problems"]),
            *([f"lesson: {lesson.get('action')} ({lesson.get('layer')}): "
               f"{lesson.get('text')}"] if isinstance(lesson, dict) else [])])
        choice = "stop"
    elif outcome == "escalate":
        return {"action": "card", "question": f"{parsed['question']}\nruling: {rid}",
                "options": [o["label"] for o in OPTIONS]}
    else:
        return {"action": "escalate", "reason": UNMAPPABLE}
    return _apply(choice, rid, state_path, decisions, config)


def _parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="review_stop.py",
                                  description="Apply a review-stop ruling.")
    sub = top.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("settle", help="map a ruling to label/fix/card/escalate/halt")
    for flag in ("--id", "--state", "--decisions"):
        s.add_argument(flag, required=True)
    s.add_argument("--config", default=None)
    s.add_argument("--root", default=None)
    return top


def main(argv=None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    root = args.root or project_root.find_project_root() or Path.cwd()
    try:
        decisions = finalizer_cli_ruling.archived_path(args.decisions)  # Tier 7: archived
        out = settle(root, args.id, state_path=args.state, decisions=decisions,
                     config=args.config)
    except (SettleError, OSError) as exc:
        print(f"review-stop: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
