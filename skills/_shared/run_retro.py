#!/usr/bin/env python3
"""run_retro.py — the run-retro CLI over collect, group, filter and file.

design: design-learn-retro. ``main(argv)`` runs one subcommand on ``D`` (``--design-dir``, for
all but ``known-items``): a design, spike or archived dir; no seat or fleet marker is read (B9,
B10). A missing artifact exits 0; a malformed ``--verdicts`` / ``--filed`` file exits 2.

* ``known-items --repo R [--out F]``: one ``{id, kind: "seed", retro_key, text}`` per
  ``R/three-pillars-docs/tp-designs/*/seed.md`` into F (default ``./known-items.json``).
* ``draft [--known-items F] [--repo R]``: writes ``D/retro-findings.json`` ``{drafts,
  observations, evidence_adds, tokens, filed}``, keeping its ``filed`` list (B11), and prints
  ``{"drafts": n, "observations": m, "review_needed": n > 0}``. ``review-prompt`` writes and
  prints ``D/retro-review-prompt.md``, the reviewer brief; nothing with zero drafts (B4).
* ``file [--verdicts V] --board none|<key> [--notion-skill present|absent]``: V is the verdict
  list as JSON or as a reply's last fenced json block. ``present`` means notion-ops'
  ``notion-file-upgrade-request`` is in the session's skills; a board with it absent takes the
  seed fallback, reason ``notion-skill-unavailable`` (B12). The seed path prints every modified
  seed path, one per line, for the caller to stage exactly (never a glob); the board path prints
  ``{"outbox": path, "entries": n}`` and posts nothing.
* ``record --filed F``: F is a list with one row per outbox entry the skill was called for:
  ``{slug, reply}`` (its reply line, verbatim), or the mapped ``{slug, id}`` (a row url) /
  ``{slug, reason}``. ``filed: <action> <url>`` puts the url into ``filed`` and ``decisions.md``
  with the entry's retro key and slug (a board entry is marked filed only here);
  ``not filed: <reason>`` takes the seed fallback for that entry alone, one ``not filed`` entry
  naming the reasons, and the printed ``seeds`` are staged. A new slug not in
  ``retro-outbox.json``, or a row that is neither, refuses the whole file (B13).
* ``pr-section`` prints the ``## Framework friction`` block, or nothing; ``note --title T
  [--body B]`` appends one ``### [run-retro] T`` entry, once.

``filed`` holds retro keys, slugs, ``evidence:<slug>@<key>``, ``seed:<slug>`` and
``id:<slug>:<id>``. ``decisions.md`` is written only through ``local_route_log.append_entry``,
as ``### [run-retro] <title>`` entries, which ``collect`` skips. Stdlib only; no notion-ops.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import run_retro_file as rf  # noqa: E402
from local_route_log import append_entry  # noqa: E402 — the one decisions.md writer
from run_retro_collect import collect, parse_entries  # noqa: E402
from run_retro_filter import MIN_RECURRENCE, MIN_RERUNS, apply_rrsi  # noqa: E402
from run_retro_group import group_signals  # noqa: E402

FINDINGS = "retro-findings.json"
PROMPT = "retro-review-prompt.md"
DECISIONS = "decisions.md"
PREFIX = "run-retro"
FALLBACK = "notion-skill-unavailable"
FRICTION = "## Framework friction"
VERDICTS = ("accept", "merge-with", "reject")
_FENCE = re.compile(r"```json[ \t]*\n(.*?)```", re.S)
_RETRO_KEY = re.compile(r"^retro_key:[ \t]*(\S[^\n]*?)[ \t]*$", re.M)


class Malformed(Exception):
    """A malformed ``--verdicts`` / ``--filed`` file, or a refused record or board (exit 2)."""


def _text(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError, TypeError):
        return ""


def _load(path, default, kind=dict):
    try:
        data = json.loads(_text(path))
    except ValueError:
        return default
    return data if isinstance(data, kind) else default


def _write(path, data) -> None:
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _filed(d: Path) -> tuple[dict, list]:  # (retro-findings.json, its filed marks)
    findings = _load(d / FINDINGS, {})
    marks = findings.get("filed")
    return findings, [m for m in marks if isinstance(m, str)] if isinstance(marks, list) else []


def _known(path) -> list:
    return [i for i in _load(path, [], list) if isinstance(i, dict) and "id" in i]


def _reply(path, valid) -> list:
    """``path``'s list (JSON, else its last fenced json block) of ``valid`` dicts; [] if absent."""
    if not path or not Path(path).exists():
        return []
    data, text = None, _text(path)
    for candidate in (text, *_FENCE.findall(text)[-1:]):
        try:
            data = json.loads(candidate)
            break
        except ValueError:
            continue
    if not (isinstance(data, list) and all(isinstance(x, dict) and valid(x) for x in data)):
        raise Malformed(f"{path}: not the documented list")
    return data


