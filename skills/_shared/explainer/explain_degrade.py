"""explainer/explain_degrade.py — the deterministic degrade after the one rewrite.

Public API:
    FACTS_ONLY                         "facts_only", the facts-only label key
    STYLE_NOTE                         "style_note", the lint-miss note key
    DIAGRAM_NOTES                      "diagram_notes", the omitted-diagram notes key
    DIAGRAM_NOTE_PREFIX                "diagram omitted: ", the start of each note
    MAX_FACT_ITEMS                     3, the most items a facts-only section has
    EDITED_MIN_RATIO                   0.6, the least prose ratio that is "edited"
    finalize(env, request, gate) -> dict
    merge_notes(prior, own) -> list    the notes a --checked finalize ships
    facts_only(request) -> dict
    prose(env) -> str
    check_outcome(draft, checked) -> "accepted" | "edited" | "rewritten"

finalize takes a drafted envelope that has used its one rewrite, plus the
explain_gate.run_gates result for it, and returns the envelope to render.
It never mutates its input, and the same input always gives the same output.

    1. An envelope that is not well-formed for request["kind"]
       (explain_envelope.validate_envelope codes other than raw-diagram:
       bad-shape, bad-schema, kind-mismatch, missing-section, no-recommended)
       gives facts_only(request).
    2. A section item that evidence_refs.supported rejects (no ref, or an
       unknown ref) is dropped; a section left with no items is dropped.
    3. A diagram_specs entry is kept only when gate["diagrams_ok"] holds True
       at its index. Each dropped entry adds one note to DIAGRAM_NOTES:
       "diagram omitted: <sentence>", where the sentence is
       explain_diagram_check.reason_text of gate["diagram_reasons"][<index>],
       or of "bad-shape" when that reason is missing. The list is [] when no
       diagram was dropped; a drafted DIAGRAM_NOTES is replaced, never kept.
       facts_only(request) has no DIAGRAM_NOTES key. A second finalize of the
       checked envelope loses the first one's notes; the CLI restores them
       with merge_notes (explain_cli_cmds.cmd_finalize).
    4. The result must then pass validate_envelope and check_refs with no
       unsupported field: an unsupported ste_summary or confidence_note, a
       required section emptied by step 2, a raw text field, or an options
       section that lost its recommended item gives facts_only(request).
    5. ste_lint.lint runs on the result. When "passed" is False (never on
       "any issue"), STYLE_NOTE is a string naming the failed rules; the prose
       is kept.

The drafter does not own FACTS_ONLY or STYLE_NOTE: finalize removes a
drafted STYLE_NOTE and sets FACTS_ONLY to False on every non-fallback result.

facts_only(request) builds a valid envelope from the request evidence alone,
labelled FACTS_ONLY True. Each required section gets up to MAX_FACT_ITEMS
items "`<label>`: see `<ref>`", each citing that one evidence item: the
evidence whose ref fits the section (_SECTION_REFS, in that prefix order),
else the first evidence item. The label and the ref text sit in code spans,
so the items pass ste_lint whatever the label says; backticks, "<", ">" and
line breaks are removed from that text. The summary and the note cite the
first evidence item. A human-escalation "options" section marks its first
item "recommended". A request with no evidence gives empty sections and
uncited summary and note. An unknown request["kind"] raises ValueError.

check_outcome measures the Opus check from the prose diff, never from the
check's own claim. prose(env) is every text field (the summary, each
section item, the note; as ste_lint reads them) joined by newlines in
envelope order; refs, titles and other keys are not prose. The
difflib.SequenceMatcher ratio of the draft prose against the checked prose
is 1.0 for "accepted", at least EDITED_MIN_RATIO for "edited", and anything
lower is "rewritten". autojunk is off: on prose of 200 chars or more it
treats common letters as junk and scores a light edit as a rewrite.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import copy
import difflib
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import evidence_refs  # noqa: E402
import explain_diagram_check  # noqa: E402
import explain_envelope  # noqa: E402
import ste_lint  # noqa: E402

FACTS_ONLY = "facts_only"
STYLE_NOTE = "style_note"
DIAGRAM_NOTES = "diagram_notes"
DIAGRAM_NOTE_PREFIX = "diagram omitted: "
_FALLBACK_REASON = "bad-shape"
MAX_FACT_ITEMS = 3
EDITED_MIN_RATIO = 0.6

# Section id -> the ref prefixes whose evidence fits it, most fitting first.
_SECTION_REFS = {
    "what-merging": ("design:problem", "design:scope", "diffstat"),
    "whole-system": ("design:loci", "design:dependencies", "tree:"),
    "defaults-switches": ("config:diff", "design:consumer-repo",
                          "design:forge"),
    "risks-residuals": ("audit:verdict",),
    "review-outcome": ("review:digest",),
    "rulings-without-you": ("ruling:",),
    "decided": ("subject:", "decision:"),
    "why": ("design:problem", "decision:"),
    "commits-to": ("diffstat", "design:scope", "tree:"),
    "question": ("subject:question", "subject:"),
    "options": ("subject:options", "subject:"),
    "pillar-analysis": ("design:",),
    "recommendation": ("subject:recommendation", "subject:"),
}

_SUMMARY = ("Facts only: the draft did not pass the checks, so each item "
            "points to the evidence.")
_NOTE = ("Read the cited evidence for the detail. This brief holds no "
         "drafted text.")
_UNSAFE_RE = re.compile(r"[`<>]")


def _kind(request) -> str:
    kind = request.get("kind") if isinstance(request, dict) else None
    if kind not in explain_envelope.KINDS:
        raise ValueError(f"unknown explain kind {kind!r}; "
                         f"expected one of {explain_envelope.KINDS}")
    return kind


def _evidence(request) -> list:
    """(ref, label) per well-formed evidence item, each ref once, in order."""
    out, seen = [], set()
    for e in request.get("evidence") or []:
        ref = e.get("ref") if isinstance(e, dict) else None
        if not isinstance(ref, str) or not ref or ref in seen:
            continue
        seen.add(ref)
        label = e.get("label")
        out.append((ref, label if isinstance(label, str) else ""))
    return out


def _code_text(text: str) -> str:
    """``text`` made safe to sit inside one code span."""
    return " ".join(_UNSAFE_RE.sub("", text).split())


def _fact(ref: str, label: str) -> dict:
    ref_text = _code_text(ref) or "evidence"
    label_text = _code_text(label) or ref_text
    return {"text": f"`{label_text}`: see `{ref_text}`", "refs": [ref]}


def _section_evidence(sid: str, evidence: list) -> list:
    picked = []
    for prefix in _SECTION_REFS.get(sid, ()):
        for pair in evidence:
            if pair[0].startswith(prefix) and pair not in picked:
                picked.append(pair)
    return picked[:MAX_FACT_ITEMS] or evidence[:1]


def _title(sid: str) -> str:
    return sid.replace("-", " ").capitalize()


def facts_only(request) -> dict:
    """A labelled envelope built only from ``request``'s evidence."""
    kind = _kind(request)
    evidence = _evidence(request)
    first = [evidence[0][0]] if evidence else []
    sections = []
    for sid in explain_envelope.REQUIRED_SECTIONS[kind]:
        items = [_fact(ref, label)
                 for ref, label in _section_evidence(sid, evidence)]
        if sid == "options" and items:
            items[0]["recommended"] = True
        sections.append({"id": sid, "title": _title(sid), "items": items})
    return {
        "schema": explain_envelope.SCHEMA,
        "kind": kind,
        "ste_summary": {"text": _SUMMARY, "refs": list(first)},
        "sections": sections,
        "diagram_specs": [],
        "confidence_note": {"text": _NOTE, "refs": list(first)},
        FACTS_ONLY: True,
    }


