"""`verify_three_way.occurrences`: per-occurrence atoms, place keys and section bounds.

Spec: basesync-three-way-verifier detailed-design.md, Interfaces (`occurrences`). Every test goes
through `occurrences()` and states the span it expects by hand-tracing the input lines; nothing
reads the module's source. The multiset property is checked on generated line mixes (always) and
on every tracked `.md` (skipped outside a checkout). Rule: skills/_shared/test-fragility.md.
"""
import os
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
from task_scope import _git_env as clean_git_env  # noqa: E402  # shipped scrub; git_env is dev-only
from verify_atoms import atoms  # noqa: E402
from verify_three_way import Occ, occurrences  # noqa: E402

LINE_KINDS = ("entry", "heading-entry", "row", "log", "slug-row")
ROOT = Path(__file__).resolve().parents[3]


def doc(*lines):
    return "\n".join(lines) + "\n"


def got(*lines):
    """The occurrences of the doc made of `lines`, as a set (no example repeats a whole Occ)."""
    return set(occurrences(doc(*lines)))


def decision_sig(*block):
    """The spec's definition: the `decision-entry` key of `atoms(block)`."""
    return [s for k, s in atoms("\n".join(block)) if k == "decision-entry"][0]


# --- examples from the Interfaces section --------------------------------------------------

def test_an_entry_section_runs_to_the_line_before_the_next_heading():
    lines = ["# Known Issues",    # 0
             "",                  # 1
             "## Medium",         # 2
             "",                  # 3
             "### L139: t",       # 4
             "body a",            # 5
             "#### sub heading",  # 6  (four hashes: body, not a boundary)
             "body b",            # 7
             "",                  # 8  (trailing blank, trimmed)
             "### L140: u",       # 9
             "tail"]              # 10
    assert got(*lines) == {Occ("entry", "t", "L139", 4, 8), Occ("entry", "u", "L140", 9, 11)}


def test_a_heading_entry_section_is_bounded_like_an_entry_and_trailing_blanks_are_trimmed():
    lines = ["## Resolved",                       # 0
             "### M44 (RESOLVED 2026-09-30): t",  # 1
             "closed body",                       # 2
             "",                                  # 3
             "",                                  # 4
             "## History",                        # 5
             "- **2026-07-01** — x"]              # 6
    assert got(*lines) == {Occ("heading-entry", "M44|t", "M44", 1, 3),
                           Occ("log", "2026-07-01 — x", "2026-07-01", 6, 7)}


def test_the_last_section_runs_to_eof_with_trailing_blank_lines_trimmed():
    text = "### L1: a\nbody\n\n\n\n"                # lines: 0 heading, 1 body, 2-4 blank
    assert set(occurrences(text)) == {Occ("entry", "a", "L1", 0, 2)}


def test_entry_and_heading_entry_share_one_key_namespace():
    lines = ["### M44: a",           # 0
             "### M44 (OPEN): b"]    # 1
    assert got(*lines) == {Occ("entry", "a", "M44", 0, 1),
                           Occ("heading-entry", "M44|b", "M44", 1, 2)}


def test_a_placeholder_and_a_backtick_slug_heading_key_by_the_placeholder_and_the_slug():
    lines = ["### M-new-x: draft",                   # 0
             "body",                                 # 1
             "### `slug` (2026-09-29) archived",     # 2
             "body"]                                 # 3
    assert got(*lines) == {Occ("heading-entry", "M-new-x|draft", "M-new-x", 0, 2),
                           Occ("heading-entry", "`slug`|archived", "`slug`", 2, 4)}


def test_a_row_is_one_line_keyed_by_its_id_and_header_rows_are_no_atom():
    lines = ["| ID | Name | Note |",    # 0
             "|----|------|------|",    # 1
             "| D1 | alpha | x |",      # 2
             "| D2 | beta | y |"]      # 3
    assert got(*lines) == {Occ("row", "alpha", "D1", 2, 3), Occ("row", "beta", "D2", 3, 4)}


def test_a_log_bullet_is_one_line_keyed_by_its_bold_lead():
    lines = ["## History",               # 0
             "",                         # 1
             "- **2026-07-01** — x",     # 2
             "- **`slug`** — y"]         # 3
    assert got(*lines) == {Occ("log", "2026-07-01 — x", "2026-07-01", 2, 3),
                           Occ("log", "slug — y", "`slug`", 3, 4)}


def test_rows_and_logs_under_an_entry_heading_are_part_of_its_section_and_still_their_own_atoms():
    lines = ["### L1: a",                # 0
             "| D1 | alpha | x |",       # 1
             "- **2026-07-01** — x",      # 2
             "prose",                     # 3
             "",                          # 4  (trimmed)
             "## Next"]                   # 5
    assert got(*lines) == {Occ("entry", "a", "L1", 0, 4), Occ("row", "alpha", "D1", 1, 2),
                           Occ("log", "2026-07-01 — x", "2026-07-01", 2, 3)}


def test_a_decision_block_runs_to_the_next_decision_heading_and_other_headings_are_body():
    lines = ["# Decisions",                  # 0
             "",                              # 1
             "### [tp-plan] First Title",     # 2
             "body one",                      # 3
             "## Section banner",             # 4  (body: only a decision heading ends a block)
             "- **2026-07-01** — nested",     # 5  (a log atom AND part of the block)
             "",                              # 6  (trimmed)
             "### [tp-plan] Second",          # 7
             "tail"]                          # 8
    assert got(*lines) == {
        Occ("decision-entry", decision_sig(*lines[2:6]), "[tp-plan] first title", 2, 6),
        Occ("decision-entry", decision_sig(*lines[7:9]), "[tp-plan] second", 7, 9),
        Occ("log", "2026-07-01 — nested", "2026-07-01", 5, 6)}


