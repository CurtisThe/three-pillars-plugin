#!/usr/bin/env python3
"""certify_ledger — the shipped half of the certification sweep: dirs, coherence, ledger.

design: audit-pass-does-not-bind (Tasks 9.3, 9.4, 10.3; dd §Interfaces [F10][R1][B], N2, N6, N10, P10).

`resolve_design_dir(root, slug)`: the in-flight design dir, else the archived one, else
`FileNotFoundError`. `coherence_state(root, slug)`: ledger + no open pending entry →
`certified`; no ledger + open entry → `pending`; both → `stale-pending`; neither (or an
unresolvable slug, N6) → `missing`. An open entry is an `### ` heading in `known_issues.md` or
`known_issues_low.md` (never the resolved or cold archive) holding `sweep ledger pending` and the slug (never the id).
`gate_outcome(state)`: the coherence gate's action — `skip` for `pending` only, `assert` for
`certified`, `fail` otherwise.

`ledger render` writes `sweep-ledger.md`: a header comment (certified SHA, date, sha256
of the committed inventory + triage snapshots, paths relative to the ledger's dir), one
`## Sweep` row per inventory row and a `## Self-certification` table. Statuses are
certify's (`unverified:cap` / `:budget` distinct); triage rows read `not-a-claim`,
`unverified:cap` or `unverified`; a claim row with no result is `unverified`
(`no-result`). `ledger verify` re-renders from the header's snapshots (never a live
inventory) and exits 1 on any difference. `issues render|apply` live in `certify_issues.py`;
`apply` files each miss under a placeholder `M-new-<slug>` (numbered at landing), never a
next-free number: into `known_issues.md` (`--known-issues K`), or on a design branch, which never edits a
living doc, into the design's fragment (`--fragment F`, the docs read beside its `changes/` directory).

    certify_ledger.py design-dir <slug> [--root R]    # prints resolve_design_dir(R, slug)
    certify_ledger.py ledger render --inventory I --triage T [--result R]...
                      [--self-result S] --out F [--date D] [--sha S] [--after-repair N]
    certify_ledger.py ledger verify --ledger L [--result R]... [--self-result S]
    certify_ledger.py issues render [--result R]... [--self-result S] --out P
    certify_ledger.py issues apply --pending P (--known-issues K [--resolved R] | --fragment F)

Exit 0 ok, 1 verify mismatch, 2 bad input. No subprocess, no git, no dev-only imports.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import certify_issues

DOCS = Path("three-pillars-docs")
IN_FLIGHT = DOCS / "tp-designs"
ARCHIVED = DOCS / "completed-tp-designs"
KNOWN_ISSUES = DOCS / "known_issues.md"
LEDGER_NAME = "sweep-ledger.md"
PENDING_PHRASE = "sweep ledger pending"
STATES = ("certified", "pending", "stale-pending", "missing")
EXIT_OK, EXIT_MISMATCH, EXIT_BAD_INPUT = 0, 1, 2


def resolve_design_dir(root, slug: str) -> Path:
    """The design dir for `slug`: in-flight, else archived, else FileNotFoundError."""
    root = Path(root)
    for base in (IN_FLIGHT, ARCHIVED):
        candidate = root / base / slug
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"no design dir for {slug!r} under {IN_FLIGHT} or {ARCHIVED}")


def open_pending_heading(root, slug: str) -> str | None:
    """The first open "sweep ledger pending" heading for `slug` (without `### `), else None.

    The slug must match a whole heading token — bounded by a non-slug character or the line
    edge — so it never matches a longer slug that merely contains it (`audit-pass` does not
    match a heading written for `audit-pass-does-not-bind`).
    """
    token = re.compile(r"(?<![a-zA-Z0-9-])" + re.escape(slug) + r"(?![a-zA-Z0-9-])")
    for rel in certify_issues.LIVE_ISSUE_DOCS:  # known_issues.md, then known_issues_low.md
        path = Path(root) / rel
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("### ") and PENDING_PHRASE in line and token.search(line):
                return line[4:].strip()
    return None


def coherence_state(root, slug: str) -> str:
    """One of `STATES`, per the mapping in the module docstring."""
    try:
        design = resolve_design_dir(root, slug)
    except FileNotFoundError:
        return "missing"
    ledger = (design / LEDGER_NAME).is_file()
    pending = open_pending_heading(root, slug) is not None
    if ledger:
        return "stale-pending" if pending else "certified"
    return "pending" if pending else "missing"


GATE_OUTCOMES = {"certified": "assert", "pending": "skip", "stale-pending": "fail",
                 "missing": "fail"}


def gate_outcome(state: str) -> str:
    """The coherence gate's action for a `coherence_state`: `skip` only for `pending` (F3)."""
    if state not in GATE_OUTCOMES:
        raise ValueError(f"unknown coherence state {state!r}")
    return GATE_OUTCOMES[state]