def _verdict_ok(v: dict) -> bool:
    return (isinstance(v.get("slug"), str) and v.get("verdict") in VERDICTS
            and (v["verdict"] != "merge-with" or isinstance(v.get("target"), str)))


def _outcome(row: dict):
    """``("filed", url)`` or ``("not filed", reason)`` for one ``record`` row, else None."""
    for key, kind in (("id", "filed"), ("reason", "not filed")):
        if isinstance(row.get(key), str) and row[key]:
            return kind, row[key]
    return rf.parse_reply(row["reply"]) if isinstance(row.get("reply"), str) else None


def _row_ok(row: dict) -> bool:
    return isinstance(row.get("slug"), str) and bool(row["slug"]) and _outcome(row) is not None


def _bullets(lines) -> str:
    return "\n".join("- " + " ".join(str(line).split()) for line in lines)


def _note(d: Path, title: str, body: str = "", *, latest_only: bool = False) -> bool:
    """Append one ``### [run-retro] <title>`` entry unless one with this body exists (or is the
    latest with this title, when ``latest_only``)."""
    path, title, body = d / DECISIONS, " ".join(title.split()), body.strip()
    same = [e["body"] for e in parse_entries(_text(path))
            if e["prefix"] == PREFIX and e["title"] == title]
    if body in (same[-1:] if latest_only else same):
        return False
    append_entry(path, f"### [{PREFIX}] {title}" + (f"\n{body}" if body else ""))
    return True


def known_items(repo) -> list:
    """One item per ``tp-designs/*/seed.md``; ``retro_key`` from its frontmatter, else None."""
    items = []
    for seed in sorted(Path(repo).glob("three-pillars-docs/tp-designs/*/seed.md")):
        text = _text(seed)
        head = text[4:].split("\n---", 1)[0] if text.startswith("---\n") else ""
        key = _RETRO_KEY.search(head)
        items.append({"id": seed.parent.name, "kind": "seed",
                      "retro_key": key.group(1) if key else None, "text": seed.parent.name})
    return items


def review_prompt(drafts: list, known: list) -> str:
    """The reviewer brief: the RRSI filter, the verdicts, the known items, the reply contract."""
    items = [{"id": k["id"], "retro_key": k.get("retro_key")} for k in known]
    example = [{"slug": d["proposed_slug"], "verdict": "accept", "reason": "<why>"} for d in drafts]
    example += [{"slug": "<slug>", "verdict": "merge-with", "target": "<known item id>",
                 "reason": "<why>"}, {"slug": "<slug>", "verdict": "reject", "reason": "<why>"}]
    return "\n".join([
        "# run-retro reviewer brief", "",
        "Act as an independent critic. Re-apply the RRSI filter to every draft below:", "",
        "1. Reusable mechanism: the retro_key names a mechanism, never only an `event:` type.",
        f"2. It recurred (count >= {MIN_RECURRENCE}), cost an operator touch, or cost "
        f"{MIN_RERUNS} or more re-runs.", "3. No known item below already covers it.", "",
        "Give each draft one verdict:", "", "- `accept`: it passes all three tests; it is filed.",
        "- `merge-with`: a known item covers it; set `target` to that item's id.",
        "- `reject`: it fails a test; give the reason; it is logged, never filed.", "",
        "## Known items", "", "```json", json.dumps(items, indent=2), "```", "",
        "## Drafts", "", "```json", json.dumps(drafts, indent=2), "```", "", "## Reply contract",
        "", "End the reply with one fenced json block, the last in the reply: a list of "
        "`{slug, verdict, reason}`, plus `target` for `merge-with`, one per draft. "
        "Shapes only, never values.", "", "```json", json.dumps(example, indent=2), "```", ""])


