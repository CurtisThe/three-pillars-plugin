"""explainer/explain_envelope.py — the explain envelope schema and its check.

Public API:
    SCHEMA                              "explain-envelope/v1"
    KINDS                               the three explain kinds
    REQUIRED_SECTIONS                   kind -> tuple of required section ids
    validate_envelope(env, kind) -> list[str]

The envelope is the drafter's only output:

    {schema: "explain-envelope/v1", kind,
     ste_summary: {text, refs},
     sections: [{id, title, items: [{text, refs}]}],
     diagram_specs: [dict],
     confidence_note: {text, refs}}

Extra keys (an item's "recommended", a finalized envelope's "facts_only" or
"style_note") are allowed. validate_envelope returns failure codes, each code
once, in the order found; [] means valid:

    bad-shape:<path>      a field is missing or has the wrong type; <path>
                          is "ste_summary.text", "sections[<i>].items[<j>].refs"
    bad-schema            schema is a string but not SCHEMA
    kind-mismatch         env kind differs from the kind argument
    missing-section:<id>  a REQUIRED_SECTIONS id for the kind is absent
    no-recommended        human-escalation: the "options" section has no item
                          with "recommended": true
    raw-diagram           a diagram_specs entry is a string or carries an
                          svg / mermaid / html key, or a text field holds a
                          ``` fence or "<svg"

Refs are checked for shape only here; evidence_refs.check_refs checks them
against the request. An unknown kind argument raises ValueError.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_spec  # noqa: E402

SCHEMA = "explain-envelope/v1"

KINDS = ("auto-ruling", "human-escalation", "pr-brief")

REQUIRED_SECTIONS = {
    "pr-brief": ("what-merging", "whole-system", "defaults-switches",
                 "risks-residuals", "review-outcome", "rulings-without-you"),
    "auto-ruling": ("decided", "why", "commits-to"),
    "human-escalation": ("question", "options", "pillar-analysis",
                         "recommendation"),
}

# One registry for "raw markup, never a spec": the diagram sanitizer's own.
_RAW_DIAGRAM_KEYS = explain_spec._RAW_DIAGRAM_KEYS
_RAW_TEXT_RE = re.compile(r"```|<svg", re.IGNORECASE)


class _Codes:
    """Ordered, de-duplicated failure codes."""

    def __init__(self):
        self.codes: list = []

    def add(self, code: str) -> None:
        if code not in self.codes:
            self.codes.append(code)


def _check_text(value, path: str, out: _Codes) -> None:
    if not isinstance(value, str):
        out.add(f"bad-shape:{path}")
    elif _RAW_TEXT_RE.search(value):
        out.add("raw-diagram")


def _check_refs(value, path: str, out: _Codes) -> None:
    if not isinstance(value, list) or not all(isinstance(r, str) for r in value):
        out.add(f"bad-shape:{path}")


def _check_cited(value, path: str, out: _Codes) -> None:
    """A {text, refs} block: ste_summary, confidence_note or a section item."""
    if not isinstance(value, dict):
        out.add(f"bad-shape:{path}")
        return
    _check_text(value.get("text"), f"{path}.text", out)
    _check_refs(value.get("refs"), f"{path}.refs", out)


def _check_sections(sections, out: _Codes) -> list:
    """Check each section's shape; return the sections that have a string id."""
    if not isinstance(sections, list):
        out.add("bad-shape:sections")
        return []
    good = []
    for i, sec in enumerate(sections):
        path = f"sections[{i}]"
        if not isinstance(sec, dict):
            out.add(f"bad-shape:{path}")
            continue
        if isinstance(sec.get("id"), str):
            good.append(sec)
        else:
            out.add(f"bad-shape:{path}.id")
        _check_text(sec.get("title"), f"{path}.title", out)
        items = sec.get("items")
        if not isinstance(items, list):
            out.add(f"bad-shape:{path}.items")
            continue
        for j, item in enumerate(items):
            _check_cited(item, f"{path}.items[{j}]", out)
    return good


def _check_diagrams(specs, out: _Codes) -> None:
    if not isinstance(specs, list):
        out.add("bad-shape:diagram_specs")
        return
    for i, spec in enumerate(specs):
        if isinstance(spec, str):
            out.add("raw-diagram")
        elif not isinstance(spec, dict):
            out.add(f"bad-shape:diagram_specs[{i}]")
        elif any(k in spec for k in _RAW_DIAGRAM_KEYS):
            out.add("raw-diagram")


def _lacks_recommended(section: dict) -> bool:
    """True when a well-formed items list has no "recommended": true item."""
    items = section.get("items")
    return isinstance(items, list) and not any(
        isinstance(item, dict) and item.get("recommended") is True
        for item in items)


def validate_envelope(env, kind) -> list:
    """Return the failure codes for ``env`` as a ``kind`` envelope ([] = valid)."""
    if kind not in KINDS:
        raise ValueError(f"unknown explain kind {kind!r}; expected one of {KINDS}")
    out = _Codes()
    if not isinstance(env, dict):
        out.add("bad-shape:envelope")
        return out.codes

    schema = env.get("schema")
    if not isinstance(schema, str):
        out.add("bad-shape:schema")
    elif schema != SCHEMA:
        out.add("bad-schema")

    env_kind = env.get("kind")
    if not isinstance(env_kind, str):
        out.add("bad-shape:kind")
    elif env_kind != kind:
        out.add("kind-mismatch")

    _check_cited(env.get("ste_summary"), "ste_summary", out)
    sections = _check_sections(env.get("sections"), out)
    _check_diagrams(env.get("diagram_specs"), out)
    _check_cited(env.get("confidence_note"), "confidence_note", out)

    if isinstance(env.get("sections"), list):
        by_id = {}
        for sec in sections:
            by_id.setdefault(sec["id"], sec)
        for sid in REQUIRED_SECTIONS[kind]:
            if sid not in by_id:
                out.add(f"missing-section:{sid}")
        options = by_id.get("options")
        if (kind == "human-escalation" and options is not None
                and _lacks_recommended(options)):
            out.add("no-recommended")
    return out.codes
