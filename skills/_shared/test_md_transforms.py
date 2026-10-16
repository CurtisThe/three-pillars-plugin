"""test_md_transforms.py — `blocks`, `reflow`, `reorder_sections` (design:
fragile-test-prevention, detailed-design-stages.md Part C3).

Example-based cases pin `blocks`'s classification of each block kind (a heading
inside a fence stays code). Metamorphic cases, over a small corpus of example
docs (plus Hypothesis-generated docs when `hypothesis` is importable), check
that each transform changes only what it claims to change: `reflow` touches
paragraph words only and is idempotent at a fixed width; `reorder_sections`
leaves the multiset of non-paragraph blocks and the bag of paragraph words
unchanged.
"""
from __future__ import annotations

from collections import Counter

import pytest

import md_transforms as mt

try:
    from hypothesis import given, strategies as st

    HAVE_HYPOTHESIS = True
except ImportError:
    HAVE_HYPOTHESIS = False


# --- blocks(): example-based classification ---------------------------------------

def test_blocks_splits_frontmatter():
    text = "---\ntitle: x\n---\nbody\n"
    kinds = [b["kind"] for b in mt.blocks(text)]
    assert kinds[0] == "frontmatter"
    assert "paragraph" in kinds


def test_blocks_heading_inside_fence_stays_code():
    text = "```\n# not a heading\n```"
    bl = mt.blocks(text)
    assert [b["kind"] for b in bl] == ["fenced_code"]
    assert "# not a heading" in bl[0]["lines"]


def test_blocks_classifies_each_kind():
    text = (
        "# Heading\n"
        "\n"
        "A paragraph.\n"
        "\n"
        "- a list item\n"
        "\n"
        "| a | b |\n"
        "| - | - |\n"
        "\n"
        "> a quote\n"
        "\n"
        "<div>html</div>\n"
    )
    kinds = [b["kind"] for b in mt.blocks(text)]
    for expected in (
        "atx_heading", "paragraph", "list_item", "table", "blockquote", "html", "blank",
    ):
        assert expected in kinds, (expected, kinds)


def test_blocks_reconstructs_text_exactly():
    for text in (
        "---\nk: v\n---\n# T\n\nbody\n",
        "no frontmatter\njust text",
        "trailing blank\n\n",
    ):
        rebuilt = "\n".join(line for b in mt.blocks(text) for line in b["lines"])
        assert rebuilt == text


# --- example docs used by the metamorphic checks below -----------------------------

_DOC_A = (
    "---\n"
    "title: Example\n"
    "---\n"
    "# Title\n"
    "\n"
    "Preamble paragraph before any second-level section, with enough words in "
    "it to be worth wrapping across more than one line when reflowed.\n"
    "\n"
    "## First\n"
    "\n"
    "First section paragraph one has quite a few words in it so that reflow "
    "actually has something to do when it re-wraps this text at a new width.\n"
    "\n"
    "```\n"
    "# not a heading, code stays byte-identical\n"
    "some code\n"
    "```\n"
    "\n"
    "- a\n"
    "- b\n"
    "\n"
    "## Second\n"
    "\n"
    "Second section paragraph, also long enough to wrap differently under a "
    "narrower or wider width than the paragraph above it in the first section.\n"
    "\n"
    "> a blockquote line\n"
)

_DOC_B = (
    "# Only Title\n"
    "\n"
    "Just one top-level heading and no siblings at any deeper level either, so "
    "reorder_sections has nothing to reverse and returns the text unchanged.\n"
)

_EXAMPLE_DOCS = [_DOC_A, _DOC_B]


def _widest_line(text: str) -> int:
    return max((len(line) for line in text.split("\n")), default=0)


def _non_paragraph_multiset(text: str) -> Counter:
    return Counter(
        (b["kind"], tuple(b["lines"]))
        for b in mt.blocks(text)
        if b["kind"] != "paragraph"
    )


