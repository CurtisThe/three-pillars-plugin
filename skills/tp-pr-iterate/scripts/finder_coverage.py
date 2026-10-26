"""finder_coverage — a segmented round's outcomes, coverage figure and merge.

design: finder-cap-coverage (Tasks 1.5-1.8)

`merge_round` (the `finder_segments.py merge` body) runs the cap step for every
segment entry the driver left unsettled, then writes `segments-merged.json`: the
merged findings, `uncovered_files`, the `coverage` figure and per-segment
telemetry. The harvest lives in `finder_harvest`, the prompt and digest text in
`finder_digest`, first-attempt sizing in `finder_sizing`; this module re-exports
their public names so every caller keeps one import path.
"""
from __future__ import annotations

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

from finder_digest import (COVERAGE_OK, UNCCLOSE, UNCOPEN, check_scope,  # noqa: E402,F401
                           coverage_line, label_suffix, partial_note)
from finder_harvest import (SIDECAR, TRANSCRIPT, Partial, _finding_key,  # noqa: E402,F401
                            _json_obj, read_partial)
from finder_sizing import lines_per_cap, plan_for_round  # noqa: E402,F401

# `finder_round`, `finder_retry` and `finder_segments` are imported only inside the
# functions below: `angles` imports this module at module level and `finder_retry`
# imports `finder_round`, so a module-level import here closes the cycle.
RETRIED = "retried"


def segment_entries(manifest) -> list:
    """Every entry carrying a `segment` block."""
    return [e for e in manifest.get("angles") or () if e.get("segment")]


def _placeholder_only(findings) -> bool:
    """A NON-EMPTY findings list whose every item is `capped: true` (what `put-capped` writes)."""
    return bool(findings) and all(isinstance(f, dict) and f.get(agent_caps.CAP_FIELD)
                                 for f in findings)


def entry_outcome(entry, reply_text=None) -> str:
    """The entry's segment outcome: its recorded telemetry, else derived from its state.

    An entry with no telemetry (written before this change, or never settled) counts
    `delivered` only when its reply parses and is not placeholder-only — never by
    default; a missing or unparseable reply reads `unparseable` (Task 1.6)."""
    tel = entry.get("telemetry") or {}
    if tel.get("outcome"):
        return tel["outcome"]
    if entry.get("skipped") == RETRIED:
        return RETRIED
    if entry.get("skipped"):
        return "skipped"
    if entry.get("unparseable"):
        return "unparseable"
    if reply_text is None:
        return "unparseable"
    from review_merge import parse_codereview_result  # noqa: PLC0415 — lazy, CLI only
    findings, ok = parse_codereview_result(reply_text)
    return "delivered" if ok and not _placeholder_only(findings) else "unparseable"


def _covers(entry, outcome, path) -> bool:
    """The entry saw `path`: a delivered segment saw its whole segment, a partial only
    the files its progress lines named."""
    if outcome == "delivered":
        return path in ((entry.get("segment") or {}).get("files") or ())
    if outcome == "partial":
        return path in ((entry.get("telemetry") or {}).get("covered_files") or ())
    return False


def uncovered(manifest, outcomes) -> list[str]:
    """The plan's coverage rule, for-all: a changed file is covered when, for every
    segmented angle and EVERY segment of that angle carrying it, that segment is
    `delivered` or is `partial` and named the file. A `skipped: "retried"` parent is
    replaced by its halves and counts neither way."""
    segs = segment_entries(manifest)
    changed = {p for e in segs for p in e["segment"].get("files") or ()}
    live = [e for e in segs if e.get("skipped") != RETRIED]
    out = set()
    for path in changed:
        for e in live:
            if (path in (e["segment"].get("files") or ())
                    and not _covers(e, outcomes.get(e["name"]), path)):
                out.add(path)
                break
    return sorted(out)


def coverage(manifest, outcomes) -> dict:
    """`{fraction, percent, files_changed, files_covered}` — `percent` is the integer
    `files_covered * 100 // files_changed`, never a float floor (29/100 prints 29)."""
    files_changed = {p for e in segment_entries(manifest)
                     for p in e["segment"].get("files") or ()}
    unc = uncovered(manifest, outcomes)
    covered = len(files_changed) - len(unc)
    return {"fraction": round(covered / len(files_changed), 4) if files_changed else 0.0,
            "percent": covered * 100 // len(files_changed) if files_changed else 0,
            "files_changed": len(files_changed), "files_covered": covered}


def _telemetry_row(e, outcome) -> dict:
    """The merge's telemetry row for one segment entry; unset fields read `null`."""
    seg, tel = e["segment"], e.get("telemetry") or {}
    return {"id": seg.get("id"), "angle": seg.get("angle"),
            "rung": e.get("rung") or tel.get("rung"),
            "attempt": e.get("attempt") or tel.get("attempt"),
            "lines": seg.get("lines"), "files": len(seg.get("files") or ()),
            "elapsed_s": tel.get("elapsed_s"), "outcome": outcome,
            "sources": tel.get("sources") or [],
            "transcript_found": bool(tel.get("transcript_found"))}


def _needs_cap_step(entry, text) -> bool:
    """True for a segment entry the merge must settle itself (Behaviors 7, 8): with no
    recorded outcome, a missing, empty, placeholder-only or unparseable reply; or an
    outcome `capped` with no parse-lift mark — a `retry`/`sonnet` answer (or a Sonnet
    re-run that then delivered) nobody acted on, whatever its reply. A final outcome
    (delivered, partial, unparseable, or capped WITH the mark) is never touched."""
    tel = (entry.get("telemetry") or {}).get("outcome")
    if tel == "capped":
        return entry.get("unparseable") != _uncovered_mark()
    if tel:
        return False
    if text.strip() == "":
        return True
    from review_merge import parse_codereview_result  # noqa: PLC0415 — lazy, CLI only
    findings, ok = parse_codereview_result(text)
    return not ok or _placeholder_only(findings)


