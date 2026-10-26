"""finder_retry — settle a finished segment finder, and retry a capped one.

design: finder-cap-coverage (Task 1.3)

`settle` is the mechanical cap step for one segment slot: the driver runs it after
each segment finder, and the merge (Task 1.7) runs it anyway for any entry the
driver skipped. It reads the reply with the same strict parser the converge step
uses, so an outcome is never decided by a looser read, and it decides exactly one
of `OUTCOMES`:

- `delivered`  — the reply parses and is not placeholder-only; it is left untouched.
- `partial`    — the reply is missing, empty or placeholder-only and the shipped
                 transport (Task 1.1) harvested a finding or a progress line.
- `capped`     — the same, with nothing to harvest.
- `unparseable`— a NON-EMPTY reply that fails to parse from a finder that was not
                 capped: today's path, never retried (Behavior 7).

A placeholder-only reply is a NON-EMPTY findings list whose every item is
`capped: true` — what `agent_caps.put_capped` writes when it found nothing — so
the driver skipping `put-capped` can never lift a segment to `delivered`.
Progress lines alone write `{"findings": []}` directly: `put_capped` with an empty
list would write the junk `{"text": "", "capped": true}` finding.

Every call writes the entry's `telemetry` in one atomic `angles.json` write.
The capped segment's re-plan (`split_segment`, `retry`) lives in `finder_split`;
this module re-exports both and keeps the `settle`/`retry` CLI.
`finder_coverage` and this module import each other only inside functions.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_SHARED = _HERE.parents[1] / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import agent_caps  # noqa: E402
import agent_caps_watch  # noqa: E402
import finder_round  # noqa: E402
import finder_segments  # noqa: E402
import review_merge  # noqa: E402
from finder_split import retry, split_segment  # noqa: E402,F401 — re-exported

MANIFEST = finder_round.MANIFEST
UNCOVERED_MARK = "re-covered-by-opus-check"  # finder_round's parse-lift mark
OUTCOMES = ("delivered", "partial", "capped", "retried", "unparseable", "skipped")


def _fail(msg) -> int:
    print(f"finder_retry: {msg}", file=sys.stderr)
    return 2


def _read_manifest(round_dir):
    try:
        return json.loads((Path(round_dir) / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _fail(f"cannot read manifest: {exc}")


def _find(manifest, angle):
    for e in manifest.get("angles") or ():
        if e.get("name") == angle:
            return e
    return None


def _slot_dir(round_dir, entry):
    """The slot dir holding `caps.json`/`spawn.json`: the reply's parent."""
    reply = entry.get("reply_path") or ""
    return Path(round_dir) / entry["name"] if not reply else Path(reply).parent


def _stopped(round_dir, entry) -> bool:
    """The caps watch stopped this slot (`caps.json` `stopped: true`)."""
    try:
        rec = json.loads((_slot_dir(round_dir, entry) / agent_caps_watch.STATE)
                         .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(isinstance(rec, dict) and rec.get("stopped"))


def _reply_text(entry, round_dir) -> str:
    reply = entry.get("reply_path") or ""
    path = Path(reply) if reply else Path(round_dir) / entry["name"] / agent_caps_watch.REPLY
    path = path if path.is_absolute() else Path(round_dir) / path
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _placeholder_only(findings) -> bool:
    """A NON-EMPTY findings list whose every item is `capped: true`."""
    return bool(findings) and all(isinstance(f, dict) and f.get(agent_caps.CAP_FIELD)
                                 for f in findings)


def _write_reply(path, findings) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps({"findings": findings}, sort_keys=True) + "\n",
                          encoding="utf-8")


def _telemetry(entry, seg, outcome, covered, part, elapsed_s, old):
    """The entry's telemetry block; an unstated `elapsed_s`/`covered_files` keeps the old."""
    keep = elapsed_s is None and part is None
    return {
        "rung": entry.get("rung"),
        "attempt": entry.get("attempt"),
        "lines": seg.get("lines"),
        "files": len(seg.get("files") or ()),
        "elapsed_s": elapsed_s if elapsed_s is not None
        else (old.get("elapsed_s") if keep else None),
        "outcome": outcome,
        "covered_files": covered if covered or not keep else (old.get("covered_files") or []),
        "partial_malformed": part.malformed if part else 0,
        "sources": list(part.sources) if part else [],
        "transcript_found": bool(part.transcript_found) if part else False,
        # The Strata attempt's time, set aside when the entry moved to Sonnet (N2).
        **({"strata_elapsed_s": old["strata_elapsed_s"]}
           if old.get("strata_elapsed_s") is not None else {}),
    }


