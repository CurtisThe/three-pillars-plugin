"""explainer/explain_card.py — the question card, the log entry and the headline.

Public API:
    render_card(env, html_path) -> {question, options: [{label, description}]}
    render_log_entry(env) -> str
    headline(env, brief_path) -> str
    HEADLINE_MAX, LABEL_CHARS, TITLE_CHARS

render_card turns a human-escalation envelope into the text of one
AskUserQuestion card (plain text, not HTML or markdown). The question is the
"question" section's items (else the summary), then the HTML page path:
"<question> (Full explanation: <html_path>)". There is one option per
"options" item: the first item with "recommended": true comes first and its
label ends " (Recommended)"; the rest keep their envelope order. A label and
its description come from the item: its "label" key when that is a
non-blank string (the text is then the description), else the text before
the first " — ", ": " or " - " that sits within LABEL_CHARS chars (the rest
is the description), else the text cut to LABEL_CHARS chars on a word
boundary (the whole text is the description). Model text never carries its
own "(Recommended)": it is removed from every label and description first.

render_log_entry gives one auto-mode Decision Entry
(skills/_shared/auto-mode.md) for decisions.md:

    ### [explainer] <title>
    **Question**: <the question section, else the summary>
    **Decided**: <the decided items>
    **Reasoning**: <the why items>
    **Confidence**: <the confidence note>

The title is the summary cut to TITLE_CHARS chars, after "Ruling <id>: "
when the envelope stores its ledger id. A field with no text reads "(none)".

headline gives one line of at most HEADLINE_MAX chars for the PR body (the
Gitea AGit description keeps its first line): "<summary> — brief:
<brief_path>". The summary goes through explain_markdown.escape_md (the PR
body is a bot-posted body), and an over-budget summary is cut on a word
boundary with "…"; the brief path is never cut. A path that alone overruns
the budget gives "brief: <brief_path>".

In all three, every model string has its whitespace runs (line breaks
included) folded to one space, so it stays on its own line.

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

from explain_markdown import escape_md  # noqa: E402

HEADLINE_MAX = 300           # chars in the one-line headline
LABEL_CHARS = 60             # most chars of a card label taken from the text
TITLE_CHARS = 80             # most chars of a log entry title
RECOMMENDED = " (Recommended)"
ELLIPSIS = "…"

_LABEL_SEPARATORS = (" — ", ": ", " - ")
_RECOMMENDED_RE = re.compile(r"\(\s*recommended\s*\)", re.IGNORECASE)
_PARTIAL_ENTITY_RE = re.compile(r"&[#\w]*$")
_NEWLINES_RE = re.compile(r"[\r\n]+")


def _line(value) -> str:
    """``value`` as text on one line (whitespace runs folded)."""
    return " ".join(str(value).split()) if value is not None else ""


def _clip(text: str, limit: int) -> str:
    """``text`` cut to at most ``limit`` chars on a word boundary, with "…"."""
    if len(text) <= limit:
        return text
    cut = text[:max(limit - len(ELLIPSIS), 0)]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    else:
        cut = _PARTIAL_ENTITY_RE.sub("", cut)
    return cut.rstrip() + ELLIPSIS


def _section(env, sid: str):
    sections = env.get("sections") if isinstance(env, dict) else None
    for sec in sections if isinstance(sections, list) else []:
        if isinstance(sec, dict) and sec.get("id") == sid:
            return sec
    return None


def _items(env, sid: str) -> list:
    sec = _section(env, sid)
    items = sec.get("items") if sec else None
    return [i for i in items if isinstance(i, dict)] \
        if isinstance(items, list) else []


def _joined(env, sid: str) -> str:
    """The section's item texts, one line."""
    return _line(" ".join(str(i.get("text") or "") for i in _items(env, sid)))


def _block_text(env, key: str) -> str:
    block = env.get(key) if isinstance(env, dict) else None
    return _line(block.get("text")) if isinstance(block, dict) else ""


def _question(env) -> str:
    return _joined(env, "question") or _block_text(env, "ste_summary")


def _unmarked(value) -> str:
    """One line, with any model-written "(Recommended)" removed."""
    return _line(_RECOMMENDED_RE.sub(" ", _line(value)))


def _split(text: str) -> tuple:
    """(label, description) from one option text."""
    best = None
    for sep in _LABEL_SEPARATORS:
        idx = text.find(sep)
        if 0 < idx <= LABEL_CHARS and (best is None or idx < best[0]):
            best = (idx, sep)
    if best:
        idx, sep = best
        label = text[:idx].strip()
        rest = text[idx + len(sep):].strip()
        return label, rest or text
    return _clip(text, LABEL_CHARS), text


def _option(item: dict, index: int) -> dict:
    text = _unmarked(item.get("text"))
    own = _unmarked(item.get("label")) if isinstance(item.get("label"), str) \
        else ""
    label, description = (own, text) if own else _split(text)
    return {"label": label or f"Option {index + 1}", "description": description}


def render_card(env, html_path) -> dict:
    """The AskUserQuestion card for a human-escalation envelope."""
    question = _question(env)
    if html_path:
        question = f"{question} (Full explanation: {html_path})".strip()
    items = _items(env, "options")
    rec = next((i for i, item in enumerate(items)
                if item.get("recommended") is True), None)
    order = list(range(len(items)))
    if rec is not None:
        order = [rec] + [i for i in order if i != rec]
    options = [_option(items[i], i) for i in order]
    if rec is not None:
        options[0]["label"] += RECOMMENDED
    return {"question": question, "options": options}


def render_log_entry(env) -> str:
    """One auto-mode Decision Entry for decisions.md."""
    summary = _block_text(env, "ste_summary")
    title = _clip(summary, TITLE_CHARS) or _line(
        env.get("kind") if isinstance(env, dict) else "") or "ruling"
    rid = _line(env.get("id")) if isinstance(env, dict) else ""
    if rid:
        title = f"Ruling {rid}: {title}"
    fields = (
        ("Question", _question(env)),
        ("Decided", _joined(env, "decided")),
        ("Reasoning", _joined(env, "why")),
        ("Confidence", _block_text(env, "confidence_note")),
    )
    lines = [f"### [explainer] {title}"]
    lines += [f"**{name}**: {value or '(none)'}" for name, value in fields]
    return "\n".join(lines) + "\n"


def headline(env, brief_path) -> str:
    """One line of at most HEADLINE_MAX chars that ends with ``brief_path``."""
    path = _NEWLINES_RE.sub(" ", str(brief_path)).strip()
    tail = f"brief: {path}"
    joiner = " — "
    prose = _line(escape_md(_block_text(env, "ste_summary")))
    room = HEADLINE_MAX - len(joiner) - len(tail)
    if not prose or room <= len(ELLIPSIS):
        return tail
    return f"{_clip(prose, room)}{joiner}{tail}"
