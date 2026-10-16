"""Ruling envelope for finalizer question stops: constants + text helpers.

design: fable-escalation 1.1-1.3, 3.2 — constants, whitespace/section
helpers, chosen option, pillar-doc loading, the `check_shape` ruling-key
shape check, the `check` pillar rules and the `brief_lines` brief tail
for resolved question stops. Pure except `load_pillars` and
`brief_lines`' doc-presence probe; stdlib only.
"""

from __future__ import annotations

import re
from pathlib import Path

import lessons

RULING_KEYS = ("options", "pillar_basis", "tie_breaker", "commits_to", "confidence",
               "lesson_proposal")
GENERAL_KINDS = ("decision", "lesson")
OPERATOR_ONLY = ("merge", "force-push", "remote-delete", "classifier-denial",
                 "standing-order", "scope-growth", "base-sync-hunk")  # last: seat ruling
KINDS = GENERAL_KINDS + OPERATOR_ONLY
PILLAR_DOCS = ("vision.md", "architecture.md")  # under three-pillars-docs/
EMPTY_RULING = {"options": [], "pillar_basis": [], "tie_breaker": None,
                "commits_to": [], "confidence": "low", "lesson_proposal": None}

_PILLARS_DIR = "three-pillars-docs"
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_CONFIDENCES = ("high", "medium", "low")
_STANCES = ("serves", "violates")
_LESSON_ACTIONS = ("add", "remove")
_LESSON_LAYERS = ("repo", "user")


def normalize_ws(text: str) -> str:
    """Collapse every run of whitespace to a single space."""
    return " ".join(text.split())


def _headings(doc: str) -> list[tuple[int, int, str]]:
    """(line index, level, normalised heading text) for every markdown heading
    outside a ``` fence."""
    out = []
    fenced = False
    for idx, line in enumerate(doc.splitlines()):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced:
            m = _HEADING.match(line)
            if m:
                out.append((idx, len(m.group(1)), normalize_ws(m.group(2))))
    return out


def section_text(doc: str, section: str) -> str | None:
    """Body of the `##`/`###` heading whose text == section (ws-normalised).

    The body runs to the next heading of the same or a higher level, so nested
    subsections are included. None when the section is absent or matched twice.
    """
    want = normalize_ws(section)
    hits = [(idx, lvl) for idx, lvl, text in _headings(doc)
            if lvl in (2, 3) and text == want]
    if len(hits) != 1:
        return None
    idx, lvl = hits[0]
    lines = doc.splitlines()
    end = len(lines)
    for hidx, hlvl, _ in _headings(doc):
        if hidx > idx and hlvl <= lvl:
            end = hidx
            break
    return "\n".join(lines[idx + 1:end]).strip()


def chosen(options) -> dict | None:
    """The single option with `recommended` true; None unless exactly one."""
    if not isinstance(options, list):
        return None
    picks = [o for o in options
             if isinstance(o, dict) and o.get("recommended")]
    return picks[0] if len(picks) == 1 else None


def _valid_option(o) -> bool:
    return (isinstance(o, dict)
            and all(isinstance(o.get(k), str)
                    for k in ("id", "label", "description"))
            and isinstance(o.get("recommended"), bool))


def _valid_basis(e) -> bool:
    return (isinstance(e, dict)
            and all(isinstance(e.get(k), str)
                    for k in ("option", "doc", "section", "quote"))
            and e.get("stance") in _STANCES)


def _valid_lesson(l) -> bool:
    if not isinstance(l, dict):
        return False
    if l.get("action") not in _LESSON_ACTIONS or l.get("layer") not in _LESSON_LAYERS:
        return False
    if not all(isinstance(l.get(k), str) for k in ("text", "applies_when")):
        return False
    if "lesson_id" in l and not isinstance(l["lesson_id"], str):
        return False
    contradicts = l.get("contradicts")
    if not isinstance(contradicts, list):
        return False
    return all(isinstance(c, dict)
               and all(isinstance(c.get(k), str) for k in ("doc", "section", "quote"))
               for c in contradicts)


_SHAPE_OK = {
    "options": lambda v: isinstance(v, list) and all(_valid_option(o) for o in v),
    "pillar_basis": lambda v: isinstance(v, list) and all(_valid_basis(e) for e in v),
    "tie_breaker": lambda v: v is None or isinstance(v, str),
    "commits_to": lambda v: isinstance(v, list)
                            and all(isinstance(s, str) for s in v),
    "confidence": lambda v: v in _CONFIDENCES,
    "lesson_proposal": lambda v: v is None or _valid_lesson(v),
}


