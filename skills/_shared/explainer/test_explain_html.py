"""test_explain_html.py — the offline HTML page for every explain kind.

Covers explainer-agent plan Task 6.2 (detailed-design §Interfaces:
"render_html(env, *, head, title) -> str passes assert_offline, and every
model string goes through safe_text and is escaped once"; design: "Every HTML
page passes assert_offline"):
  - one valid envelope of each kind, with a flow and a sequence diagram,
    renders to a page that passes explain_offline.assert_offline (guard),
    holds an inline <style> and each diagram's spec_svg inline, names the
    head, and has one data-section element per envelope section, in order;
  - a hostile section item text is escaped once (no "&amp;lt;") with its URL
    neutralized, and a hostile string in any model field keeps the page
    offline;
  - a facts_only envelope shows a visible "facts only" label (and an
    unflagged one does not); a style_note shows.

Envelopes are built here from the §Interfaces shapes; no repo docs are read.
Assertions read the parsed page (html.parser), not pinned markup
(skills/_shared/test-fragility.md).
"""
import copy
import sys
from html.parser import HTMLParser
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import explain_envelope  # noqa: E402
import explain_offline  # noqa: E402
import explain_text  # noqa: E402
from explain_html import render_html  # noqa: E402
from explain_svg import spec_svg  # noqa: E402

HEAD = "abc123"
HOSTILE = "<script>x</script> https://evil"

FLOW = {"kind": "flow", "nodes": ["draft", "gate", "render"],
        "edges": [["draft", "gate"], ["gate", "render"]]}
SEQUENCE = {"kind": "sequence", "nodes": ["fable", "explainer", "forge"],
            "messages": [["fable", "explainer", "draft brief"],
                         ["explainer", "forge", "post comment"]]}


def _envelope(kind: str) -> dict:
    """A valid ``kind`` envelope: every required section, two diagrams."""
    sections = []
    for i, sid in enumerate(explain_envelope.REQUIRED_SECTIONS[kind]):
        item = {"text": f"Item {i} for {sid}.", "refs": ["diffstat"]}
        if sid == "options":
            item["recommended"] = True
        sections.append({"id": sid, "title": f"Title {i}", "items": [item]})
    env = {
        "schema": explain_envelope.SCHEMA,
        "kind": kind,
        "ste_summary": {"text": "The change adds a brief.", "refs": ["diffstat"]},
        "sections": sections,
        "diagram_specs": [copy.deepcopy(FLOW), copy.deepcopy(SEQUENCE)],
        "confidence_note": {"text": "The evidence is the diff.",
                            "refs": ["diffstat"]},
    }
    assert explain_envelope.validate_envelope(env, kind) == []
    return env


class _Page(HTMLParser):
    """Visible body text, data-section ids, style text and the <title>."""

    _HIDDEN = ("style", "script", "title", "head")

    def __init__(self, page: str):
        super().__init__(convert_charrefs=True)
        self.stack: list = []
        self.text: list = []
        self.sections: list = []
        self.style = ""
        self.title = ""
        self.feed(page)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)
        for name, value in attrs:
            if name == "data-section":
                self.sections.append(value)

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass

    def handle_data(self, data):
        if "style" in self.stack:
            self.style += data
        elif "title" in self.stack:
            self.title += data
        elif not any(t in self.stack for t in self._HIDDEN):
            self.text.append(data)

    @property
    def visible(self) -> str:
        return " ".join(" ".join(self.text).split())


def _visible(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.parametrize("kind", explain_envelope.KINDS)
def test_every_kind_renders_an_offline_page(kind):
    env = _envelope(kind)
    page = render_html(env, head=HEAD, title="t")
    explain_offline.assert_offline(page)
    parsed = _Page(page)
    assert parsed.style.strip(), "no inline <style> content"
    assert parsed.title == "t"
    assert HEAD in parsed.visible
    for spec in env["diagram_specs"]:
        assert spec_svg(spec) in page
    assert parsed.sections == [s["id"] for s in env["sections"]]


@pytest.mark.parametrize("kind", explain_envelope.KINDS)
def test_every_model_text_shows_in_its_section_order(kind):
    env = _envelope(kind)
    visible = _Page(render_html(env, head=HEAD, title="t")).visible
    assert _visible(env["ste_summary"]["text"]) in visible
    assert _visible(env["confidence_note"]["text"]) in visible
    positions = []
    for sec in env["sections"]:
        assert sec["title"] in visible
        positions.append(visible.index(sec["items"][0]["text"]))
    assert positions == sorted(positions)


def test_hostile_item_text_is_escaped_once_and_neutralized():
    env = _envelope("pr-brief")
    env["sections"][0]["items"][0]["text"] = HOSTILE
    page = render_html(env, head=HEAD, title="t")
    explain_offline.assert_offline(page)
    assert explain_text.safe_text(HOSTILE) in page
    assert "&amp;lt;" not in page
    assert "<script" not in page.lower()
    assert "https://evil" not in page
    assert _visible(HOSTILE) in _Page(page).visible


def _set_summary(env):
    env["ste_summary"]["text"] = HOSTILE


def _set_title(env):
    env["sections"][1]["title"] = HOSTILE


def _set_note(env):
    env["confidence_note"]["text"] = HOSTILE


def _set_ref(env):
    env["sections"][0]["items"][0]["refs"] = [HOSTILE]


def _set_style_note(env):
    env["style_note"] = HOSTILE


@pytest.mark.parametrize("mutate", [_set_summary, _set_title, _set_note,
                                    _set_ref, _set_style_note])
def test_hostile_text_in_any_model_field_stays_offline(mutate):
    env = _envelope("human-escalation")
    mutate(env)
    page = render_html(env, head=HEAD, title="t")
    explain_offline.assert_offline(page)
    assert "&amp;lt;" not in page
    assert "<script" not in page.lower()


def test_facts_only_envelope_shows_a_visible_label():
    env = _envelope("auto-ruling")
    env["facts_only"] = True
    flagged = _Page(render_html(env, head=HEAD, title="t")).visible
    env["facts_only"] = False
    plain = _Page(render_html(env, head=HEAD, title="t")).visible
    assert "facts only" in flagged.lower()
    assert "facts only" not in plain.lower()


def test_style_note_shows():
    env = _envelope("pr-brief")
    note = "Style note: this text did not pass the STE writing check (S1)."
    env["style_note"] = note
    visible = _Page(render_html(env, head=HEAD, title="t")).visible
    assert note in visible


def test_render_never_mutates_the_envelope():
    env = _envelope("human-escalation")
    before = copy.deepcopy(env)
    render_html(env, head=HEAD, title="t")
    assert env == before
