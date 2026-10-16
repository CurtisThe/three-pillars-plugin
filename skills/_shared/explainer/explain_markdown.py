"""explainer/explain_markdown.py — the forge markdown comment.

Public API:
    render_markdown(env, *, head, marker) -> str
    render_rulings_comment(rows, *, head, cap=COMMENT_CAP, html_hint, slug)
    ruling_hook(ruling_id) -> str
    HOOK_RE, COMMENT_CAP
    escape_md(value) -> str

render_markdown renders one explain envelope (any kind) as a PR comment body
for GitHub and Gitea (>= 1.17). The body holds, in order:

    marker           the caller's explainer_marker.marker(...) line, first,
                     so the review loop skips the comment
    heading          the kind and "Briefed head: <head>"
    facts-only label when env["facts_only"] is True
    style note       when env["style_note"] is a non-empty string
    summary          ste_summary text and its refs
    diagram notes    one "> <note>" line per string in env["diagram_notes"]
                     (a dropped diagram: "diagram omitted: <reason>"); none
                     when the key is absent or empty
    diagrams         one ```mermaid block per diagram_specs entry that
                     explain_mermaid.spec_mermaid can draw; it omits the rest
    sections         one collapsed <details> per envelope section, in
                     envelope order: the title in <summary>, then one list
                     item per section item, with "(Recommended)" when the
                     item has "recommended": true, and its refs; in the
                     rulings-without-you section each item is followed by
                     ruling_hook(<id>) for every ruling:<id> ref it cites
    confidence note  confidence_note text and its refs

render_rulings_comment renders the one rolling rulings comment. ``rows`` are
the ledger rows, oldest first: each is an auto-ruling envelope that stores
its ``id`` (r<n>). The body holds the rulings marker
(explainer_marker.marker("rulings", slug, head)) first, a heading, then one
collapsed <details> per ruling (the summary in <summary>; the diagrams,
sections and confidence note inside, and the row's diagram_notes lines after
its labels) that ends with ruling_hook(<id>). When the body is longer than ``cap`` chars, the oldest rulings collapse first, one
at a time, to one headline line each ("- Ruling <id>: <summary> <hook>"),
and a line names ``html_hint`` (the page with every ruling in full). If the
body is still too long with every ruling collapsed, it is returned as is.
``slug`` goes in the marker, so post_or_edit's marker fallback finds the
comment; sync_rulings passes the design slug.

ruling_hook(id) is the fixed agree / disagree line. HOOK_RE matches the two
replies it asks for ("agree r1", "disagree r1: <reason>") at the start of a
line, any case; groups: verdict, id, reason (None for agree). The hook is
framework text, but it holds the ruling id, so the renderers pass the whole
line through escape_md.

Escaping: every model string (kind, texts, titles, refs, the style and diagram
notes) goes through escape_md, and its whitespace runs fold to one space, so it
stays on its own line. The mermaid text comes from the sanitized spec (explain_mermaid
escapes the labels) and gets only the proof: break of step 4 below. The
caller's marker and head are not model text and go in as given.

escape_md(value):
    1. removes every "<!-- tp-explainer:" (explainer_marker.MARKER_PREFIX),
       again until none is left, so a model string never carries a marker;
    2. escapes & < > (so "</details><details open>" is inert text);
    3. puts U+2060 WORD JOINER after every "@", so "@octocat" never pings;
    4. puts U+2060 between "proof" and ":", so no line matches the
       review_proof digest patterns ("proof: base ..." / "proof: ⚠️ DEGRADED").
The joiners do not show, and the entities show as the original characters.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import html as _html
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from explain_html import FACTS_ONLY_LABEL  # noqa: E402
from explain_mermaid import spec_mermaid  # noqa: E402
from explainer_marker import MARKER_PREFIX, marker as _marker  # noqa: E402

WORD_JOINER = "⁠"

COMMENT_CAP = 60000          # chars; GitHub refuses a comment over 65536
HEADLINE_CHARS = 200         # model chars kept in a collapsed headline
RULINGS_SECTION = "rulings-without-you"
RULING_REF = "ruling:"

HOOK_RE = re.compile(
    r"^[ \t]*(?P<verdict>agree|disagree)[ \t]+(?P<id>r\d+)\b"
    r"(?:[ \t]*:[ \t]*(?P<reason>[^\r\n]*\S))?",
    re.IGNORECASE | re.MULTILINE)

# The review_proof digest token, any case: "proof" directly before ":".
_PROOF_TOKEN_RE = re.compile(r"(proof)(:)", re.IGNORECASE)


def _break_proof(text: str) -> str:
    return _PROOF_TOKEN_RE.sub(lambda m: m.group(1) + WORD_JOINER + m.group(2),
                               text)


def escape_md(value) -> str:
    """Model text made inert for a bot-posted comment; see the module docstring."""
    text = str(value)
    while MARKER_PREFIX in text:
        text = text.replace(MARKER_PREFIX, "")
    text = _html.escape(text, quote=False)
    text = text.replace("@", "@" + WORD_JOINER)
    return _break_proof(text)


def _inline(value) -> str:
    """escape_md, on one line."""
    return " ".join(escape_md(value).split())


def _text(block) -> str:
    text = block.get("text") if isinstance(block, dict) else None
    return _inline(text) if text is not None else ""


def _refs(block) -> str:
    """ " (refs: a, b)" for a {text, refs} block ("" if none)."""
    refs = block.get("refs") if isinstance(block, dict) else None
    if not isinstance(refs, list) or not refs:
        return ""
    return " (refs: " + ", ".join(_inline(r) for r in refs) + ")"


def ruling_hook(ruling_id) -> str:
    """The fixed agree / disagree line for one ruling."""
    rid = str(ruling_id)
    return (f'Your call on ruling {rid}: reply "agree {rid}" or '
            f'"disagree {rid}: <reason>".')


def _hook(ruling_id) -> str:
    return _inline(ruling_hook(ruling_id))


def _ruling_ids(item) -> list:
    """The distinct ids of the item's ruling:<id> refs, in ref order."""
    refs = item.get("refs") if isinstance(item, dict) else None
    ids = []
    for ref in refs if isinstance(refs, list) else []:
        rid = ref[len(RULING_REF):].strip() if isinstance(ref, str) and \
            ref.startswith(RULING_REF) else ""
        if rid and rid not in ids:
            ids.append(rid)
    return ids


