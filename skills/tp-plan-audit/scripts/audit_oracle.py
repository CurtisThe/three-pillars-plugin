"""audit_oracle.py — the plan audit's mechanical check of every task's **Oracle**
and **Entry point** fields, gated by the ``plan-schema`` marker.

design: fragile-test-prevention (detailed-design-stages Part C2)

The grammar lives in ``skills/_shared/task_oracle.py`` (the one parser the audit
and any runtime reader share): ``parse_oracle`` / ``parse_entry_point`` return
``{kind, types|items, errors}`` and ``validate_pair`` carries the pairing rule.
This module owns the presence rule and the marker gate:

* ``plan_schema(text)`` reads the ``plan-schema`` frontmatter key (through
  ``weight_class.parse_frontmatter``) and gives ``1`` when it is absent or not
  an integer — the schema the plan declares;
* ``check_oracle(tasks, mode, *, schema)``: in ``standard`` and ``light`` modes
  with ``schema >= 2`` a missing or malformed Oracle or Entry point is an
  ``ERROR`` (the message from ``task_oracle``), and so is a ``validate_pair``
  break; without the marker the same gaps are ``NOTE``s; spike mode is exempt;
* ``check_fields(tasks, mode, root, schema)`` is the one call ``audit_plan.py``
  makes: the Targets, Oracle/Entry point and pin results together, as
  ``(issues, notes)``. Without the marker the Oracle, Entry point and pin
  findings are all NOTEs, typed ``LEGACY_NOTE`` so ``audit_plan`` prints them on
  stderr and a legacy plan's stdout report is unchanged; spike mode returns
  nothing (Targets included, as before);
* ``criteria_pins(task, root)`` reads the inline code spans (a CommonMark
  backtick-run scan) and double-quoted spans of the ``Done when`` and ``Test``
  fields only: a line or hash pin is an ``ERROR``, a decidable wording pin is a
  ``_WORDING_LEVEL`` finding (one line to promote it).

``check_targets(..., require=...)`` in ``audit_targets.py`` carries the matching
Targets rule: a missing Targets field is an ``ERROR`` when ``require`` is set
(True only for marked standard and light plans) and a NOTE otherwise. Stdlib only.
"""
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent.parent.parent / "_shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from weight_class import parse_frontmatter  # noqa: E402 — stdlib-only sibling
from task_oracle import (  # noqa: E402
    parse_entry_point, parse_oracle, validate_pair)
from audit_targets import check_targets  # noqa: E402 — sibling: the Targets rule

LEGACY_NOTE = "LEGACY-NOTE"  # a NOTE about a schema the plan has not opted into

_SCHEMA_MARKER = 2
_WORDING_LEVEL = "WARN"  # promote to "ERROR" once the completed-plan count is reviewed
_CRITERIA = ("Done when", "Test")
_LINE_PIN = re.compile(r"[^\s:]+:\d+(?:-\d+)?|L\d+")
_HEX_PIN = re.compile(r"[0-9a-fA-F]{32,}")


def plan_schema(text: str) -> int:
    """The schema a plan declares: the integer ``plan-schema`` frontmatter key,
    or ``1`` when the key is absent or not an integer."""
    value = parse_frontmatter(text).get("plan-schema")
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 1
    return n if n > 0 else 1


def check_oracle(tasks, mode, *, schema: int = 1) -> tuple[list, list]:
    """``tasks`` (from ``extract_tasks``) → ``(issues, notes)``, each
    ``(type, ctx, msg)``. ``mode`` is ``"standard" | "light" | "spike"``.

    Marked (``schema >= 2``) standard and light plans get ERRORs; unmarked
    plans get NOTEs; spike mode returns nothing.
    """
    strict = mode in ("standard", "light") and schema >= _SCHEMA_MARKER
    kind = "ERROR" if strict else "NOTE"
    issues: list[tuple] = []
    notes: list[tuple] = []
    out = issues if strict else notes
    if mode == "spike":
        return [], []
    for t in tasks:
        ctx = f"Task {t['id']}: {t['name']}"
        fields = t["fields"]
        oracle = parse_oracle(fields.get("Oracle"))
        entry = parse_entry_point(fields.get("Entry point"))
        pair = validate_pair(oracle, fields.get("Targets"), entry)
        msgs: list[str] = []
        if oracle["kind"] == "missing":
            msgs.append("no **Oracle** field: non-canonical (not auditable "
                        "for oracle style; add it or write `none`)")
        elif oracle["kind"] == "malformed":
            msgs.append("malformed **Oracle**: " + "; ".join(oracle["errors"]))
        if entry["kind"] == "missing":
            msgs.append("no **Entry point** field: non-canonical (not auditable "
                        "for entry point; add it or write `none`)")
        elif entry["kind"] == "malformed":
            msgs.append("malformed **Entry point**: " + "; ".join(entry["errors"]))
        msgs.extend(pair)
        for m in msgs:
            out.append((kind, ctx, m))
    return issues, notes