def retry_used(manifest, angle) -> int:
    """Retry runs already spent for one angle: the sum of `attempt - 1` over its
    segment entries (one per half run, one per Sonnet re-run)."""
    return sum((e.get("attempt") or 1) - 1 for e in manifest.get("angles") or ()
               if (e.get("segment") or {}).get("angle") == angle)


def budget(manifest, angle) -> int:
    """The per-angle retry budget: the `max_segments` the segment blocks carry
    (Task 1.5), else `finder_segments.DEFAULTS` on an old manifest."""
    for e in manifest.get("angles") or ():
        seg = e.get("segment") or {}
        if seg.get("angle") == angle and isinstance(seg.get("max_segments"), int):
            return seg["max_segments"]
    return finder_segments.DEFAULTS["max_segments"]


def _next(entry, manifest, final) -> str:
    """The budget-first transition for a capped entry: `retry`, `sonnet` or
    `uncovered`. `final` (the merge's cap step) never transitions."""
    if final:
        return "uncovered"
    angle = (entry.get("segment") or {}).get("angle")
    used, free = retry_used(manifest, angle), budget(manifest, angle)
    if str(entry.get("rung") or "").startswith("sonnet"):
        return "uncovered"
    attempt = entry.get("attempt") or 1
    if attempt >= 2 and used + 1 <= free:
        return "sonnet"
    if attempt == 1 and used + 2 <= free:
        return "retry"
    return "uncovered"


def _to_sonnet(entry, slot_dir) -> None:
    """Take the Sonnet transition on the entry and clear the slot's stale files
    so the caps watch never stops the re-run on the old agent's clock, and the
    re-run inherits neither the first run's elapsed time nor its coverage; that
    time is kept apart as `strata_elapsed_s`, never on the Sonnet rung (N2)."""
    entry["rung"] = "sonnet-xhigh"
    entry["attempt"] = (entry.get("attempt") or 1) + 1
    for name in (agent_caps_watch.REPLY, agent_caps_watch.STATE, agent_caps_watch.SPAWN):
        try:
            (Path(slot_dir) / name).unlink()
        except OSError:
            pass
    tel = entry.get("telemetry")
    if isinstance(tel, dict):
        if tel.get("elapsed_s") is not None:
            tel["strata_elapsed_s"] = tel["elapsed_s"]
        tel["elapsed_s"] = None
        tel["covered_files"] = []


def _mark_uncovered(entry) -> None:
    """Every `uncovered` answer carries the parse-lift mark, so the converge step
    never refuses the round as `unparseable-review-angle`."""
    entry["unparseable"] = UNCOVERED_MARK


def _cmd_retry(args) -> int:
    out = retry(args.round_dir, args.angle, repo=args.repo)
    if out.get("exit"):
        return out["exit"]
    print(json.dumps({"next": out["next"]}))
    return 0