def test_an_entry_section_ends_at_a_decision_heading():
    lines = ["### L1: a",             # 0
             "body",                   # 1
             "### [tp-plan] Alpha",    # 2
             "tail"]                   # 3
    assert got(*lines) == {Occ("entry", "a", "L1", 0, 2),
                           Occ("decision-entry", decision_sig(*lines[2:]), "[tp-plan] alpha", 2, 4)}


def test_a_heading_shaped_line_with_an_empty_signature_part_opens_no_decision_block():
    text = doc("### [tp-plan] Real", "body", "### [_] x", "more")
    assert [(o.kind, o.start, o.end) for o in occurrences(text)] == [("decision-entry", 0, 4)]


# --- multiset: a repeated signature is counted, not collapsed -------------------------------

def test_a_signature_held_twice_is_counted_twice():
    text = doc("### L1: Foo", "", "### L2: Foo", "", "| D1 | alpha | x |", "| D2 | alpha | y |", "",
               "- **2026-07-01** — x", "- **2026-07-01** — x")
    counts = Counter((o.kind, o.sig) for o in occurrences(text))
    assert counts == Counter({("entry", "foo"): 2, ("row", "alpha"): 2,
                              ("log", "2026-07-01 — x"): 2})
    assert {o.key for o in occurrences(text) if o.kind == "entry"} == {"L1", "L2"}


def test_two_identical_decision_blocks_are_two_occurrences_of_one_atom():
    text = doc("### [a] t", "body", "", "### [a] t", "body")
    counts = Counter((o.kind, o.sig) for o in occurrences(text))
    assert list(counts.values()) == [2]
    assert set(counts) == set(atoms(text))


# --- property: the multiset contract on generated mixes -------------------------------------

HEADINGS = {"# Top", "## Section", "### L1: Foo", "### L2: Foo", "### L3: Bar",
            "### M44 (OPEN): Foo", "### M-new-x: Foo", "### [tp-plan] Alpha", "### [tp-plan] Beta"}
DECISIONS = {"### [tp-plan] Alpha", "### [tp-plan] Beta"}
OTHER = ["#### Sub", "plain prose", "", "| D1 | alpha | x |", "| D2 | alpha | y |", "|---|---|",
         "- **2026-07-01** — x", "- **2026-07-02** — y"]
TEMPLATES = sorted(HEADINGS) + OTHER


def reference_counter(text):
    """The spec's multiset: per-line `atoms(line)` keys of the line kinds, plus one per decision
    block (signature from `atoms(block)`); a decision key on a lone heading line is dropped."""
    lines, heads, counts = text.splitlines(), [], Counter()
    for i, line in enumerate(lines):
        for key in atoms(line):
            if key[0] in LINE_KINDS:
                counts[key] += 1
            else:
                heads.append(i)
    for a, b in zip(heads, heads[1:] + [len(lines)]):
        counts.update(k for k in atoms("\n".join(lines[a:b])) if k[0] == "decision-entry")
    return counts


def expected_end(lines, start, stops):
    end = start + 1
    while end < len(lines) and lines[end] not in stops:
        end += 1
    while end > start + 1 and lines[end - 1] == "":
        end -= 1
    return end


@pytest.mark.parametrize("seed", range(150))
def test_generated_mixes_obey_the_multiset_and_span_contract(seed):
    rng = random.Random(seed)
    lines = [rng.choice(TEMPLATES) for _ in range(rng.randint(1, 14))]
    text = doc(*lines)
    occs = occurrences(text)
    assert Counter((o.kind, o.sig) for o in occs) == reference_counter(text)
    assert {(o.kind, o.sig) for o in occs} == set(atoms(text))
    for o in occs:
        assert 0 <= o.start < o.end <= len(lines)
        if o.kind == "decision-entry":
            assert lines[o.start] in DECISIONS
            assert o.end == expected_end(lines, o.start, DECISIONS)
            continue
        assert (o.kind, o.sig) in atoms(lines[o.start])
        if o.kind in ("entry", "heading-entry"):
            assert o.end == expected_end(lines, o.start, HEADINGS)
        else:
            assert o.end == o.start + 1


# --- property: the same contract over every tracked .md -------------------------------------

def tracked_markdown():
    run = subprocess.run(["git", "-C", str(ROOT), "ls-files", "*.md"], capture_output=True,
                         text=True, check=False, env=clean_git_env())
    if run.returncode != 0:
        pytest.skip("not a git checkout: no tracked markdown to measure")
    paths = [ROOT / p for p in run.stdout.splitlines() if (ROOT / p).is_file()]
    if not paths:
        pytest.skip("no tracked markdown files in this checkout")
    return paths


def test_the_multiset_and_key_set_contract_holds_on_every_tracked_markdown_file():
    bad = []
    for path in tracked_markdown():
        text = path.read_text(encoding="utf-8")
        occs = occurrences(text)
        same_multiset = Counter((o.kind, o.sig) for o in occs) == reference_counter(text)
        same_keys = {(o.kind, o.sig) for o in occs} == set(atoms(text))
        if not (same_multiset and same_keys):
            bad.append(str(path.relative_to(ROOT)))
    assert not bad, bad[:5]
