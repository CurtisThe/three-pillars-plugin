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

CLASSES = ("P", "X", "T", "C")

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


def coerce(raw) -> dict:
    """Reviewer tags → `{class, blocking, verdict, reproducer?, schema_note?}`.

    Returns `{}` for a non-dict, a sentinel, or the legacy shape (neither
    `class` nor `blocking` present) so the caller's default verdict stands.
    """
    if not isinstance(raw, dict) or is_sentinel(raw):
        return {}
    if "class" not in raw and "blocking" not in raw:
        return {}
    claimed = raw.get("blocking") is True
    repro = raw.get("reproducer")
    has_repro = valid_reproducer(repro)
    blocking = claimed and has_repro
    out = {
        "class": _coerce_class(raw.get("class")),
        "blocking": blocking,
        "verdict": "structural" if blocking else "minor",
    }
    if has_repro:
        out["reproducer"] = repro
    if claimed and not has_repro:
        out["schema_note"] = "blocking-without-reproducer"
    return out


def tally(findings) -> dict:
    """Per-class counts plus `blocking` (real structural) and `degraded` (sentinels).

    Sentinels count only as `degraded`, never as `blocking` or a class. A finding
    without a `class` tag (legacy shape) adds to no class bucket but still counts
    as `blocking` while its verdict is `structural`.
    """
    out = {c: 0 for c in CLASSES}
    out.update(blocking=0, degraded=0)
    for f in findings or ():
        if is_sentinel(f):
            out["degraded"] += 1
            continue
        if "class" in f:
            out[_coerce_class(f.get("class"))] += 1
        if f.get("verdict") == "structural":
            out["blocking"] += 1
    return out


def class_line(round_n, head, t: dict) -> str:
    """`[tp-pr-iterate] round N head=<sha7> P<n> X<n> T<n> C<n> blocking=<n>`."""
    counts = " ".join(f"{c}{t.get(c, 0)}" for c in CLASSES)
    return (f"[tp-pr-iterate] round {round_n} head={str(head or '')[:7]} "
            f"{counts} blocking={t.get('blocking', 0)}")


def note_line(round_n, finding: dict) -> str:
    """`[tp-pr-iterate/note] round N <class> <file>:<start> — <summary ≤160>`."""
    rng = finding.get("line_range")
    start = rng[0] if isinstance(rng, (list, tuple)) and rng else 0
    summary = " ".join(str(finding.get("summary") or "").split())[:160]
    return (f"[tp-pr-iterate/note] round {round_n} {_coerce_class(finding.get('class'))} "
            f"{finding.get('file', '')}:{start} — {summary}")