def cmd_known_items(a, d) -> None:
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    _write(a.out, items := known_items(a.repo))
    print(json.dumps({"known_items": str(a.out), "count": len(items)}))


def cmd_draft(a, d) -> None:
    counts = {"drafts": 0, "observations": 0, "review_needed": False}
    if d.is_dir():
        parents = d.resolve().parents
        got = collect(d, repo_root=a.repo or parents[min(2, len(parents) - 1)])
        out = apply_rrsi(group_signals(got["signals"]), _known(a.known_items))
        out["tokens"], out["filed"] = got["tokens"], _filed(d)[1]
        _write(d / FINDINGS, out)
        counts = {"drafts": len(out["drafts"]), "observations": len(out["observations"]),
                  "review_needed": bool(out["drafts"])}
    print(json.dumps(counts))


def cmd_review_prompt(a, d) -> None:
    drafts = _filed(d)[0].get("drafts") or []
    if d.is_dir() and drafts:
        (d / PROMPT).write_text(review_prompt(drafts, _known(a.known_items)), encoding="utf-8")
        print(d / PROMPT)


def _log_file(d: Path, board_arg: str, findings: dict, res: dict) -> None:
    keys = {x["proposed_slug"]: x["retro_key"] for x in findings.get("drafts") or []}
    why = [f"board `{board_arg}` is set but notion-file-upgrade-request is not in the session; "
           "accepted drafts became seed.md drafts"] if res["fallback_reason"] else []
    seeds = [Path(p).parent.name for p in res["seeds"]]
    for title, lines in (
            (f"fallback {res['fallback_reason']}", why),
            ("filed seeds", [f"{s} ({keys.get(s, '')})" for s in seeds]),
            ("outbox", [f"{e['slug']} ({e['retro_key']}) -> {e['board']}" for e in res["outbox"]]),
            ("evidence", [f"{x['seed']}: {x['retro_key']}" for x in res["evidence_adds"]]),
            ("rejected", [f"{r['slug']}: {r['reason']}" for r in res["rejected"]]),
            ("refused", [f"{r['slug']}: refused by leaks()" for r in res["refused"]])):
        if lines:
            _note(d, title, _bullets(lines))
    obs = [f"{o['retro_key']}: count {o['count']} ({o['reason']})"
           for o in findings.get("observations") or []]
    if obs:
        _note(d, "observations", "## Observations\n\n" + _bullets(obs), latest_only=True)


def _add_marks(findings: dict, base: list, res: dict) -> None:
    new = res["filed_marks"] + [f"seed:{Path(p).parent.name}" for p in res["seeds"]]
    findings["filed"] = base + [m for m in dict.fromkeys(new) if m not in base]


def cmd_file(a, d) -> None:
    verdicts = _reply(a.verdicts, _verdict_ok)
    findings, filed = _filed(d)
    if not (d.is_dir() and findings):
        return
    board, reason = (None if a.board == "none" else a.board), None
    if board is not None and a.notion_skill != "present":
        board, reason = None, FALLBACK
    done = set(filed)
    adds = [x for x in findings.get("evidence_adds") or []
            if x.get("retro_key") not in done and x.get("seed") not in done]
    try:
        res = rf.file_drafts(findings.get("drafts") or [], verdicts, board=board, design_dir=d,
                             already_filed=filed, fallback_reason=reason, evidence_adds=adds)
    except ValueError as exc:  # the feedback board, refused before anything is written
        raise Malformed(str(exc)) from exc
    _add_marks(findings, filed, res)
    _write(d / FINDINGS, findings)
    _log_file(d, a.board, findings, res)
    if board is None:
        for path in res["modified_seeds"]:
            print(path)
    else:
        print(json.dumps({"outbox": str(d / rf.OUTBOX_NAME), "entries": len(res["outbox"])}))