# --- ledger model / render / parse (Task 9.4) ------------------------------------------

HEADER_MARK = "sweep-ledger v1"
_HEADER_RE = re.compile(r"^<!-- " + re.escape(HEADER_MARK) + r" (\{.*\}) -->$", re.MULTILINE)
_CELL_SPLIT = re.compile(r"(?<!\\)\|")
SWEEP_COLUMNS = ("row", "design", "file", "phrase", "claim", "status", "reasons")
SELF_COLUMNS = ("claim", "guard", "status", "reasons")
TRIAGE_STATUS = {"not-a-claim": "not-a-claim", "cap": "unverified:cap"}


def status_label(entry: dict) -> str:
    """The ledger status: the certify status, `unverified:cap`/`:budget` kept apart."""
    status = str(entry.get("status"))
    reasons = entry.get("reasons") or []
    if status == "unverified":
        for reason in ("cap", "budget"):
            if reason in reasons:
                return f"unverified:{reason}"
    return status


def _by_claim(results: list[dict]) -> dict:
    return {entry.get("id"): (certify_issues.stem(res.get("name")), entry)
            for res in results for entry in res.get("claims") or []}


def _claim_row(base: dict, tri: dict, found) -> dict:
    if found is None:
        return {**base, "claim": str(tri.get("claim")), "status": "unverified",
                "reasons": "no-result"}
    name, entry = found
    return {**base, "claim": f"{name}#{entry.get('id')}", "status": status_label(entry),
            "reasons": ", ".join(entry.get("reasons") or [])}


def ledger_model(inventory: dict, triage: dict, results: list[dict], self_result) -> dict:
    """`{rows, self_rows}`: one row per inventory row, one self row per self claim."""
    by_row = {t.get("row"): t for t in triage.get("rows") or []}
    found = _by_claim(results)
    rows = []
    for n, inv in enumerate(inventory.get("rows") or [], start=1):
        tri = by_row.get(n)
        if tri is None:
            raise ValueError(f"inventory row {n} is untriaged")
        base = {"row": n, "design": str(inv["design"]), "file": f"{inv['file']}:{inv['line']}",
                "phrase": str(inv["phrase"])}
        if tri.get("triage") == "claim":
            rows.append(_claim_row(base, tri, found.get(tri.get("claim"))))
        else:
            rows.append({**base, "claim": "",
                         "status": TRIAGE_STATUS.get(tri.get("triage"), "unverified"),
                         "reasons": str(tri.get("reason"))})
    self_rows = [{"claim": f"{certify_issues.stem(self_result.get('name'))}#{e.get('id')}",
                  "guard": str(e.get("guard")), "status": status_label(e),
                  "reasons": ", ".join(e.get("reasons") or [])}
                 for e in (self_result or {}).get("claims") or []]
    return {"rows": rows, "self_rows": self_rows}


def _cell(value) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def _table(columns, rows) -> list[str]:
    out = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    return out + ["| " + " | ".join(_cell(r[c]) for c in columns) + " |" for r in rows]


def _counts(rows) -> dict:
    counts: dict = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return dict(sorted(counts.items()))


