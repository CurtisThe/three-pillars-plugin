"""Write, validate and report ``escape-ledger.ndjson`` rows.

The ledger sits next to ``dispatch-telemetry.ndjson``; each row records what
happened to one local-engine finding (kept, dropped, downgraded, or added by
the Opus check).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import dispatch_log  # noqa: E402
import role_engine  # noqa: E402

DISPOSITIONS = ("kept", "dropped", "downgraded", "opus-added")
ROLES = role_engine.ENGINE_ROLES
SERVED = ("sonnet-busy",)
NDJSON_NAME = "escape-ledger.ndjson"
CHECK_DIR = "opus-check"  # finder_round.CHECK_NAME
REPLY = "reply.md"  # round_scratch.REPLY
MANIFEST = "angles.json"  # round_scratch.MANIFEST / finder_round.MANIFEST
CAPPED = "capped"  # agent_caps.CAP_FIELD — a capped agent's row, no disposition


def row(role, engine, design, step, finding_id, disposition, caught_by,
        defect_class, *, served=None) -> dict:
    """Build one escape row; ValueError outside the closed sets."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; expected one of {ROLES}")
    if disposition not in DISPOSITIONS:
        raise ValueError(
            f"unknown disposition {disposition!r}; expected one of {DISPOSITIONS}")
    if served is not None and served not in SERVED:
        raise ValueError(f"unknown served {served!r}; expected one of {SERVED}")
    out = {"role": role, "engine": engine, "design": design, "step": step,
           "finding_id": finding_id, "disposition": disposition,
           "caught_by": caught_by, "defect_class": defect_class}
    if served is not None:
        out["served"] = served
    return out


def from_audit(envelope, slot, design) -> list:
    """Rows from a synth envelope's optional ``escape_dispositions[]``.

    Bad items are skipped with one stderr note each; never raises.
    """
    items = envelope.get("escape_dispositions") if isinstance(envelope, dict) else None
    if not isinstance(items, list):
        return []
    rows = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            print(f"escape_ledger: skipped escape_dispositions[{i}]: not an object",
                  file=sys.stderr)
            continue
        try:
            rows.append(row("council_member", "local", design, slot,
                            item.get("from"), item.get("disposition"), "synth",
                            item.get("defect_class"), served=item.get("served")))
        except ValueError as exc:
            print(f"escape_ledger: skipped escape_dispositions[{i}]: {exc}",
                  file=sys.stderr)
    return rows


