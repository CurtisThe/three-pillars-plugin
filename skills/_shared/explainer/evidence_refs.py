"""explainer/evidence_refs.py — check envelope refs against the request evidence.

Public API:
    supported(item, ids) -> bool
    check_refs(env, request) -> {"unknown": [ref, ...], "unsupported": [path, ...]}

An item is supported when it has at least one ref and every ref is an
evidence id in the request (``request["evidence"][*]["ref"]``). The check is
syntactic: a ref proves provenance, not truth. The Opus check is the
semantic catch.

check_refs walks every sentence-bearing field of the envelope, in envelope
order: ``ste_summary``, ``sections[<i>].items[<j>]``, ``confidence_note``.
"unknown" lists each unknown ref once, in the order found; "unsupported"
names each failing field by that path. A malformed field (wrong type, refs
missing) counts as unsupported; shape codes are explain_envelope's job.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _refs(item) -> list:
    """The item's refs, or [] when the item or its refs are malformed."""
    if not isinstance(item, dict):
        return []
    refs = item.get("refs")
    if not isinstance(refs, list):
        return []
    return refs


def supported(item, ids) -> bool:
    """True when ``item`` has at least one ref and every ref is in ``ids``."""
    refs = _refs(item)
    return bool(refs) and all(isinstance(r, str) and r in ids for r in refs)


def _evidence_ids(request) -> set:
    evidence = request.get("evidence") if isinstance(request, dict) else None
    if not isinstance(evidence, list):
        return set()
    return {e["ref"] for e in evidence
            if isinstance(e, dict) and isinstance(e.get("ref"), str)}


def _cited_fields(env) -> list:
    """(path, item) for every sentence-bearing field, in envelope order."""
    fields = [("ste_summary", env.get("ste_summary"))]
    sections = env.get("sections")
    if isinstance(sections, list):
        for i, sec in enumerate(sections):
            items = sec.get("items") if isinstance(sec, dict) else None
            if not isinstance(items, list):
                continue
            for j, item in enumerate(items):
                fields.append((f"sections[{i}].items[{j}]", item))
    fields.append(("confidence_note", env.get("confidence_note")))
    return fields


def check_refs(env, request) -> dict:
    """Return the unknown refs and the unsupported field paths of ``env``."""
    ids = _evidence_ids(request)
    unknown: list = []
    unsupported: list = []
    # Fail closed: a non-dict envelope has an unsupported summary and note.
    for path, item in _cited_fields(env if isinstance(env, dict) else {}):
        for ref in _refs(item):
            if isinstance(ref, str) and ref not in ids and ref not in unknown:
                unknown.append(ref)
        if not supported(item, ids):
            unsupported.append(path)
    return {"unknown": unknown, "unsupported": unsupported}
