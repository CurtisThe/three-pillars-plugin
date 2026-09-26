"""Real-format (bold-lead-bullet) + wrapped-entry RESOLVER fixtures for the log-entry-insertion
class. Split from test_resolve.py to keep that module lean (file-size soft-warn is 300 lines).

These prove the RESOLVER — not just the classifier — keeps both concurrent insertions VERBATIM
(zero-drop) for the two real living-doc log shapes: dated `## History` bullets and name-keyed
`### Recent completions` bullets, including entries that WRAP across a continuation body. They also
pin the tightness backstop (a non-log prose insertion defers at the resolve layer).

The three fixture texts now live in `conflict_fixtures.py` — ONE copy, shared with the cross-module
coverage test, so a fixture cannot be updated here and go stale there.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from conflict_fixtures import (  # noqa: E402
    NAME_KEYED_LOG,
    NONLOG_PROSE_DEFER,
    WRAPPED_DATED_LOG,
)
from resolve import DEFER, RESOLVED, resolve_file  # noqa: E402


def test_name_keyed_log_resolves_keep_both_zero_drop():
    # product_roadmap.md `### Recent completions` shape: name-keyed `- **`slug`** — …` bullets.
    status, lines, results = resolve_file(NAME_KEYED_LOG)
    assert status == RESOLVED and results[0].label == "log-entry-insertion"
    text = "\n".join(lines)
    assert "`design-a`" in text and "`design-b`" in text     # zero-drop keep-both
    assert "<<<<<<<" not in text


def test_wrapped_entry_resolves_preserving_continuation_body_verbatim():
    # A WRAPPED entry (bullet + blank + indented body) must survive keep-both with its body intact —
    # guards the correctness point that continuation lines are carried, not dropped.
    status, lines, results = resolve_file(WRAPPED_DATED_LOG)
    assert status == RESOLVED and results[0].label == "log-entry-insertion"
    text = "\n".join(lines)
    for needle in ("decision OURS", "rationale ours line", "decision THEIRS", "rationale theirs line"):
        assert needle in text                                 # every wrapped-body line preserved
    assert "<<<<<<<" not in text


def test_nonlog_prose_insertion_defers_at_resolve_layer():
    # Tightness backstop at the resolve layer: an insertion that is not clean log bullets defers to
    # a human even with an empty base (the bullet-block restriction, not just the empty-base gate).
    status, lines, _ = resolve_file(NONLOG_PROSE_DEFER)
    assert status == DEFER
    assert "<<<<<<<" in "\n".join(lines)                      # markers preserved for the human
