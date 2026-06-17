"""Number-cite NON-match (exclusion) tests for citation_scan.

The false-positive surface: PR/issue refs, keyword-less hash chains, out-of-
context decorated numbers, slugs, and sub-clause cites must NOT flag.

design: invariant-citation-coherence
"""

from __future__ import annotations

from citation_scan import find_number_cites_in_line


def _cites(line: str) -> list[int]:
    return find_number_cites_in_line(line)


# ------------------------------------------------------------------ #
# PR / issue references — no invariant keyword in context.
# ------------------------------------------------------------------ #


def test_pr_ref_excluded():
    assert _cites("PR #123 merged cleanly") == []


def test_issue_ref_excluded():
    assert _cites("see issue #45 for the bug") == []


def test_bare_hash_chain_no_keyword_excluded():
    # "#45/#46" with no invariant keyword — PR/issue chain, never flagged.
    assert _cites("backported in #45/#46 last week") == []


def test_bare_hash_number_no_keyword_excluded():
    assert _cites("ticket #34 is open") == []


def test_hash_class_out_of_context_excluded():
    # "#69-class" with no nearby invariant keyword.
    assert _cites("a #69-class outage hit prod") == []


def test_slug_not_matched():
    assert _cites("run tp-merge then tp-post-merge") == []


def test_plain_number_no_hash_no_keyword_excluded():
    assert _cites("there were 34 commits today") == []


# ------------------------------------------------------------------ #
# Adversarial: invariant keyword present but the number belongs to a PR.
# ------------------------------------------------------------------ #


def test_number_first_far_keyword_not_pulled():
    # A `#123` whose nearest "invariant" is well beyond the window must not
    # be pulled in by the number-first pass.
    line = "PR #123 touches a lot of files and also some invariant prose later"
    assert _cites(line) == []


def test_pr_ref_with_intervening_words_before_invariant_excluded():
    # `#88` is a PR ref; the keyword "invariant" follows but with intervening
    # words ("which adds the"). Adjacency NOT satisfied → must NOT flag.
    assert _cites("See PR #88 which adds the invariant checker") == []


def test_pr_ref_references_invariant_work_excluded():
    assert _cites("PR #123 references invariant work") == []


def test_issue_ref_relates_to_invariant_excluded():
    assert _cites("issue #45 relates to the invariant") == []


def test_pull_request_ref_invariant_excluded():
    assert _cites("pull request #200 covers the invariant later") == []


def test_pr_marker_directly_adjacent_still_excluded():
    # Even when `#N` is directly adjacent to the keyword, a PR/issue marker
    # immediately before `#N` makes it a reference (defense-in-depth).
    assert _cites("PR #88 invariant changes") == []
    assert _cites("issue #45 invariant work") == []


# ------------------------------------------------------------------ #
# Sub-clause cites — key on the leading integer only; no spurious flag.
# ------------------------------------------------------------------ #


def test_subclause_alone_not_flagged():
    # "33b" with no invariant keyword and no `#` — not an independent cite.
    assert _cites("the 33b sub-rule applies") == []


def test_subclause_in_invariant_context_keys_on_leading_integer():
    # "invariant 33b" — the leading integer 33 is the cite; the trailing 'b'
    # is ignored. (33 is a valid number, so this is a correct cite, not rot.)
    assert _cites("invariant 33b governs seats") == [33]


def test_bare_33_inside_33b_not_double_counted():
    # Ensure "33b" does not yield both 33 and some artifact; in invariant
    # context it is exactly [33].
    assert _cites("see invariant 33b here") == [33]


def test_subclause_hash_form_keys_on_integer():
    assert _cites("invariant #33d") == [33]
