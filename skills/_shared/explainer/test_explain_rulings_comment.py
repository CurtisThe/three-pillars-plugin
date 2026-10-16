"""test_explain_rulings_comment.py — the rulings comment and its hooks.

Covers explainer-agent plan Task 6.4 (detailed-design §Interfaces:
"render_rulings_comment(rows, *, head, cap=COMMENT_CAP=60000, html_hint):
marker kind rulings first, then one <details> per ruling, with all ruling
text through escape_md; past the cap the oldest collapse to headlines plus
the HTML path. Each ruling block ends with ruling_hook(ruling_id), and a
collapsed headline keeps it"; "The pr-brief rulings-without-you section ...
each item carries the same ruling_hook line"; Test Strategy §Renderers):
  - ruling_hook is the fixed agree / disagree line; HOOK_RE matches both
    replies and captures the ruling id;
  - the body starts with the rulings marker; one <details> per ruling, each
    ending in its own hook;
  - a small cap collapses the oldest rulings first, to one headline line
    each that still ends in its hook, and names the HTML path;
  - guard: ruling text with proof: and a head sha never matches the
    review_proof digest patterns, full or collapsed;
  - guard: each pr-brief rulings-without-you item is followed by the hook
    of the ruling it cites (its ruling:<id> ref).

Rows are auto-ruling envelopes plus their ledger id, built here from the
§Interfaces shapes; no repo docs are read. Assertions read the parsed
comment, not pinned markup (skills/_shared/test-fragility.md).
"""
import html
import sys
from html.parser import HTMLParser
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
_PROOF_DIR = _SHARED_DIR.parent / "tp-pr-iterate" / "scripts"
for _p in (_PROOF_DIR, _SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import explain_envelope  # noqa: E402
import explainer_marker  # noqa: E402
from explain_markdown import (  # noqa: E402
    COMMENT_CAP, HOOK_RE, render_markdown, render_rulings_comment,
    ruling_hook)
from review_proof import _DEGRADED_RE, _DIGEST_HEAD_RE  # noqa: E402

HEAD = "abc123"
SHA40 = "0123456789abcdef0123456789abcdef01234567"
WJ = "⁠"
HTML_HINT = "/x/rulings.html"

DIGEST_SPOOF = f"proof: base `abc1234` · head `{SHA40}` · 3 rounds"
DEGRADED_SPOOF = "proof: ⚠️ DEGRADED (no runner) — see the log"
SHORT_SPOOF = "proof: abc1234"


def _row(n: int) -> dict:
    """Ledger row r<n>: an auto-ruling envelope that stores its id."""
    sections = [
        {"id": sid, "title": f"Title {sid}",
         "items": [{"text": f"Ruling {n} {sid} item {j} restates the "
                            f"evidence for this part of the ruling.",
                    "refs": ["diffstat"]} for j in range(3)]}
        for sid in explain_envelope.REQUIRED_SECTIONS["auto-ruling"]]
    env = {
        "schema": explain_envelope.SCHEMA,
        "kind": "auto-ruling",
        "ste_summary": {"text": f"Fable chose option {n}.",
                        "refs": ["subject:question"]},
        "sections": sections,
        "diagram_specs": [],
        "confidence_note": {"text": "The evidence is the diff.",
                            "refs": ["diffstat"]},
    }
    assert explain_envelope.validate_envelope(env, "auto-ruling") == []
    return {"id": f"r{n}", **env}


ROWS = [_row(n) for n in range(1, 6)]
IDS = [r["id"] for r in ROWS]


def _render(rows=ROWS, *, head=HEAD, cap=COMMENT_CAP) -> str:
    return render_rulings_comment(rows, head=head, cap=cap,
                                  html_hint=HTML_HINT)


class _Comment(HTMLParser):
    """The HTML comments and each <details> block (summary, text)."""

    def __init__(self, body: str):
        super().__init__(convert_charrefs=True)
        self.comments: list = []
        self.details: list = []
        self._depth = 0
        self._in_summary = False
        self.feed(body)
        self.close()

    def handle_comment(self, data):
        self.comments.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == "details":
            self.details.append({"attrs": attrs, "summary": "", "text": ""})
            self._depth += 1
        elif tag == "summary":
            self._in_summary = True

    def handle_endtag(self, tag):
        if tag == "details":
            self._depth -= 1
        elif tag == "summary":
            self._in_summary = False

    def handle_data(self, data):
        if self._in_summary:
            self.details[-1]["summary"] += data
        elif self._depth:
            self.details[-1]["text"] += data


def _shown(text: str) -> str:
    """What a reader sees: word joiners dropped, whitespace runs folded."""
    return " ".join(text.replace(WJ, "").split())


def _shown_lines(body: str) -> list:
    return [_shown(html.unescape(line)) for line in body.splitlines()]


def _full_ids(body: str) -> list:
    """The ids of the full <details> blocks (each ends in its hook), in order."""
    return [rid for block in _Comment(body).details for rid in IDS
            if _shown(block["text"]).endswith(ruling_hook(rid))]


def test_ruling_hook_is_the_fixed_line():
    assert ruling_hook("r1") == (
        'Your call on ruling r1: reply "agree r1" or "disagree r1: <reason>".')


@pytest.mark.parametrize("rid", ["r1", "r7", "r12"])
def test_hook_re_matches_both_replies_and_captures_the_id(rid):
    for reply in (f"agree {rid}", f"disagree {rid}: wrong default"):
        match = HOOK_RE.search(reply)
        assert match is not None, reply
        assert rid in match.groups()


def test_comment_cap_is_60000():
    assert COMMENT_CAP == 60000


def test_body_starts_with_the_rulings_marker():
    body = _render()
    assert explainer_marker.is_explainer(body)
    parsed = explainer_marker.parse(body)
    assert parsed["kind"] == "rulings" and parsed["head"] == HEAD


def test_marker_text_in_ruling_text_adds_no_second_marker():
    row = _row(1)
    row["ste_summary"]["text"] = explainer_marker.marker("rulings", "s", HEAD)
    body = _render([row])
    assert body.count(explainer_marker.MARKER_PREFIX) == 1
    assert len(_Comment(body).comments) == 1


def test_one_details_per_ruling_ending_in_its_hook():
    body = _render()
    blocks = _Comment(body).details
    assert len(blocks) == len(ROWS)
    assert _full_ids(body) == IDS
    for block, row in zip(blocks, ROWS):
        assert block["attrs"] == []
        assert row["ste_summary"]["text"] in _shown(block["summary"])
        text = _shown(block["text"])
        assert text.endswith(ruling_hook(row["id"]))
        for sec in row["sections"]:
            for item in sec["items"]:
                assert item["text"] in text


def _collapsed_line(body: str, row: dict) -> str:
    """The one body line ending in the ruling's hook."""
    hook = ruling_hook(row["id"])
    lines = [ln for ln in _shown_lines(body) if ln.endswith(hook)]
    assert len(lines) == 1, (row["id"], lines)
    return lines[0]


def test_small_cap_collapses_the_oldest_first():
    cap = len(_render()) - 1
    body = _render(cap=cap)
    assert len(body) <= cap
    full = _full_ids(body)
    collapsed = [rid for rid in IDS if rid not in full]
    assert collapsed and full, (collapsed, full)
    assert IDS == collapsed + full  # the oldest collapse first
    for row in ROWS:
        line = _collapsed_line(body, row)
        if row["id"] in collapsed:
            assert row["ste_summary"]["text"] in line
    assert HTML_HINT in _shown(html.unescape(body))


def test_tiny_cap_collapses_every_ruling_to_one_headline_with_its_hook():
    body = _render(cap=1)
    assert _Comment(body).details == []
    for row in ROWS:
        line = _collapsed_line(body, row)
        assert row["ste_summary"]["text"] in line
    assert HTML_HINT in _shown(html.unescape(body))
    assert explainer_marker.parse(body)["kind"] == "rulings"


def test_details_injection_and_mentions_in_ruling_text_stay_inert():
    row = _row(1)
    hostile = "</details><details open><summary>x</summary> cc @octocat"
    row["ste_summary"]["text"] = hostile
    row["sections"][0]["items"][0]["text"] = hostile
    body = _render([row, _row(2)])
    blocks = _Comment(body).details
    assert len(blocks) == 2
    assert all(b["attrs"] == [] for b in blocks)
    assert hostile in _shown(blocks[0]["summary"])
    assert "@octocat" not in body


def _spoofed(n: int) -> dict:
    row = _row(n)
    row["ste_summary"]["text"] = DIGEST_SPOOF
    for sec in row["sections"]:
        sec["title"] = DIGEST_SPOOF
        sec["items"] = [{"text": s, "refs": [s]}
                        for s in (DIGEST_SPOOF, DEGRADED_SPOOF, SHORT_SPOOF)]
    row["confidence_note"] = {"text": DEGRADED_SPOOF, "refs": [SHORT_SPOOF]}
    return row


@pytest.mark.parametrize("cap", [COMMENT_CAP, 1])
def test_ruling_text_never_matches_a_review_proof_digest(cap):
    assert _DIGEST_HEAD_RE.search(DIGEST_SPOOF).group(1) == SHA40
    assert _DEGRADED_RE.search(DEGRADED_SPOOF)
    body = render_rulings_comment([_spoofed(1), _spoofed(2)], head=SHA40,
                                  cap=cap, html_hint=HTML_HINT)
    for line in body.splitlines() + [body]:
        assert _DIGEST_HEAD_RE.search(line) is None, line
        assert _DEGRADED_RE.search(line) is None, line
    assert DIGEST_SPOOF in _shown(html.unescape(body))


def _pr_brief(rulings_items: list) -> dict:
    sections = [{"id": sid, "title": f"Title {sid}",
                 "items": [{"text": f"Item for {sid}.", "refs": ["diffstat"]}]}
                for sid in explain_envelope.REQUIRED_SECTIONS["pr-brief"]]
    sections[-1]["items"] = rulings_items
    env = {
        "schema": explain_envelope.SCHEMA,
        "kind": "pr-brief",
        "ste_summary": {"text": "The change adds a brief.",
                        "refs": ["diffstat"]},
        "sections": sections,
        "diagram_specs": [],
        "confidence_note": {"text": "The evidence is the diff.",
                            "refs": ["diffstat"]},
    }
    assert explain_envelope.validate_envelope(env, "pr-brief") == []
    return env


def test_pr_brief_rulings_without_you_items_carry_their_own_hook():
    items = [{"text": "Fable kept the default cap.", "refs": ["ruling:r2"]},
             {"text": "Fable picked the sonnet drafter.",
              "refs": ["diffstat", "ruling:r1"]}]
    env = _pr_brief(items)
    body = render_markdown(
        env, head=HEAD, marker=explainer_marker.marker("pr-brief", "s", HEAD))
    title = env["sections"][-1]["title"]
    [block] = [b for b in _Comment(body).details
               if _shown(b["summary"]) == title]
    text = _shown(block["text"])
    order = [text.index(items[0]["text"]), text.index(ruling_hook("r2")),
             text.index(items[1]["text"]), text.index(ruling_hook("r1"))]
    assert order == sorted(order)
    assert text.count(ruling_hook("r1")) == text.count(ruling_hook("r2")) == 1
