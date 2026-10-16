"""test_explain_diagram_note.py — an omitted diagram leaves a note in the comment.

Covers explainer-diagram-fidelity plan Task 1.6 (operator ruling, Part 2:
"Omitted diagram leaves a note"): when finalize drops a diagram, the
envelope carries `diagram_notes`, one "diagram omitted: <reason>" line per
dropped diagram, built from the gate's `diagram_reasons` and the
explain_diagram_check.REASONS sentence (the bad-shape sentence when the gate
gave no reason). Kept diagrams add no note, and a drafter-supplied
`diagram_notes` is never trusted. render_markdown prints each note as a
"> diagram omitted: ..." line after the summary (and in each ruling block);
render_html prints it as <p class="diagram-note">; an envelope with no
`diagram_notes` key renders as before.

Envelopes and requests come from the neighbouring degrade test builders.
Assertions are on the notes list, the REASONS sentences the check module
owns, and the parsed lines of the comment (skills/_shared/test-fragility.md);
no other prose is pinned.
"""
import copy
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_degrade as ed  # noqa: E402
import explain_diagram_check as edc  # noqa: E402
import explain_gate as eg  # noqa: E402
from explain_html import render_html  # noqa: E402
from explain_markdown import render_markdown, render_rulings_comment  # noqa: E402
from test_explain_degrade import GOOD_DIAGRAM, _envelope, _request  # noqa: E402

NO_EDGE_FLOW = {"kind": "flow", "nodes": ["a", "b"]}
NOTE_PREFIX = "diagram omitted: "
HEAD = "abc1234"
MARKER = "<!-- tp-explainer: test -->"


def _final(specs, gate=None):
    """finalize of the shared envelope carrying ``specs``, with the real gate."""
    env = _envelope()
    env["diagram_specs"] = specs
    request = _request()
    return ed.finalize(env, request, gate or eg.run_gates(env, request))


def _md_lines(env):
    return render_markdown(env, head=HEAD, marker=MARKER).splitlines()


def _note_lines(lines):
    return [ln for ln in lines if ln.startswith("> " + NOTE_PREFIX)]


# ---------------------------------------------------------------------------
# finalize: the notes
# ---------------------------------------------------------------------------

def test_a_dropped_diagram_adds_its_reason_note():
    out = _final([copy.deepcopy(GOOD_DIAGRAM), dict(NO_EDGE_FLOW)])
    assert out["diagram_specs"] == [GOOD_DIAGRAM]
    assert out["diagram_notes"] == [NOTE_PREFIX + edc.REASONS["no-edges"]]


def test_kept_diagrams_add_no_note():
    out = _final([copy.deepcopy(GOOD_DIAGRAM)])
    assert out["diagram_specs"] == [GOOD_DIAGRAM]
    assert out["diagram_notes"] == []


def test_no_diagrams_at_all_adds_no_note():
    assert _final([])["diagram_notes"] == []


def test_each_dropped_diagram_gets_its_own_note_in_index_order():
    orphan = {"kind": "flow", "nodes": ["a", "b", "c"], "edges": [["a", "b"]]}
    out = _final([dict(NO_EDGE_FLOW), copy.deepcopy(GOOD_DIAGRAM), orphan])
    assert out["diagram_specs"] == [GOOD_DIAGRAM]
    assert out["diagram_notes"] == [NOTE_PREFIX + edc.REASONS["no-edges"],
                                    NOTE_PREFIX + edc.REASONS["orphan-node"]]


def test_a_missing_reason_falls_back_to_the_bad_shape_sentence():
    env = _envelope()
    env["diagram_specs"] = [dict(NO_EDGE_FLOW)]
    for gate in ({"diagrams_ok": [False]},
                 {"diagrams_ok": [False], "diagram_reasons": []},
                 {"diagrams_ok": [False], "diagram_reasons": [None]}):
        out = ed.finalize(env, _request(), gate)
        assert out["diagram_specs"] == []
        assert out["diagram_notes"] == [NOTE_PREFIX + edc.REASONS["bad-shape"]]