def _seed_not_filed(d: Path, findings: dict, why: dict) -> list:
    """The seed fallback for the outbox entries the upgrade skill did not file (``why``: slug ->
    reason): only those drafts, never over an existing slug (it gains an evidence line); one
    ``not filed`` entry names every reason. Returns the seed paths to stage."""
    drafts = [x for x in findings.get("drafts") or [] if x.get("proposed_slug") in why]
    res = rf.file_drafts(drafts, [{"slug": s, "verdict": "accept"} for s in why], board=None,
                         design_dir=d, already_filed=findings["filed"])
    _add_marks(findings, findings["filed"], res)
    shown = {s: "reason withheld (leak pattern)" if rf.leaks(r) else r[:200]
             for s, r in why.items()}
    _note(d, "not filed", _bullets(f"{s}: {r}" for s, r in shown.items()))
    return res["modified_seeds"]


def cmd_record(a, d) -> None:
    rows = _reply(a.filed, _row_ok)
    if not (d.is_dir() and rows):
        return
    findings, filed = _filed(d)
    box = _load(d / rf.OUTBOX_NAME, {}).get("entries")
    keys = ({e.get("slug"): e.get("retro_key") for e in box if isinstance(e, dict)}
            if isinstance(box, list) else {})  # slug -> retro_key of every outbox entry
    outcomes = [(r["slug"], *_outcome(r)) for r in rows]
    new = {m: (s, v) for s, k, v in outcomes
           if k == "filed" and (m := f"id:{s}:{v}") not in filed}
    why = {s: v for s, k, v in outcomes if k == "not filed" and s not in filed
           and f"seed:{s}" not in filed}  # a slug a fallback seed already marks is not new
    foreign = sorted({s for s in [*(s for s, _v in new.values()), *why] if s not in keys})
    if foreign:
        raise Malformed(f"record refused: not in {rf.OUTBOX_NAME}: {', '.join(foreign)}")
    seeds = []
    if new or why:
        marks = [m for mark, (s, _v) in new.items() for m in (mark, keys.get(s), s)]
        findings["filed"] = filed + [m for m in dict.fromkeys(marks)
                                     if isinstance(m, str) and m and m not in filed]
        seeds = _seed_not_filed(d, findings, why) if why else []
        _write(d / FINDINGS, findings)
    if new:
        _note(d, "filed ids", _bullets(f"{s}: {v}" for s, v in new.values()))
    print(json.dumps({"recorded": len(new), **({"seeds": seeds} if seeds else {})}))


def cmd_pr_section(a, d) -> None:
    """Print the ``## Framework friction`` block listing filed row ids and seed slugs."""
    filed = _filed(d)[1]
    lines = [f"- Automated upgrade request `{rid}` (`{slug}`)"
             for slug, _sep, rid in (m[3:].partition(":") for m in filed if m.startswith("id:"))]
    lines += [f"- Seed `{m[5:]}`: `three-pillars-docs/tp-designs/{m[5:]}/seed.md`"
              for m in filed if m.startswith("seed:")]
    if lines:
        print("\n".join([FRICTION, "", "Filed by run-retro from this run's record:", "", *lines]))


def cmd_note(a, d) -> None:
    print(json.dumps({"appended": d.is_dir() and _note(d, a.title, a.body or "")}))


COMMANDS = {
    "known-items": (cmd_known_items, {"--repo": {"required": True},
                                      "--out": {"default": "known-items.json"}}),
    "draft": (cmd_draft, {"--known-items": {}, "--repo": {}}),
    "review-prompt": (cmd_review_prompt, {"--known-items": {}}),
    "file": (cmd_file, {"--verdicts": {}, "--board": {"default": "none"},
                        "--notion-skill": {"choices": ("present", "absent"), "default": "absent",
                                           "help": "present: notion-file-upgrade-request is in the "
                                                   "session's skill list; absent: seed fallback"}}),
    "record": (cmd_record, {"--filed": {"required": True,
                                        "help": "[{slug, reply}]: one reply per outbox entry"}}),
    "pr-section": (cmd_pr_section, {}),
    "note": (cmd_note, {"--title": {"required": True}, "--body": {}}),
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run_retro.py", description="run-retro: a run's friction")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (_func, options) in COMMANDS.items():
        sp = sub.add_parser(name)
        sp.add_argument("--design-dir", required=name != "known-items", default="")
        for flag, kw in options.items():
            sp.add_argument(flag, **kw)
    args = parser.parse_args(argv)
    try:
        COMMANDS[args.command][0](args, Path(args.design_dir))
    except Malformed as exc:
        print(f"run_retro: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