def check_shape(data: dict) -> list[str]:
    """Type/enum check of every PRESENT ruling key; [] = ok.

    Runs on every source and outcome. An absent key is not its job — the
    missing-keys check in `finalizer_outcome.validate` owns that.
    """
    problems = []
    for key in RULING_KEYS:
        if key in data and not _SHAPE_OK[key](data[key]):
            problems.append(f"finalizer-errored: bad {key}")
    return problems


def _names_pillar(item: str) -> bool:
    """True when a token of ``item`` names a pillar doc by basename.

    The basename is the text after the last ``/`` or ``\\``, stripped of
    surrounding backticks, quotes and ``,.;:()``, lower-cased — so
    ``docs/Vision.md`` names a pillar but ``supervision.md`` does not.
    """
    for token in item.split():
        name = token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if name.strip("`\"',.;:()").lower() in PILLAR_DOCS:
            return True
    return False


def check(data: dict, pillars: dict, kind: str | None) -> list[str]:
    """Pillar rules for a `resolved` `question` stop; every problem found.

    Rows follow the detailed design's `check` table. Operator-only kinds
    escalate first; empty `pillars` short-circuits to `no-pillar-basis`.
    """
    if kind in OPERATOR_ONLY:
        return [f"operator-only: {kind}"]
    if not pillars:
        return ["no-pillar-basis"]
    problems = []
    pick = chosen(data.get("options"))
    entries = []
    if pick is None:
        problems.append("pillar-basis-missing: no chosen option")
    else:
        entries = [e for e in data.get("pillar_basis", [])
                   if isinstance(e, dict) and e.get("option") == pick["id"]]
        if not any(e.get("stance") == "serves" for e in entries):
            problems.append(f"pillar-basis-missing: {pick['id']}")
    for e in entries:
        doc, section = e.get("doc", ""), e.get("section", "")
        body = section_text(pillars[doc], section) \
            if doc in PILLAR_DOCS and doc in pillars else None
        quote = normalize_ws(e.get("quote", ""))
        if body is None or not quote or quote not in normalize_ws(body):
            problems.append(
                f"pillar-basis-missing: quote not under {doc} § {section}")
        if e.get("stance") == "violates":
            problems.append(f"pillar-conflict: {doc} § {section}")
    for item in data.get("commits_to", []):
        if isinstance(item, str) and _names_pillar(item):
            problems.append("pillar-change: propose /tp-docs-update")
    return problems


def load_pillars(root) -> dict[str, str]:
    """{doc name: text} for each PILLAR_DOCS entry under three-pillars-docs/.

    Missing or unreadable docs are simply omitted — never raises.
    """
    base = Path(root) / _PILLARS_DIR
    pillars = {}
    for name in PILLAR_DOCS:
        try:
            pillars[name] = (base / name).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
    return pillars


def brief_lines(entry: str, repo_root, decisions) -> list[str]:
    """Question-stop brief tail: basis docs present, then the envelope rules."""
    root = Path(repo_root)
    present = [f"- {_PILLARS_DIR}/{n}" for n in PILLAR_DOCS
               if (root / _PILLARS_DIR / n).is_file()]
    layers = [f"- {lessons.REPO_REL}"] if (root / lessons.REPO_REL).is_file() else []
    user = lessons.user_path()
    if user.is_file():
        layers.append(f"- {user}")
    lines = [f"- entry: {entry}", "Basis docs present:",
             *(present or ["- (none found)"]),
             *(layers or ["- (none found)"]),
             f"- decisions log (context, not a basis): {decisions}"]
    if not present:
        lines.append("No pillar doc found: reply `escalate` (`no-pillar-basis`).")
    keys = ", ".join(f"`{k}`" for k in RULING_KEYS)
    kinds = ", ".join(f"`{k}`" for k in OPERATOR_ONLY)
    lines += [
        f"Ruling keys (all present in the reply): {keys}.",
        "Chosen option = the one with `recommended: true`.",
        "A `serves` basis entry quotes verbatim from under the named `##`/`###` `section` of the named `doc`.",
        f"Operator-only kinds always escalate: {kinds}.",
        "A pillar-doc change escalates as a `/tp-docs-update` proposal.",
    ]
    return lines