def _item(item, *, hooks=False) -> str:
    badge = ""
    if isinstance(item, dict) and item.get("recommended") is True:
        badge = " **(Recommended)**"
    line = f"- {_text(item)}{badge}{_refs(item)}"
    if hooks:
        line += "".join(f"\n  {_hook(r)}" for r in _ruling_ids(item))
    return line


def _section(sec) -> str:
    if not isinstance(sec, dict):
        return ""
    items = sec.get("items")
    hooks = sec.get("id") == RULINGS_SECTION
    lines = ([_item(i, hooks=hooks) for i in items]
             if isinstance(items, list) else [])
    return "\n".join([
        "<details>",
        f"<summary>{_inline(sec.get('title', ''))}</summary>",
        "",
        *lines,
        "",
        "</details>",
    ])


def _diagram(spec) -> str:
    mermaid = spec_mermaid(spec)
    if mermaid is None:
        return ""
    return f"```mermaid\n{_break_proof(mermaid)}\n```"


def _labels(env: dict) -> list:
    parts = []
    if env.get("facts_only") is True:
        parts.append(f"> **{_html.escape(FACTS_ONLY_LABEL, quote=False)}**")
    note = env.get("style_note")
    if isinstance(note, str) and note:
        parts.append(f"> {_inline(note)}")
    return parts


def _diagram_notes(env: dict) -> list:
    """One "> <note>" line per string in env["diagram_notes"]."""
    notes = env.get("diagram_notes")
    notes = notes if isinstance(notes, list) else []
    return [f"> {_inline(n)}" for n in notes if isinstance(n, str) and n.strip()]


def render_markdown(env, *, head, marker) -> str:
    """The forge comment body for ``env``; see the module docstring."""
    env = env if isinstance(env, dict) else {}
    parts = [
        str(marker),
        f"### Explainer: {_inline(env.get('kind', ''))}",
        f"Briefed head: `{head}`",
    ]
    parts += _labels(env)
    summary = env.get("ste_summary")
    parts.append(f"{_text(summary)}{_refs(summary)}")
    parts += _diagram_notes(env)
    specs = env.get("diagram_specs")
    parts += [_diagram(s) for s in (specs if isinstance(specs, list) else [])]
    sections = env.get("sections")
    parts += [_section(s) for s in (sections if isinstance(sections, list) else [])]
    note = env.get("confidence_note")
    parts.append(f"Confidence: {_text(note)}{_refs(note)}")
    return "\n\n".join(p for p in parts if p) + "\n"


def _ruling_section(sec) -> str:
    if not isinstance(sec, dict):
        return ""
    items = sec.get("items")
    lines = [_item(i) for i in items] if isinstance(items, list) else []
    return "\n".join([f"**{_inline(sec.get('title', ''))}**", "", *lines])


def _ruling_block(row: dict) -> str:
    rid = row.get("id", "")
    parts = ["<details>\n<summary>Ruling "
             f"{_inline(rid)}: {_text(row.get('ste_summary'))}</summary>"]
    parts += _labels(row)
    parts += _diagram_notes(row)
    specs = row.get("diagram_specs")
    parts += [_diagram(s) for s in (specs if isinstance(specs, list) else [])]
    sections = row.get("sections")
    parts += [_ruling_section(s)
              for s in (sections if isinstance(sections, list) else [])]
    note = row.get("confidence_note")
    parts += [f"Confidence: {_text(note)}{_refs(note)}", _hook(rid),
              "</details>"]
    return "\n\n".join(p for p in parts if p)


def _ruling_headline(row: dict) -> str:
    rid = row.get("id", "")
    summary = row.get("ste_summary")
    text = summary.get("text") if isinstance(summary, dict) else None
    short = " ".join(str(text if text is not None else "").split())
    if len(short) > HEADLINE_CHARS:
        short = short[:HEADLINE_CHARS - 1].rstrip() + "…"
    return f"- Ruling {_inline(rid)}: {escape_md(short)} {_hook(rid)}"


def render_rulings_comment(rows, *, head, cap=COMMENT_CAP, html_hint=None,
                           slug="-") -> str:
    """The rolling rulings comment body; see the module docstring."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    full = [_ruling_block(r) for r in rows]
    headlines = [_ruling_headline(r) for r in rows]
    top = [_marker("rulings", slug, head), "### Fable rulings",
           f"Fable made these rulings without you. Head: `{head}`"]
    hint = "Older rulings show as one line each."
    if html_hint:
        hint += f" The full text of every ruling is in {_inline(html_hint)}"
    body = ""
    for n in range(len(rows) + 1):
        parts = top + ([hint, "\n".join(headlines[:n])] if n else [])
        body = "\n\n".join(parts + full[n:]) + "\n"
        if len(body) <= cap:
            break
    return body
