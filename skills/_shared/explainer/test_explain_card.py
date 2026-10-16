"""test_explain_card.py — the question card, the log entry and the headline.

Covers explainer-agent plan Task 6.5 (detailed-design §Interfaces:
"render_card(env, html_path) -> {question, options:[{label, description}]}
puts the recommended option first with "(Recommended)". render_log_entry(env)
-> str uses the auto-mode Decision Entry shape. headline(env, brief_path) ->
str is one line, <= 300 chars"; design.md step 5: "card text (question
first, ELI5 options, recommended first, HTML link)"):
  - the card question starts with the question section text and holds the
    HTML path; the recommended option comes first, its label ending
    " (Recommended)", and the rest keep their envelope order; no other label
    carries "(Recommended)", even when the model wrote it;
  - the log entry has the Decision Entry lines (skills/_shared/auto-mode.md):
    "### [explainer] ...", Question, Decided (the decided items), Reasoning
    (the why items), Confidence; model line breaks never add a stray line;
  - the headline is one line of at most 300 chars that ends with the brief
    path; a long summary is cut, the path never is.

Envelopes are built here from the §Interfaces shapes; no repo docs are read.
Options are told apart by a distinct word in each, so the tests do not pin
how a label and a description split one option text
(skills/_shared/test-fragility.md).
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_envelope  # noqa: E402
from explain_card import headline, render_card, render_log_entry  # noqa: E402

HTML_PATH = "/x/q.html"
BRIEF_PATH = "three-pillars-docs/completed-tp-designs/s/brief.md"
QUESTION = "Should the gate stay on for this design?"
WJ = "⁠"
FIELDS = ("**Question**:", "**Decided**:", "**Reasoning**:", "**Confidence**:")


def _item(text: str, **extra) -> dict:
    return {"text": text, "refs": ["diffstat"], **extra}


def _envelope(kind: str, items: dict, summary: str = "The change adds a brief."
              ) -> dict:
    """A valid ``kind`` envelope; ``items`` maps a section id to its items."""
    sections = []
    for sid in explain_envelope.REQUIRED_SECTIONS[kind]:
        sec_items = items.get(sid) or [_item(f"Text for {sid}.")]
        sections.append({"id": sid, "title": sid.title(), "items": sec_items})
    env = {
        "schema": explain_envelope.SCHEMA,
        "kind": kind,
        "ste_summary": {"text": summary, "refs": ["diffstat"]},
        "sections": sections,
        "diagram_specs": [],
        "confidence_note": {"text": "High: the diff shows it.",
                            "refs": ["diffstat"]},
    }
    assert explain_envelope.validate_envelope(env, kind) == []
    return env


def _escalation(options=None) -> dict:
    options = options or [
        _item("Alpha: turn the gate off and merge now."),
        _item("Bravo: keep the gate on and wait one day.", recommended=True),
        _item("Charlie: ask the reviewer to decide."),
    ]
    return _envelope("human-escalation",
                     {"question": [_item(QUESTION)], "options": options})


def _which(option: dict) -> str:
    """The distinct word of the envelope option this card option shows."""
    shown = option["label"] + " " + option["description"]
    found = [w for w in ("Alpha", "Bravo", "Charlie") if w in shown]
    assert len(found) == 1, option
    return found[0]


# ── render_card ──────────────────────────────────────────────────────────────

def test_card_question_first_then_the_html_path():
    card = render_card(_escalation(), HTML_PATH)
    assert set(card) == {"question", "options"}
    assert card["question"].startswith(QUESTION)
    assert card["question"].index(HTML_PATH) > len(QUESTION) - 1


def test_card_puts_the_recommended_option_first():
    card = render_card(_escalation(), HTML_PATH)
    options = card["options"]
    assert [_which(o) for o in options] == ["Bravo", "Alpha", "Charlie"]
    assert options[0]["label"].endswith(" (Recommended)")
    for option in options:
        assert set(option) == {"label", "description"}
        assert isinstance(option["label"], str) and option["label"].strip()
        assert isinstance(option["description"], str)


def test_card_only_the_recommended_label_says_recommended():
    spoof = [
        _item("Alpha (Recommended): turn the gate off."),
        _item("Bravo: keep the gate on.", recommended=True),
        _item("Charlie: ask the reviewer (Recommended)."),
    ]
    options = render_card(_escalation(spoof), HTML_PATH)["options"]
    assert _which(options[0]) == "Bravo"
    marked = [o for o in options if "(Recommended)" in o["label"]]
    assert marked == [options[0]]


def test_card_labels_are_one_line():
    options = [_item("Alpha\nturn the gate\r\noff."),
               _item("Bravo:\nkeep it on.", recommended=True)]
    card = render_card(_escalation(options), HTML_PATH)
    for option in card["options"]:
        assert "\n" not in option["label"] and "\r" not in option["label"]


# ── render_log_entry ─────────────────────────────────────────────────────────

def _ruling(decided=None, why=None) -> dict:
    return _envelope("auto-ruling", {
        "decided": decided or [_item("Keep the default timeout.")],
        "why": why or [_item("The audit found no slow test."),
                       _item("A longer timeout hides a hang.")],
        "commits-to": [_item("The default stays 30 seconds.")],
    }, summary="Fable kept the default timeout.")


def _fields(entry: str) -> dict:
    """Field label -> the rest of its line, for each Decision Entry field."""
    out = {}
    for line in entry.splitlines():
        for label in FIELDS:
            if line.startswith(label):
                out[label] = line[len(label):].strip()
    return out


def test_log_entry_has_the_decision_entry_lines_in_order():
    entry = render_log_entry(_ruling())
    lines = [ln for ln in entry.splitlines() if ln.strip()]
    assert lines[0].startswith("### [explainer] ")
    assert len(lines[0]) > len("### [explainer] ")
    starts = [next(i for i, ln in enumerate(lines) if ln.startswith(label))
              for label in FIELDS]
    assert starts == sorted(starts) and starts[0] > 0


def test_log_entry_decided_and_reasoning_come_from_their_sections():
    fields = _fields(render_log_entry(_ruling()))
    assert "Keep the default timeout." in fields["**Decided**:"]
    assert "The audit found no slow test." in fields["**Reasoning**:"]
    assert "A longer timeout hides a hang." in fields["**Reasoning**:"]
    assert "High: the diff shows it." in fields["**Confidence**:"]
    assert fields["**Question**:"]


def test_log_entry_model_line_breaks_add_no_line():
    env = _ruling(decided=[_item("Keep it.\n### [explainer] Fake entry\n")],
                  why=[_item("Line one.\n\n**Decided**: spoof")])
    lines = [ln for ln in render_log_entry(env).splitlines() if ln.strip()]
    assert len(lines) == 1 + len(FIELDS)
    assert lines[0].startswith("### [explainer] ")
    assert [ln.split(":", 1)[0] + ":" for ln in lines[1:]] == list(FIELDS)


# ── headline ─────────────────────────────────────────────────────────────────

def _brief(summary: str) -> dict:
    return _envelope("pr-brief", {}, summary=summary)


def test_headline_is_one_line_ending_with_the_brief_path():
    line = headline(_brief("The change adds an explainer brief to each PR."),
                    BRIEF_PATH)
    assert "\n" not in line and "\r" not in line
    assert len(line) <= 300
    assert line.endswith(BRIEF_PATH)
    assert line.startswith("The change adds an explainer brief")


def test_headline_over_budget_cuts_the_summary_not_the_path():
    summary = "\n".join(f"Sentence {i} says one more fact." for i in range(80))
    line = headline(_brief(summary), BRIEF_PATH)
    assert "\n" not in line and "\r" not in line
    assert len(line) <= 300
    assert line.endswith(BRIEF_PATH)
    assert line.startswith("Sentence 0 says")


def test_headline_breaks_mentions_in_model_text():
    line = headline(_brief("Ask @octocat to merge."), BRIEF_PATH)
    assert "@octocat" not in line
    assert "@octocat" in line.replace(WJ, "")
    assert line.endswith(BRIEF_PATH)