def _unsettled_prose(entry, text) -> bool:
    """A never-settled, non-empty reply that does not parse: an uncapped finder's
    `unparseable` reply (Behavior 7), settled uncapped so it is marked, never retried."""
    if (entry.get("telemetry") or {}).get("outcome") or not text.strip():
        return False
    from review_merge import parse_codereview_result  # noqa: PLC0415 — lazy, CLI only
    return not parse_codereview_result(text)[1]


def _uncovered_mark() -> str:
    import finder_retry  # noqa: PLC0415 — lazy: the two modules import each other
    return finder_retry.UNCOVERED_MARK


def _run_cap_step(rd, manifest) -> dict:
    """Settle every entry the driver left unsettled (Task 1.7), then re-read the manifest."""
    import finder_retry  # noqa: PLC0415 — lazy: the two modules import each other
    texts = {}
    for e in segment_entries(manifest):
        if e.get("skipped") or not _needs_cap_step(e, texts.setdefault(
                e["name"], _reply_text(rd, e))):
            continue
        # A re-settled entry keeps the elapsed time the driver recorded for it.
        finder_retry.settle(rd, e["name"], capped=not _unsettled_prose(e, texts[e["name"]]),
                            final=True, elapsed_s=(e.get("telemetry") or {}).get("elapsed_s"))
    try:
        return json.loads((rd / "angles.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return manifest


def _reply_text(rd, entry) -> str:
    path = entry.get("reply_path") or str(Path(rd) / entry["name"] / agent_caps_watch.REPLY)
    path = Path(path) if Path(path).is_absolute() else Path(rd) / path
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def merge_round(round_dir) -> int:
    """Write `R/opus-check/segments-merged.json`: the merged findings, the uncovered
    files, the round coverage figure, per-segment telemetry, the budget skips and the
    retry budget. A round with no segment entries writes nothing (Behavior 6).
    Before computing anything the merge runs the cap step itself (Behavior 8), so an
    outcome never depends on the driver having run `put-capped` or `settle`."""
    import finder_retry  # noqa: PLC0415 — lazy: the two modules import each other
    import finder_segments  # noqa: PLC0415
    from review_merge import parse_codereview_result  # noqa: PLC0415 — lazy, CLI only

    rd = Path(round_dir)
    try:
        manifest = json.loads((rd / "angles.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"finder_coverage: cannot read manifest: {exc}", file=sys.stderr)
        return 2
    segs = segment_entries(manifest)
    if not segs:
        return 0
    manifest = _run_cap_step(rd, manifest)
    segs = segment_entries(manifest)
    texts, replies = {}, {}
    for e in segs:
        if e.get("skipped"):
            continue
        try:
            texts[e["name"]] = (rd / e["name"] / agent_caps_watch.REPLY).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            texts[e["name"]] = ""
    outcomes = {e["name"]: entry_outcome(e, texts.get(e["name"])) for e in segs}
    for e in segs:
        # A delivered or partial segment's reply is unioned with its partial findings,
        # so a finder that sent partials and delivered a reply holding fewer loses none.
        if e.get("skipped") or outcomes[e["name"]] not in ("delivered", "partial"):
            continue
        findings = parse_codereview_result(texts.get(e["name"], ""))[0]
        base = findings if isinstance(findings, list) else []
        for obj in read_partial(rd, e).findings:
            if all(_finding_key(obj) != _finding_key(f) for f in base):
                base.append(obj)
        replies[e["name"]] = base
    # The check's prompt names every uncovered path (Behavior 4), at any coverage.
    import finder_round  # noqa: PLC0415 — lazy: the two modules import each other
    unc = uncovered(manifest, outcomes)
    scoped = check_scope(manifest, unc)
    finder_round._atomic_write(rd / "angles.json", json.dumps(scoped, indent=2) + "\n")
    angles = {e["segment"].get("angle") for e in segs}
    out = {"merged": finder_segments.merge_segment_replies(manifest, replies),
           "uncovered_files": unc,
           "coverage": coverage(manifest, outcomes),
           "segments": [_telemetry_row(e, outcomes[e["name"]]) for e in segs],
           "budget_skips": [{"id": e["segment"].get("id"), "angle": e["segment"].get("angle"),
                             "files": len(e["segment"].get("files") or ())}
                            for e in segs if e.get("skipped") == finder_segments.SKIP_BUDGET],
           "retry_budget": {"per_angle": max((finder_retry.budget(manifest, a) for a in angles),
                                             default=finder_segments.DEFAULTS["max_segments"]),
                            "used": {a: finder_retry.retry_used(manifest, a) for a in angles}}}
    dest = rd / "opus-check"
    dest.mkdir(exist_ok=True)
    (dest / finder_segments.MERGED).write_text(json.dumps(out, indent=2) + "\n",
                                               encoding="utf-8")
    print(json.dumps({"wrote": str(dest / finder_segments.MERGED),
                      "uncovered": len(out["uncovered_files"])}))
    return 0


def cmd_merge(args) -> int:
    """The `finder_segments.py merge` command body (the CLI stays where it is)."""
    return merge_round(args.round_dir)