def render_model(model: dict, meta: dict) -> str:
    """The ledger markdown for `model`; `meta` = sha, date, snapshot paths and digests."""
    header = {**meta, "counts": _counts(model["rows"]), "self_counts": _counts(model["self_rows"])}
    counts = " · ".join(f"{k} {v}" for k, v in header["counts"].items()) or "none"
    lines = ["# Sweep ledger", "", f"<!-- {HEADER_MARK} {json.dumps(header, sort_keys=True)} -->",
             "", f"Certified at `{meta.get('sha')}` on {meta.get('date')}. Inventory "
             f"`{meta.get('inventory')}` (sha256 `{meta.get('inventory_sha256')}`): "
             f"{len(model['rows'])} rows. Statuses: {counts}. Unverified after certifier "
             f"repair: {meta.get('unverified_after_repair')}.", "", "## Sweep", ""]
    lines += _table(SWEEP_COLUMNS, model["rows"])
    lines += ["", "## Self-certification", ""]
    lines += _table(SELF_COLUMNS, model["self_rows"]) if model["self_rows"] else ["No self rows."]
    return "\n".join(lines) + "\n"


def _cells(line: str) -> list[str]:
    inner = line.strip()[1:-1]
    return [c.strip().replace("\\|", "|") for c in _CELL_SPLIT.split(inner)]


def parse_ledger(text: str) -> dict:
    """`{header, rows, self_rows}` from a rendered ledger."""
    m = _HEADER_RE.search(text)
    header = json.loads(m.group(1)) if m else {}
    tables: dict = {"## Sweep": [], "## Self-certification": []}
    section = None
    for line in text.splitlines():
        if line.startswith("## "):
            section = line.strip()
        elif section in tables and line.startswith("| "):
            tables[section].append(_cells(line))
    rows = [dict(zip(SWEEP_COLUMNS, c)) for c in tables["## Sweep"][1:]]
    for r in rows:
        r["row"] = int(r["row"])
    self_rows = [dict(zip(SELF_COLUMNS, c)) for c in tables["## Self-certification"][1:]]
    return {"header": header, "rows": rows, "self_rows": self_rows}


# --- render from files / verify (N10) ---------------------------------------------------

def _sha(results: list[dict], self_result, fallback=None) -> str:
    shas = {r.get("sha") for r in [*results, *([self_result] if self_result else [])]}
    if len(shas) > 1:
        raise ValueError(f"results disagree on the certified sha: {sorted(map(str, shas))}")
    sha = next(iter(shas), None) or fallback
    if not sha:
        raise ValueError("no certified sha: pass a result or --sha")
    return sha