def _evidence_ids(request) -> set:
    return {ref for ref, _ in _evidence(request)}


def _diagram_note(gate, index: int) -> str:
    """The note for the dropped diagram at ``index``."""
    reasons = gate.get("diagram_reasons") if isinstance(gate, dict) else None
    reason = reasons[index] if isinstance(reasons, list) \
        and index < len(reasons) else None
    slug = reason if isinstance(reason, str) and reason else _FALLBACK_REASON
    return DIAGRAM_NOTE_PREFIX + explain_diagram_check.reason_text(slug)


def _split_diagrams(specs: list, gate) -> tuple:
    """(the usable specs, one note per dropped spec), both in index order."""
    ok = gate.get("diagrams_ok") if isinstance(gate, dict) else None
    ok = ok if isinstance(ok, list) else []
    kept, notes = [], []
    for i, spec in enumerate(specs):
        if i < len(ok) and ok[i] is True:
            kept.append(spec)
        else:
            notes.append(_diagram_note(gate, i))
    return kept, notes


def merge_notes(prior, own) -> list:
    """The notes of ``prior`` that are our own form, then ``own``, each once.

    A string of ``prior`` is kept only when it equals DIAGRAM_NOTE_PREFIX plus
    one explain_diagram_check.REASONS sentence; any other value (drafter text,
    a non-string) is dropped. ``own`` is the notes finalize just built, kept
    as given. Order is ``prior`` first, then ``own``; a repeat is skipped. A
    ``prior`` or ``own`` that is not a list counts as empty.
    """
    ours = {DIAGRAM_NOTE_PREFIX + sentence
            for sentence in explain_diagram_check.REASONS.values()}
    kept = [n for n in prior if isinstance(n, str) and n in ours] \
        if isinstance(prior, list) else []
    merged = []
    for note in kept + (own if isinstance(own, list) else []):
        if note not in merged:
            merged.append(note)
    return merged