def _parse_reply(text):
    """Parse the whole text as JSON, else the last ```json fence; None on failure."""
    candidates = [text] + [m.strip() for m in
                           reversed(re.findall(r"```json\s*(.*?)```", text, re.S))][:1]
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def from_review(round_dir, design) -> list:
    """Rows from a round's Opus-check reply plus its ``dispositions.json``.

    Never raises; an incomplete ledger prints one ``ledger-incomplete`` note.
    """
    rd = Path(round_dir)
    step = rd.name

    def note(msg):
        print(f"escape_ledger: ledger-incomplete: {msg}", file=sys.stderr)

    served_by_finder = {}
    try:
        manifest = json.loads((rd / MANIFEST).read_text(encoding="utf-8"))
        for entry in manifest.get("angles") or ():
            name = entry.get("name") if isinstance(entry, dict) else None
            served = entry.get("served") if isinstance(entry, dict) else None
            if isinstance(name, str) and served in SERVED:
                served_by_finder[name] = served
    except (OSError, ValueError, UnicodeDecodeError):
        pass  # no (or unreadable) manifest: no tag, never an error

    def served_for(fid):
        if not isinstance(fid, str):
            return None
        return served_by_finder.get(fid.split("#", 1)[0])

    def add(rows, fid, disp, cls, served):
        served = served if served is not None else served_for(fid)
        try:
            rows.append(row("review_finder", "local", design, step, fid, disp,
                            CHECK_DIR, cls, served=served))
        except ValueError as exc:
            print(f"escape_ledger: skipped {fid!r}: {exc}", file=sys.stderr)

    try:
        reply = _parse_reply(
            (rd / CHECK_DIR / REPLY).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        note(f"no check reply: {exc}")
        return []
    findings = reply.get("findings") if reply else None
    if not isinstance(findings, list):
        note("check reply unparseable")
        return []
    rows = []
    for f in findings:
        esc = f.get("escape") if isinstance(f, dict) else None
        if isinstance(esc, dict):
            add(rows, esc.get("from"), esc.get("disposition"), f.get("class"),
                esc.get("served"))
    try:
        side = json.loads((rd / CHECK_DIR / "dispositions.json")
                          .read_text(encoding="utf-8"))
        dropped = side["dropped"]
        if not isinstance(dropped, list):
            raise ValueError("dropped is not a list")
    except (OSError, ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        note(f"no usable dispositions sidecar: {exc}")
        return rows
    for d in dropped:
        if isinstance(d, dict):
            add(rows, d.get("from"), "dropped", d.get("class"), d.get("served"))
        else:
            add(rows, d, "dropped", None, None)
    return rows


def append(design_dir, rows) -> Path:
    """Append rows to ``escape-ledger.ndjson``: one O_APPEND write per row."""
    d = dispatch_log.resolve_dir(design_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / NDJSON_NAME
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        for r in rows:
            os.write(fd, (json.dumps(r, sort_keys=True) + "\n").encode())
    finally:
        os.close(fd)
    return path


def report(paths) -> dict:
    """Per-role counts and escape rate over ledger files.

    escape_rate = opus_added / (kept + opus_added), None on a zero
    denominator. ``served: sonnet-busy`` rows are counted apart as
    ``sonnet_busy`` and left out of every other figure. A capped-agent row
    (``capped: true``, no ``disposition`` — ``agent_caps.ledger_row``, one-cheap-engine
    Task 3.2) is counted apart as ``capped`` the same way; both keys are dropped
    when zero.
    """
    out = {}
    for p in paths:
        try:
            lines = Path(p).read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict):
                continue
            capped = r.get(CAPPED) is True
            if not capped and r.get("disposition") not in DISPOSITIONS:
                continue
            role = r.get("role")
            if not isinstance(role, str):
                continue
            s = out.setdefault(role, {"n": 0, "kept": 0, "dropped": 0,
                                      "downgraded": 0, "opus_added": 0,
                                      "sonnet_busy": 0, "capped": 0})
            if capped:
                s["capped"] += 1
                continue
            if r.get("served") == "sonnet-busy":
                s["sonnet_busy"] += 1
                continue
            s["n"] += 1
            s[r["disposition"].replace("-", "_")] += 1
    for s in out.values():
        denom = s["kept"] + s["opus_added"]
        s["escape_rate"] = s["opus_added"] / denom if denom else None
        for apart in ("sonnet_busy", "capped"):
            if not s[apart]:
                del s[apart]
    return out


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="escape_ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("report")
    rp.add_argument("paths", nargs="+")
    aa = sub.add_parser("append-audit")
    aa.add_argument("--envelope", required=True)
    aa.add_argument("--slot", required=True)
    aa.add_argument("--design-dir", required=True)
    ar = sub.add_parser("append-review")
    ar.add_argument("--round-dir", required=True)
    ar.add_argument("--design-dir", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "report":
        print(json.dumps(report(a.paths), sort_keys=True))
        return 0
    if a.cmd == "append-audit":
        try:
            env = json.loads(Path(a.envelope).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"escape_ledger: cannot read envelope: {exc}", file=sys.stderr)
            return 1
        rows = from_audit(env, a.slot, Path(a.design_dir).name)
    else:
        rows = from_review(a.round_dir, Path(a.design_dir).name)
    if rows:
        append(a.design_dir, rows)
    print(f"appended {len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