def test_a_drafter_supplied_note_is_not_trusted():
    env = _envelope()
    env["diagram_notes"] = ["diagram omitted: the drafter says so"]
    request = _request()
    out = ed.finalize(env, request, eg.run_gates(env, request))
    assert out["diagram_notes"] == []


def test_finalize_with_notes_does_not_mutate_its_input():
    env = _envelope()
    env["diagram_specs"] = [dict(NO_EDGE_FLOW)]
    before = copy.deepcopy(env)
    request = _request()
    ed.finalize(env, request, eg.run_gates(env, request))
    assert env == before


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------

def test_markdown_prints_each_note_as_a_quote_line_after_the_summary():
    out = _final([dict(NO_EDGE_FLOW), copy.deepcopy(GOOD_DIAGRAM)])
    lines = _md_lines(out)
    notes = _note_lines(lines)
    assert len(notes) == 1
    assert edc.REASONS["no-edges"] in notes[0]
    summary_at = next(i for i, ln in enumerate(lines)
                      if out["ste_summary"]["text"] in ln)
    assert lines.index(notes[0]) > summary_at
    assert lines.index(notes[0]) < next(i for i, ln in enumerate(lines)
                                        if ln.startswith("<details>"))


def test_markdown_prints_no_note_line_when_no_diagram_was_dropped():
    out = _final([copy.deepcopy(GOOD_DIAGRAM)])
    assert _note_lines(_md_lines(out)) == []


def test_markdown_escapes_the_note_text():
    out = _final([copy.deepcopy(GOOD_DIAGRAM)])
    out["diagram_notes"] = [NOTE_PREFIX + "<b>bold</b> @octocat"]
    notes = _note_lines(_md_lines(out))
    assert len(notes) == 1
    assert "<b>" not in notes[0]
    assert "&lt;b&gt;" in notes[0]
    assert "@octocat" not in notes[0]


def test_markdown_without_the_key_renders_as_before():
    env = _envelope()
    assert "diagram_notes" not in env
    assert _note_lines(_md_lines(env)) == []
    assert NOTE_PREFIX not in render_markdown(env, head=HEAD, marker=MARKER)


def test_a_ruling_row_prints_its_notes_in_its_block():
    row = {"id": "r1", **_final([dict(NO_EDGE_FLOW)])}
    body = render_rulings_comment([row], head=HEAD, html_hint="/x/r.html")
    notes = _note_lines(body.splitlines())
    assert len(notes) == 1
    assert edc.REASONS["no-edges"] in notes[0]
    assert body.index(notes[0]) < body.index("</details>")


def test_a_ruling_row_without_the_key_prints_no_note():
    row = {"id": "r1", **_envelope()}
    body = render_rulings_comment([row], head=HEAD, html_hint="/x/r.html")
    assert NOTE_PREFIX not in body


# ---------------------------------------------------------------------------
# render_html
# ---------------------------------------------------------------------------

def test_html_prints_each_note_as_a_diagram_note_paragraph():
    out = _final([dict(NO_EDGE_FLOW), copy.deepcopy(GOOD_DIAGRAM)])
    page = render_html(out, head=HEAD, title="T")
    assert page.count('<p class="diagram-note">') == 1
    assert NOTE_PREFIX + edc.REASONS["no-edges"] in page


def test_html_escapes_the_note_text():
    out = _final([copy.deepcopy(GOOD_DIAGRAM)])
    out["diagram_notes"] = [NOTE_PREFIX + "<script>x</script> & more"]
    page = render_html(out, head=HEAD, title="T")
    assert '<p class="diagram-note">' in page
    assert "<script>x" not in page
    assert "&lt;script&gt;" in page


def test_html_prints_no_note_when_no_diagram_was_dropped():
    page = render_html(_final([copy.deepcopy(GOOD_DIAGRAM)]), head=HEAD,
                       title="T")
    assert '<p class="diagram-note">' not in page


def test_html_without_the_key_renders_as_before():
    env = _envelope()
    assert "diagram_notes" not in env
    page = render_html(env, head=HEAD, title="T")
    assert '<p class="diagram-note">' not in page
    assert NOTE_PREFIX not in page