def _paragraph_words(text: str) -> list[str]:
    words: list[str] = []
    for b in mt.blocks(text):
        if b["kind"] == "paragraph":
            words.extend(" ".join(b["lines"]).split())
    return words


# --- reflow: metamorphic properties --------------------------------------------

@pytest.mark.parametrize("text", _EXAMPLE_DOCS)
def test_reflow_touches_only_paragraph_blocks(text):
    width = min(_widest_line(text) + 17, 40)
    reflowed = mt.reflow(text, width)
    assert _non_paragraph_multiset(reflowed) == _non_paragraph_multiset(text)


@pytest.mark.parametrize("text", _EXAMPLE_DOCS)
def test_reflow_preserves_paragraph_words_in_order(text):
    width = min(_widest_line(text) + 17, 40)
    reflowed = mt.reflow(text, width)
    assert _paragraph_words(reflowed) == _paragraph_words(text)


@pytest.mark.parametrize("text", _EXAMPLE_DOCS)
def test_reflow_is_idempotent_at_a_fixed_width(text):
    width = min(_widest_line(text) + 17, 40)
    once = mt.reflow(text, width)
    twice = mt.reflow(once, width)
    assert twice == once


@pytest.mark.parametrize("text", _EXAMPLE_DOCS)
def test_reflow_changes_wrapping_at_a_narrower_width(text):
    # Sanity check that reflow actually does something on a doc with a
    # wrappable paragraph, so the invariance checks above aren't vacuous.
    reflowed = mt.reflow(text, 20)
    assert reflowed != text


# --- reorder_sections: metamorphic properties -----------------------------------

def test_reorder_sections_reverses_second_level_siblings():
    reordered = mt.reorder_sections(_DOC_A)
    first_idx = reordered.index("## First")
    second_idx = reordered.index("## Second")
    assert second_idx < first_idx
    # frontmatter + preamble stay first
    assert reordered.index("# Title") < second_idx
    assert reordered.startswith("---\n")


def test_reorder_sections_no_op_with_no_sibling_level():
    assert mt.reorder_sections(_DOC_B) == _DOC_B


@pytest.mark.parametrize("text", _EXAMPLE_DOCS)
def test_reorder_sections_keeps_non_paragraph_multiset(text):
    reordered = mt.reorder_sections(text)
    assert _non_paragraph_multiset(reordered) == _non_paragraph_multiset(text)


@pytest.mark.parametrize("text", _EXAMPLE_DOCS)
def test_reorder_sections_keeps_paragraph_word_bag(text):
    reordered = mt.reorder_sections(text)
    assert Counter(_paragraph_words(reordered)) == Counter(_paragraph_words(text))


def test_reorder_sections_ignores_fenced_headings():
    text = "## A\n\nbody a\n\n```\n## fenced, not a heading\n```\n\n## B\n\nbody b\n"
    reordered = mt.reorder_sections(text)
    assert reordered.index("## B") < reordered.index("## A")
    assert "## fenced, not a heading" in reordered


# --- Hypothesis-generated docs, when importable ---------------------------------

if HAVE_HYPOTHESIS:
    _word = st.text(alphabet="abcdefghij", min_size=1, max_size=8)
    _paragraph_doc = st.lists(_word, min_size=5, max_size=40).map(
        lambda words: "# T\n\n" + " ".join(words) + "\n"
    )

    @given(_paragraph_doc)
    def test_hypothesis_reflow_preserves_paragraph_words(text):
        width = min(_widest_line(text) + 17, 40)
        reflowed = mt.reflow(text, width)
        assert _paragraph_words(reflowed) == _paragraph_words(text)

    @given(_paragraph_doc)
    def test_hypothesis_reflow_idempotent(text):
        width = min(_widest_line(text) + 17, 40)
        once = mt.reflow(text, width)
        twice = mt.reflow(once, width)
        assert twice == once