def _style_note(env: dict) -> str | None:
    result = ste_lint.lint(env)
    if result["passed"]:
        return None
    rules = []
    for issue in result["issues"]:
        if issue["rule"] not in rules:
            rules.append(issue["rule"])
    return ("Style note: this text did not pass the STE writing check "
            f"({', '.join(rules)}). The facts in it are unchanged.")


def finalize(env, request, gate) -> dict:
    """The envelope to render after the one rewrite; see the module docstring."""
    kind = _kind(request)
    codes = explain_envelope.validate_envelope(env, kind)
    if not isinstance(env, dict) or any(c != "raw-diagram" for c in codes):
        return facts_only(request)
    ids = _evidence_ids(request)
    out = copy.deepcopy(env)
    out.pop(STYLE_NOTE, None)
    out[FACTS_ONLY] = False
    sections = []
    for sec in out["sections"]:
        sec["items"] = [item for item in sec["items"]
                        if evidence_refs.supported(item, ids)]
        if sec["items"]:
            sections.append(sec)
    out["sections"] = sections
    out["diagram_specs"], out[DIAGRAM_NOTES] = _split_diagrams(
        out["diagram_specs"], gate)
    if (explain_envelope.validate_envelope(out, kind)
            or evidence_refs.check_refs(out, request)["unsupported"]):
        return facts_only(request)
    note = _style_note(out)
    if note is not None:
        out[STYLE_NOTE] = note
    return out


def _texts(env) -> list:
    """The summary, section item and note texts of ``env``, in envelope order."""
    if not isinstance(env, dict):
        return []
    blocks = [env.get("ste_summary")]
    sections = env.get("sections")
    for sec in sections if isinstance(sections, list) else []:
        items = sec.get("items") if isinstance(sec, dict) else None
        blocks.extend(items if isinstance(items, list) else [])
    blocks.append(env.get("confidence_note"))
    return [b["text"] for b in blocks
            if isinstance(b, dict) and isinstance(b.get("text"), str)]


def prose(env) -> str:
    """Every text field of ``env`` joined by newlines, in envelope order."""
    return "\n".join(_texts(env))


def check_outcome(draft, checked) -> str:
    """"accepted", "edited" or "rewritten", by the prose diff ratio."""
    ratio = difflib.SequenceMatcher(None, prose(draft), prose(checked),
                                    autojunk=False).ratio()
    if ratio == 1.0:
        return "accepted"
    return "edited" if ratio >= EDITED_MIN_RATIO else "rewritten"