def settle(round_dir, angle, *, capped=False, elapsed_s=None, final=False) -> dict:
    """Decide one finished segment entry's outcome and record it in the manifest.

    Returns `{"outcome", "next", "covered_files"}`. On a `capped` outcome `next`
    comes from the budget-first rule (`_next`): `retry`, `sonnet` (writing the rung
    and clearing the slot's stale files) or `uncovered` (marking the entry); a
    `final` call (the merge's cap step) never transitions, only `uncovered`.
    """
    import finder_coverage  # noqa: PLC0415 — lazy: the two modules import each other

    round_dir = Path(round_dir)
    manifest = _read_manifest(round_dir)
    if isinstance(manifest, int):
        return {"outcome": None, "next": None, "covered_files": [], "exit": manifest}
    if angle == finder_round.CHECK_NAME:
        return {"outcome": None, "next": None, "covered_files": [],
                "exit": _fail("refusing to settle the Opus check")}
    entry = _find(manifest, angle)
    if entry is None:
        return {"outcome": None, "next": None, "covered_files": [],
                "exit": _fail(f"unknown angle {angle!r}")}
    seg = entry.get("segment")
    if not seg:
        return {"outcome": None, "next": None, "covered_files": [],
                "exit": _fail(f"angle {angle!r} is not a segment entry")}
    capped = bool(capped) or _stopped(round_dir, entry)
    old = entry.get("telemetry") or {}
    text = _reply_text(entry, round_dir)
    findings, ok = review_merge.parse_codereview_result(text)
    reply_path = entry.get("reply_path") or str(round_dir / angle / agent_caps_watch.REPLY)

    part = None
    if ok and not _placeholder_only(findings):
        outcome, covered, next_step = "delivered", list(seg.get("files") or ()), "none"
    elif text.strip() and not ok and not capped:
        outcome, covered, next_step = "unparseable", [], "none"
    else:
        part = finder_coverage.read_partial(round_dir, entry)
        extra = [f for f in findings if _placeholder_only(findings) and f.get("file")]
        found = list(part.findings) + [f for f in extra
                                       if f not in part.findings]
        if found:
            agent_caps.put_capped(reply_path, "",
                                  partial_lines=[json.dumps(f, sort_keys=True) for f in found])
            outcome = "partial"
        elif part.covered_files:
            _write_reply(reply_path, [])
            outcome = "partial"
        else:
            outcome = "capped"
        covered = list(part.covered_files)
        next_step = _next(entry, manifest, final) if outcome == "capped" else "none"

    strata_s = elapsed_s if elapsed_s is not None else old.get("elapsed_s")
    if next_step == "sonnet":
        _to_sonnet(entry, _slot_dir(round_dir, entry))
    tel = _telemetry(entry, seg, outcome, covered, part, elapsed_s, old)
    if next_step == "sonnet":
        # N2: the Sonnet rung starts with no elapsed time or coverage of its own; the
        # capped Strata run's time goes under its own key, never on the Sonnet row.
        tel.update(elapsed_s=None, covered_files=[])
        if strata_s is not None:
            tel["strata_elapsed_s"] = strata_s
    entry["telemetry"] = tel
    # The parse-lift mark is written at this one point and exists only while the
    # entry's final state is one the Opus check must re-cover: an uncapped reply that
    # failed to parse, or a capped entry with no transition left. Every other
    # outcome/next-step pair clears it, so a re-settle after an earlier `unparseable`
    # settle (the driver's respawn delivered, capped into Sonnet, or capped into a
    # `retry` that `finder_split.retry` only takes unmarked) never keeps a stale mark.
    if outcome == "unparseable" or next_step == "uncovered":
        _mark_uncovered(entry)
    else:
        entry.pop("unparseable", None)
    finder_round._atomic_write(round_dir / MANIFEST, json.dumps(manifest, indent=2) + "\n")
    return {"outcome": outcome, "next": next_step, "covered_files": covered}


def _cmd_settle(args) -> int:
    out = settle(args.round_dir, args.angle, capped=args.capped, elapsed_s=args.elapsed,
                 final=args.final)
    if out.get("exit"):
        return out["exit"]
    print(json.dumps({k: out[k] for k in ("outcome", "next", "covered_files")}))
    return 0


def _args(argv) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="finder_retry.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("settle")
    s.add_argument("--round-dir", dest="round_dir", required=True)
    s.add_argument("--angle", required=True)
    s.add_argument("--capped", action="store_true")
    s.add_argument("--elapsed", type=float)
    s.add_argument("--final", action="store_true")
    r = sub.add_parser("retry")
    r.add_argument("--round-dir", dest="round_dir", required=True)
    r.add_argument("--angle", required=True)
    r.add_argument("--repo", default=".")
    return p.parse_args(argv)


def main(argv=None) -> int:
    a = _args(list(argv if argv is not None else sys.argv[1:]))
    if a.cmd == "settle":
        return _cmd_settle(a)
    if a.cmd == "retry":
        return _cmd_retry(a)
    return _fail(f"unknown command {a.cmd!r}")


if __name__ == "__main__":
    sys.exit(main())