def _spans(text: str) -> tuple[list[str], list[str]]:
    """``text`` → ``(code_spans, quoted_spans)``. Code spans follow CommonMark:
    a backtick run opens, the next run of the same length closes, one space is
    stripped from each end when both are present; an unclosed run is literal.
    Double-quoted spans are read from the text outside code spans."""
    code: list[str] = []
    outside: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "`":
            outside.append(text[i])
            i += 1
            continue
        j = i
        while j < n and text[j] == "`":
            j += 1
        run = j - i
        k, close = j, -1
        while k < n:
            if text[k] != "`":
                k += 1
                continue
            m = k
            while m < n and text[m] == "`":
                m += 1
            if m - k == run:
                close = k
                break
            k = m
        if close < 0:
            outside.append(text[i:j])
            i = j
            continue
        body = text[j:close].replace("\n", " ")
        if len(body) > 1 and body[0] == " " and body[-1] == " " and body.strip():
            body = body[1:-1]
        code.append(body)
        outside.append(" ")
        i = close + run
    pieces = "".join(outside).split('"')
    # odd pieces sit between a pair of quotes; an unpaired trailing quote is literal
    return code, pieces[1:len(pieces) - 1:2]


def _named_md(text: str, code: list[str]) -> list[str]:
    """The ``.md`` paths a field names (bare words or code spans)."""
    words = text.replace("`", " ").split() + code
    out = []
    for w in words:
        w = w.strip("()[]<>,;:'\"").rstrip(".")
        if w.endswith(".md") and w not in out:
            out.append(w)
    return out


def _md_text(root: Path, rel: str) -> str:
    """The named ``.md`` under ``root``, or ``""`` (missing, unreadable, outside)."""
    base = Path(root).resolve()
    path = (base / rel).resolve()
    try:
        path.relative_to(base)
        return path.read_text(encoding="utf-8")
    except (ValueError, OSError, UnicodeDecodeError):
        return ""


def _greps_md(span: str) -> bool:
    """A code span whose ``shlex`` argv is ``grep``/``rg`` over a ``.md``."""
    try:
        argv = shlex.split(span)
    except ValueError:
        return False
    return (len(argv) > 1 and argv[0] in ("grep", "rg")
            and any(a.endswith(".md") for a in argv[1:]))


def _pin_kind(span: str) -> str | None:
    if _LINE_PIN.fullmatch(span):
        return "line"
    if _HEX_PIN.fullmatch(span) or span.startswith("sha256:"):
        return "hash"
    return None


def criteria_pins(task: dict, root) -> list[tuple]:
    """``task`` (from ``extract_tasks``) → ``[(type, ctx, msg)]`` for the pins
    in its ``Done when`` and ``Test`` fields; ``root`` is the plan's repo root,
    where a named ``.md`` is read for the wording test. Red and Green are never
    scanned."""
    ctx = f"Task {task['id']}: {task['name']}"
    found: list[tuple] = []
    for name in _CRITERIA:
        text = task["fields"].get(name) or ""
        code, quoted = _spans(text)
        mds = _named_md(text, code)
        docs = [_md_text(root, m) for m in mds]
        for span, is_code in [(c, True) for c in code] + [(q, False) for q in quoted]:
            span = span.strip()
            if not span:
                continue
            kind = _pin_kind(span)
            if kind:
                found.append(("ERROR", ctx, f"criteria pin a {kind}: {span}"))
            elif (is_code and _greps_md(span)) or (
                    span not in mds and any(span in d for d in docs)):
                found.append((_WORDING_LEVEL, ctx, f"criteria pin wording: {span}"))
    return found


def check_fields(tasks, mode, root, schema) -> tuple[list, list]:
    """``tasks`` → ``(issues, notes)``, each ``(type, ctx, msg)``: the Targets,
    Oracle / Entry point and criteria-pin results together. ``root`` is the
    plan's repo root; ``schema`` comes from ``plan_schema``.

    Marked (``schema >= 2``) standard and light plans: missing or malformed
    fields and line or hash pins are ERRORs, a wording pin a WARN. Unmarked
    plans: the Oracle, Entry point and pin findings are ``LEGACY_NOTE``s, never
    failing; a missing Targets is the usual NOTE. Spike mode: nothing.
    """
    if mode == "spike":
        return [], []
    marked = schema >= _SCHEMA_MARKER
    issues, notes = check_targets(tasks, root, require=marked)
    more_issues, more_notes = check_oracle(tasks, mode, schema=schema)
    pins = [p for t in tasks for p in criteria_pins(t, root)]
    if marked:
        return issues + more_issues + pins, notes
    legacy = [(LEGACY_NOTE, ctx, msg) for _, ctx, msg in more_notes + pins]
    return issues, notes + legacy
