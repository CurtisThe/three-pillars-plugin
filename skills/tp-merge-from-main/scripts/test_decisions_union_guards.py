"""`decisions_union.union_decisions` guards: CRLF, line separators and open blocks.

Spec: basesync-three-way-verifier detailed-design.md Interfaces (`decisions_union.union_decisions`).
Three guards keep the file-level union from producing text the line-based verifier cannot vouch for:
any `\\r` anywhere returns None (CRLF input stays on the diff3 path); exotic line separators stay
inside their lines so the base prefix is byte-equal; and a heading tail is never appended after an
open fence (an odd run of ``` or ~~~ lines), an unclosed `<!--`, or more `<details>`/`<div>`/`<pre>`/
`<table>` openers than closers. Inputs are small hand-built documents and every expectation is traced
by hand from the spec (skills/_shared/test-fragility.md); none reads the module source.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from decisions_union import union_decisions  # noqa: E402

BASE = "# Decisions\n\n### [tp-plan] first\n**Decided**: yes\n"
HEAD_O = "### [tp-ours] ours entry\n**Decided**: a\n"
HEAD_T = "### [tp-theirs] theirs entry\n**Decided**: b\n"


def ours_then_theirs(body_o, base=BASE):
    """ours = a heading tail whose body is `body_o`; theirs = a plain heading tail."""
    head = "### [tp-ours] ours entry\n" + body_o
    return base + "\n" + head, base + "\n" + HEAD_T, head


# ---- CRLF -----------------------------------------------------------------------------------------

def test_a_carriage_return_in_any_input_returns_none():
    crlf = BASE.replace("\n", "\r\n")
    assert union_decisions(crlf, crlf + "\r\n" + HEAD_O, crlf + "\r\n" + HEAD_T) is None
    assert union_decisions(BASE, BASE + "\n" + HEAD_O.replace("\n", "\r\n"), BASE + HEAD_T) is None
    assert union_decisions(BASE, BASE + "\n" + HEAD_O, BASE + HEAD_T.replace("\n", "\r\n")) is None


def test_a_lone_carriage_return_in_the_base_returns_none():
    base = "# Decisions\n\n### [tp-plan] first\n**Decided**: yes\rmore\n"
    assert union_decisions(base, base + "\n" + HEAD_O, base + HEAD_T) is None


def test_the_same_inputs_without_a_carriage_return_still_union():
    assert union_decisions(BASE, BASE + "\n" + HEAD_O, BASE + HEAD_T) == BASE + "\n" + HEAD_O + "\n" + HEAD_T


# ---- exotic line separators -----------------------------------------------------------------------

def test_a_base_with_u2028_and_form_feed_is_kept_byte_equal_as_the_output_prefix():
    base = "### [tp-plan] first\nsplit here\x0cand\x1c\x1d\x1e there end\u0085\n"
    ours, theirs = base + "\n" + HEAD_O, base + HEAD_T
    got = union_decisions(base, ours, theirs)
    assert got is not None
    assert got.encode().startswith(base.encode())
    assert got == base + "\n" + HEAD_O + "\n" + HEAD_T


def test_a_tail_with_u2028_and_form_feed_is_kept_verbatim():
    tail = "### [tp-ours] ours entry\n**Decided**: a\x0cb\n"
    got = union_decisions(BASE, BASE + "\n" + tail, BASE + HEAD_T)
    assert got == BASE + "\n" + tail + "\n" + HEAD_T


# ---- open fences ----------------------------------------------------------------------------------

@pytest.mark.parametrize("fence", ["```", "~~~", "   ```", "```python", "~~~~"])
def test_an_unclosed_fence_in_the_first_tail_blocks_the_second_tail(fence):
    ours, theirs, head = ours_then_theirs(f"{fence}\ncode\n")
    assert union_decisions(BASE, ours, theirs) is None
    # Swapped, the open tail is LAST: nothing is appended after it, so the guard lets it through.
    assert union_decisions(BASE, theirs, ours) == BASE + "\n" + HEAD_T + "\n" + head


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_an_unclosed_fence_in_a_continuation_blocks_the_heading_tail(fence):
    cont, other = BASE + f"{fence}\ncode\n", BASE + "\n" + HEAD_T
    assert union_decisions(BASE, cont, other) is None
    assert union_decisions(BASE, other, cont) is None


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_the_same_tails_with_the_fence_closed_union(fence):
    ours, theirs, head = ours_then_theirs(f"{fence}\ncode\n{fence}\n")
    want = BASE + "\n" + head + "\n" + HEAD_T
    assert union_decisions(BASE, ours, theirs) == want


def test_a_fence_open_in_the_base_blocks_the_first_heading_tail():
    base = "### [tp-plan] first\n```\nstill open\n"
    assert union_decisions(base, base + "\n" + HEAD_O, base + HEAD_T) is None


def test_a_mixed_fence_pair_that_is_not_closed_blocks_the_second_tail():
    ours, theirs, _ = ours_then_theirs("```\n~~~\n")
    assert union_decisions(BASE, ours, theirs) is None


def test_a_four_space_indented_fence_marker_is_not_a_fence():
    ours, theirs, head = ours_then_theirs("    ```\nindented code\n")
    assert union_decisions(BASE, ours, theirs) == BASE + "\n" + head + "\n" + HEAD_T


def test_an_inline_triple_backtick_is_not_a_fence_line():
    ours, theirs, head = ours_then_theirs("use a ``` fence here\n")
    assert union_decisions(BASE, ours, theirs) == BASE + "\n" + head + "\n" + HEAD_T


# ---- open HTML blocks -----------------------------------------------------------------------------

@pytest.mark.parametrize("opener", ["<!-- note", "<details>", "<div>", "<pre>", "<table>"])
def test_an_open_html_block_in_the_first_tail_blocks_the_second_tail(opener):
    ours, theirs, head = ours_then_theirs(f"{opener}\nbody\n")
    assert union_decisions(BASE, ours, theirs) is None
    # Swapped, the open tail is LAST: nothing is appended after it, so the guard lets it through.
    assert union_decisions(BASE, theirs, ours) == BASE + "\n" + HEAD_T + "\n" + head


CLOSED = [
    ("<!-- note", "-->"),
    ("<details>", "</details>"),
    ("<div>", "</div>"),
    ("<pre>", "</pre>"),
    ("<table>", "</table>"),
]


@pytest.mark.parametrize("opener,closer", CLOSED)
def test_the_same_tails_with_the_html_block_closed_union(opener, closer):
    ours, theirs, head = ours_then_theirs(f"{opener}\nbody\n{closer}\n")
    assert union_decisions(BASE, ours, theirs) == BASE + "\n" + head + "\n" + HEAD_T


@pytest.mark.parametrize("opener", ["<details>", "<div>", "<pre>", "<table>"])
def test_an_open_html_block_in_a_continuation_blocks_the_heading_tail(opener):
    cont, other = BASE + f"{opener}\nbody\n", BASE + "\n" + HEAD_T
    assert union_decisions(BASE, cont, other) is None
    assert union_decisions(BASE, other, cont) is None


def test_a_closer_of_a_different_tag_does_not_close_the_opener():
    ours, theirs, _ = ours_then_theirs("<div>\nbody\n</pre>\n")
    assert union_decisions(BASE, ours, theirs) is None


def test_html_tags_match_case_insensitively():
    ours, theirs, _ = ours_then_theirs("<DIV>\nbody\n")
    assert union_decisions(BASE, ours, theirs) is None
    ours, theirs, head = ours_then_theirs("<Details>\nbody\n</DETAILS>\n")
    assert union_decisions(BASE, ours, theirs) == BASE + "\n" + head + "\n" + HEAD_T


def test_an_earlier_closed_comment_does_not_hide_a_later_unclosed_one():
    ours, theirs, _ = ours_then_theirs("<!-- one -->\n<!-- two\n")
    assert union_decisions(BASE, ours, theirs) is None


def test_a_tag_that_only_starts_with_an_opener_name_is_not_an_opener():
    ours, theirs, head = ours_then_theirs("<preview>\n<divider>\n<tablet>\n")
    assert union_decisions(BASE, ours, theirs) == BASE + "\n" + head + "\n" + HEAD_T


def test_a_continuation_then_a_heading_tail_after_a_clean_base_still_unions():
    cont, other = BASE + "**Outcome**: shipped\n", BASE + "\n" + HEAD_T
    assert union_decisions(BASE, cont, other) == BASE + "**Outcome**: shipped\n" + "\n" + HEAD_T