def _digest(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def render_ledger(*, inventory_path, triage_path, results, self_result, out, date=None,
                  sha=None, after_repair=None) -> str:
    """Render the ledger for the snapshots at `inventory_path` / `triage_path`."""
    base = Path(out).parent
    meta = {"sha": _sha(results, self_result, sha),
            "date": date or datetime.date.today().isoformat(),
            "inventory": Path(os.path.relpath(inventory_path, base)).as_posix(),
            "inventory_sha256": _digest(inventory_path),
            "triage": Path(os.path.relpath(triage_path, base)).as_posix(),
            "triage_sha256": _digest(triage_path), "unverified_after_repair": after_repair}
    model = ledger_model(_load(inventory_path), _load(triage_path), results, self_result)
    return render_model(model, meta)


def verify(ledger_path, results: list[dict], self_result) -> list[str]:
    """Differences between the ledger and a re-render from the snapshots its header names."""
    ledger_path = Path(ledger_path)
    text = ledger_path.read_text(encoding="utf-8")
    header = parse_ledger(text)["header"]
    if not header:
        return ["no sweep-ledger header"]
    snaps = {key: ledger_path.parent / str(header.get(key)) for key in ("inventory", "triage")}
    problems = [f"{key} snapshot {header.get(key)} is missing or changed"
                for key, snap in snaps.items()
                if not snap.is_file() or _digest(snap) != header.get(f"{key}_sha256")]
    if problems:
        return problems
    again = render_ledger(inventory_path=snaps["inventory"], triage_path=snaps["triage"],
                          results=results, self_result=self_result, out=ledger_path,
                          date=header.get("date"), sha=header.get("sha"),
                          after_repair=header.get("unverified_after_repair"))
    return [] if again == text else ["ledger differs from a re-render of its snapshots"]


# --- CLI ------------------------------------------------------------------------------

def _result(path) -> dict:
    res = _load(path)
    if not isinstance(res, dict) or res.get("complete") is not True:
        raise ValueError(f"{path}: not a complete certify result")
    return res


def _results(args) -> tuple[list[dict], dict | None]:
    self_result = _result(args.self_result) if args.self_result else None
    return [_result(p) for p in args.result], self_result


def cmd_ledger_render(args) -> int:
    results, self_result = _results(args)
    text = render_ledger(inventory_path=args.inventory, triage_path=args.triage,
                         results=results, self_result=self_result, out=args.out,
                         date=args.date, sha=args.sha, after_repair=args.after_repair)
    Path(args.out).write_text(text, encoding="utf-8")
    return EXIT_OK


def cmd_ledger_verify(args) -> int:
    results, self_result = _results(args)
    problems = verify(args.ledger, results, self_result)
    for problem in problems:
        print(f"ledger verify: {problem}", file=sys.stderr)
    return EXIT_MISMATCH if problems else EXIT_OK


def cmd_issues_render(args) -> int:
    results, self_result = _results(args)
    Path(args.out).write_text(certify_issues.render(results, self_result), encoding="utf-8")
    return EXIT_OK


def cmd_issues_apply(args) -> int:
    pending = Path(args.pending).read_text(encoding="utf-8")
    if args.fragment and args.resolved:
        raise ValueError("--resolved goes with --known-issues, not --fragment")
    if args.fragment:
        docs = Path(args.fragment).resolve().parent.parent  # three-pillars-docs/changes/<slug>.md
        ids = certify_issues.apply_to_fragment(pending, args.fragment, docs / "known_issues.md")
    else:
        ids = certify_issues.apply(pending, args.known_issues, args.resolved)
    print(json.dumps({"applied": ids}))
    return EXIT_OK


def cmd_design_dir(args) -> int:
    print(resolve_design_dir(args.root, args.slug))
    return EXIT_OK


def _with_results(p) -> None:
    p.add_argument("--result", action="append", default=[])
    p.add_argument("--self-result")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="certify_ledger.py", description=__doc__.split("\n")[0])
    top = parser.add_subparsers(dest="cmd", required=True)
    where = top.add_parser("design-dir")
    where.add_argument("slug")
    where.add_argument("--root", default=".")
    where.set_defaults(func=cmd_design_dir)
    ledger = top.add_parser("ledger").add_subparsers(dest="sub", required=True)
    render = ledger.add_parser("render")
    for opt in ("--inventory", "--triage", "--out"):
        render.add_argument(opt, required=True)
    _with_results(render)
    render.add_argument("--date")
    render.add_argument("--sha")
    render.add_argument("--after-repair", type=int)
    render.set_defaults(func=cmd_ledger_render)
    ver = ledger.add_parser("verify")
    ver.add_argument("--ledger", required=True)
    _with_results(ver)
    ver.set_defaults(func=cmd_ledger_verify)
    issues = top.add_parser("issues").add_subparsers(dest="sub", required=True)
    irender = issues.add_parser("render")
    _with_results(irender)
    irender.add_argument("--out", required=True)
    irender.set_defaults(func=cmd_issues_render)
    iapply = issues.add_parser("apply")
    iapply.add_argument("--pending", required=True)
    target = iapply.add_mutually_exclusive_group(required=True)
    target.add_argument("--known-issues")
    target.add_argument("--fragment")
    iapply.add_argument("--resolved")
    iapply.set_defaults(func=cmd_issues_apply)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"certify_ledger: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT


if __name__ == "__main__":
    sys.exit(main())
