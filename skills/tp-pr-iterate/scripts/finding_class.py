"""finding_class — the reviewer-tagged finding bar for /tp-pr-iterate.

design: iterate-convergence-budget (Phase 1)

Review bar: "Only a demonstrated shipped-behaviour defect with a reproducer
blocks; mutation survivors, test-tightening, exotic env, lint-guard bypasses,
style and perf are non-blocking notes."

Each review angle tags a finding with a `class` (P/X/T/C), a `blocking` flag and,
when blocking, a `reproducer`. `coerce` turns that untrusted tag set into the
normalized fields: a finding blocks (`verdict="structural"`) only when
`blocking is True` AND the reproducer is valid; everything else is a
non-blocking note (`verdict="minor"`). The legacy shape (no `class` and no
`blocking`) and degraded sentinels return `{}` so the caller keeps its own
fail-closed `structural` default.

Stdlib only; computes, never shells out (C1).
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED = _HERE.parents[1] / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from finding_fields import FRAGILE_CLASSES, normalize as _normalize_fields  # noqa: E402

CLASSES = ("P", "X", "T", "C")

ESCAPE_DISPOSITIONS = ("kept", "downgraded", "opus-added")

_EXPECT_KEYS = ("exit", "stdout_contains")


def is_sentinel(finding: dict) -> bool:
    """A degraded/unavailable review sentinel (mirrors review_merge._is_sentinel)."""
    if finding.get("source") == "no-angles":
        return True
    return str(finding.get("file", "")).startswith("<review-output:")


def _valid_expect(expect) -> bool:
    if not isinstance(expect, dict):
        return False
    present = [k for k in _EXPECT_KEYS if k in expect]
    if not present:
        return False
    if "exit" in expect:
        code = expect["exit"]
        if isinstance(code, bool) or not isinstance(code, int):
            return False
    if "stdout_contains" in expect and not isinstance(expect["stdout_contains"], str):
        return False
    return True


def valid_reproducer(r) -> bool:
    """True iff `r` is a runnable reproducer.

    `{"kind":"test","source":<non-empty str>}` (pytest code) or
    `{"kind":"command","argv":[str,...],"expect":{"exit":int?,"stdout_contains":str?}}`
    with a non-empty argv and at least one `expect` key.
    """
    if not isinstance(r, dict):
        return False
    kind = r.get("kind")
    if kind == "test":
        src = r.get("source")
        return isinstance(src, str) and bool(src.strip())
    if kind == "command":
        argv = r.get("argv")
        if not isinstance(argv, list) or not argv:
            return False
        if not all(isinstance(a, str) for a in argv):
            return False
        return _valid_expect(r.get("expect"))
    return False


def _coerce_class(value) -> str:
    if isinstance(value, str):
        up = value.strip().upper()
        if up in CLASSES:
            return up
    return "C"


def _coerce_escape(raw):
    """The Opus check's `escape` record, or None when it is not a valid one.

    Valid: a dict whose `disposition` is in `ESCAPE_DISPOSITIONS`; `reason` is
    copied only when it is a str.
    """
    if not isinstance(raw, dict):
        return None
    disposition = raw.get("disposition")
    if not isinstance(disposition, str) or disposition not in ESCAPE_DISPOSITIONS:
        return None
    out = {"disposition": disposition}
    if isinstance(raw.get("reason"), str):
        out["reason"] = raw["reason"]
    return out


def coerce(raw) -> dict:
    """Reviewer tags → `{class, blocking, verdict, reproducer?, escape?, schema_note?}`.

    An Opus-downgraded claim (`escape.disposition == "downgraded"`) never
    blocks, whatever its reproducer. Returns `{}` for a non-dict, a sentinel, or the legacy shape (neither
    `class` nor `blocking` present) so the caller's default verdict stands.
    """
    if not isinstance(raw, dict) or is_sentinel(raw):
        return {}
    if "class" not in raw and "blocking" not in raw:
        return {}
    claimed = raw.get("blocking") is True
    repro = raw.get("reproducer")
    has_repro = valid_reproducer(repro)
    escape = _coerce_escape(raw.get("escape"))
    downgraded = escape is not None and escape["disposition"] == "downgraded"
    blocking = claimed and has_repro and not downgraded
    fields = _normalize_fields(raw)
    out = {
        "class": _coerce_class(raw.get("class")),
        "blocking": blocking,
        "verdict": "structural" if blocking else "minor",
        "origin": fields["origin"],
        "fragility_class": fields["fragility_class"],
    }
    if has_repro:
        out["reproducer"] = repro
    if escape is not None:
        out["escape"] = escape
    if claimed and not has_repro:
        out["schema_note"] = "blocking-without-reproducer"
    return out


def tally(findings) -> dict:
    """Per-class counts plus `blocking` (real structural) and `degraded` (sentinels).

    Sentinels count only as `degraded`, never as `blocking` or a class. A finding
    without a `class` tag (legacy shape) adds to no class bucket but still counts
    as `blocking` while its verdict is `structural`. `frag` tallies each
    `FRAGILE_CLASSES` value and `regression` counts findings whose `origin` is
    `regression` (both keyed by the normalized finding fields). `reproduced`
    counts structural findings whose `reproduction` is `reproduced`.
    """
    out = {c: 0 for c in CLASSES}
    out.update(blocking=0, degraded=0, regression=0, reproduced=0)
    out["frag"] = {c: 0 for c in FRAGILE_CLASSES}
    for f in findings or ():
        if is_sentinel(f):
            out["degraded"] += 1
            continue
        if "class" in f:
            out[_coerce_class(f.get("class"))] += 1
        if f.get("verdict") == "structural":
            out["blocking"] += 1
            if f.get("reproduction") == "reproduced":
                out["reproduced"] += 1
        if f.get("fragility_class") in out["frag"]:
            out["frag"][f["fragility_class"]] += 1
        if f.get("origin") == "regression":
            out["regression"] += 1
    return out


def class_line(round_n, head, t: dict) -> str:
    """`[tp-pr-iterate] round N head=<sha7> P<n> X<n> T<n> C<n> blocking=<n>
    frag=open-ended:<n>,change-detector:<n>,blocklist:<n> regression=<n>`."""
    counts = " ".join(f"{c}{t.get(c, 0)}" for c in CLASSES)
    frag = t.get("frag") or {}
    frag_tok = ",".join(f"{c}:{frag.get(c, 0)}" for c in FRAGILE_CLASSES)
    return (f"[tp-pr-iterate] round {round_n} head={str(head or '')[:7]} "
            f"{counts} blocking={t.get('blocking', 0)} "
            f"frag={frag_tok} regression={t.get('regression', 0)}")


def note_line(round_n, finding: dict) -> str:
    """`[tp-pr-iterate/note] round N <class> origin=<o> frag=<c> <file>:<start> —
    <summary ≤160>`."""
    rng = finding.get("line_range")
    start = rng[0] if isinstance(rng, (list, tuple)) and rng else 0
    summary = " ".join(str(finding.get("summary") or "").split())[:160]
    fields = _normalize_fields(finding)
    return (f"[tp-pr-iterate/note] round {round_n} {_coerce_class(finding.get('class'))} "
            f"origin={fields['origin']} frag={fields['fragility_class']} "
            f"{finding.get('file', '')}:{start} — {summary}")
