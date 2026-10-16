"""Finalizer outcome: reply validation, decisions.md entry, resolution note.

Pure functions, no I/O.
"""

import copy
import json
from pathlib import Path

import finalizer_ruling as fr

ALLOWED_ACTIONS = (
    "classify", "block-bar", "fix", "confirm", "converge",
    "move-lows", "answer-question", "env-fix",
)


# The reply envelope's keys, exactly: a missing key (a partial object) or an extra one escalates.
# The six ruling keys ride on EVERY source's reply (design: fable-escalation 1.4); only a
# `question` stop's `resolved` is pillar-checked — the others shape-check and stay as today.
REPLY_KEYS = ("outcome", "actions", "diagnosis", "reasoning", "demoted", "blocked") + fr.RULING_KEYS
# The finalizer's grounding docs (agents/tp-finalizer.md ## Grounding, finalizer._brief). A
# `resolved` must cite at least one in `reasoning`: a plain substring match, no scoring.
GROUNDING_DOCS = (
    "three-pillars-docs/vision.md",
    "three-pillars-docs/product_roadmap.md",
    "three-pillars-docs/architecture.md",
    "three-pillars-docs/known_issues.md",
    "three-pillars-docs/specs/",
)
DESIGN_DOCS = ("design.md", "decisions.md")  # in the stopped design's own directory
# A citation is a doc's file name (`vision.md`) or, for the specs dir, `specs/`; a full path
# contains its name, so it matches too. The cold `known_issues_low.md` is not read by default
# (not in GROUNDING_DOCS) but a Low cited by ID there still grounds a ruling.
CITE_TOKENS = (tuple(Path(d).name + ("/" if d.endswith("/") else "") for d in GROUNDING_DOCS)
               + DESIGN_DOCS + ("known_issues_low.md",))


def cites_grounding(reasoning: str) -> bool:
    """True when ``reasoning`` names a grounding doc by path or file name."""
    return any(token in reasoning for token in CITE_TOKENS)


def _escalate(problems, diagnosis="", reasoning="", demoted=None, ruling=None) -> dict:
    return {
        "outcome": "escalate",
        "problems": list(problems),
        "diagnosis": diagnosis,
        "reasoning": reasoning,
        "demoted": list(demoted or []),
        "ruling": copy.deepcopy(ruling or fr.EMPTY_RULING),
    }


def _ruling_of(data: dict) -> dict:
    """The reply's six ruling keys; a missing one falls back to a deep copy of
    its EMPTY_RULING value (results never share EMPTY_RULING's lists)."""
    return {k: copy.deepcopy(fr.EMPTY_RULING[k]) if k not in data else data[k]
            for k in fr.RULING_KEYS}


def validate(reply, pillars=None, kind=None, source=None) -> dict:
    """Map a finalizer reply (dict or JSON string) to resolved/escalate.

    ``source`` routes the ``resolved`` check: a ``question`` stop is pillar-checked
    (``finalizer_ruling.check``); every other source (and the default ``None``) keeps
    the ``cites_grounding`` rule. ``pillars`` and ``kind`` feed only the question
    check. Every result carries ``"ruling"``: the reply's six ruling keys, or
    ``EMPTY_RULING`` when the reply is missing, unparseable or not an object.
    """
    if reply is None or (isinstance(reply, str) and not reply.strip()):
        return _escalate(["finalizer-errored: missing reply"])
    data = reply
    if isinstance(reply, (str, bytes)):
        try:
            data = json.loads(reply)
        except (ValueError, TypeError):
            return _escalate(["finalizer-errored: unparseable JSON"])
    if not isinstance(data, dict):
        return _escalate(["finalizer-errored: reply is not an object"])
    ruling = _ruling_of(data)
    missing = [k for k in REPLY_KEYS if k not in data]
    extra = sorted(k for k in data if k not in REPLY_KEYS)
    diagnosis = str(data.get("diagnosis") or "")
    reasoning = str(data.get("reasoning") or "")
    raw = data.get("demoted")
    demoted = [str(x) for x in raw] if isinstance(raw, list) else []
    outcome = data.get("outcome")
    if outcome not in ("resolved", "escalate"):
        return _escalate([f"finalizer-errored: unknown outcome {outcome!r}"],
                         diagnosis, reasoning, demoted, ruling)
    problems = []
    if missing:
        problems.append(f"finalizer-errored: missing keys {missing}")
    if extra:
        problems.append(f"finalizer-errored: unexpected keys {extra}")
    if data.get("blocked"):
        problems.append(f"blocked: {data.get('blocked')}")
    actions = data.get("actions")
    if actions is None:
        actions = []
    if not isinstance(actions, list):
        problems.append("finalizer-errored: actions is not a list")
        actions = []
    for a in actions:
        if a not in ALLOWED_ACTIONS:
            problems.append(f"action not allowed: {a}")
    shape = fr.check_shape(data)
    problems += shape
    if outcome == "resolved":
        if source == "question":
            if not shape:  # a shape problem already escalates; check assumes valid shapes
                problems += fr.check(data, pillars or {}, kind)
        elif not cites_grounding(reasoning):
            problems.append("ungrounded: a resolved reasoning cites no grounding doc ("
                            + ", ".join(CITE_TOKENS) + ")")
    if problems:
        return _escalate(problems, diagnosis, reasoning, demoted, ruling)
    return {"outcome": outcome, "problems": [], "diagnosis": diagnosis,
            "reasoning": reasoning, "demoted": demoted, "actions": list(actions),
            "ruling": ruling}


def decision_entry(stop, result, model_used="fable", fallback_reason=None,
                   ruling_id=None) -> str:
    """Render the decisions.md entry for a finalizer run.

    ``ruling_id`` names the stop's ruling file (design: fable-escalation 1.5); when
    set it is a line directly after ``Diagnosis``. Unset, the entry is unchanged.
    """
    outcome = result.get("outcome", "escalate")
    lines = [
        f"### [finalizer] {outcome} — {stop.get('source')}/{stop.get('signal')}",
        f"- **Decided**: {outcome}",
        f"- **Reasoning**: {result.get('reasoning') or '(none given)'}",
        "- **Confidence**: " + ("high" if outcome == "resolved" else "low"),
        f"- **Model**: {model_used}",
        f"- **Diagnosis**: {result.get('diagnosis') or '(none given)'}",
    ]
    if ruling_id:
        lines.append(f"- **Ruling**: {ruling_id}")
    if result.get("problems"):
        lines.append("- **Problems**: " + "; ".join(result["problems"]))
    if model_used == "opus":
        lines.append(f"- **finalizer-fallback**: {fallback_reason or 'unspecified'}")
    return "\n".join(lines) + "\n"


def resolution_note(stop, result, extension=None) -> str:
    """Short Markdown body naming actions, extension and demoted findings."""
    lines = [
        f"Finalizer {result.get('outcome', 'escalate')} for "
        f"{stop.get('source')}/{stop.get('signal')}.",
    ]
    actions = result.get("actions") or []
    if actions:
        lines.append("Actions: " + ", ".join(actions) + ".")
    if extension:
        lines.append(f"Extended {extension['signal']} "
                     f"{extension['from']} → {extension['to']}.")
    else:
        lines.append("No budget was extended.")
    demoted = result.get("demoted") or []
    if demoted:
        lines.append("Demoted findings:")
        lines.extend(f"- {d}" for d in demoted)
    return "\n".join(lines) + "\n"
