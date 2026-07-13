"""Real-format (bold-lead-bullet) + wrapped-entry RESOLVER fixtures for the log-entry-insertion
class. Split from test_resolve.py to keep that module lean (file-size soft-warn is 300 lines).

These prove the RESOLVER — not just the classifier — keeps both concurrent insertions VERBATIM
(zero-drop) for the two real living-doc log shapes: dated `## History` bullets and name-keyed
`### Recent completions` bullets, including entries that WRAP across a continuation body. They also
pin the tightness backstop (a non-log prose insertion defers at the resolve layer)."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from resolve import resolve_file, RESOLVED, DEFER  # noqa: E402


def _diff3_empty_base(ours, theirs, pre=""):
    # Real `git merge-file --diff3` minimizes a concurrent insertion to an EMPTY base (no line
    # between `||||||| base` and `=======`) — the shape a live newest-first-log prepend produces.
    block = "<<<<<<< ours\n" + ours + "\n||||||| base\n=======\n" + theirs + "\n>>>>>>> theirs"
    return (pre + "\n" + block) if pre else block


def test_name_keyed_log_resolves_keep_both_zero_drop():
    # product_roadmap.md `### Recent completions` shape: name-keyed `- **`slug`** — …` bullets.
    t = _diff3_empty_base("- **`design-a`** — Implemented (2026-07-04).",
                          "- **`design-b`** — Done — archived (2026-07-05).",
                          pre="### Recent completions")
    status, lines, results = resolve_file(t)
    assert status == RESOLVED and results[0].label == "log-entry-insertion"
    text = "\n".join(lines)
    assert "`design-a`" in text and "`design-b`" in text     # zero-drop keep-both
    assert "<<<<<<<" not in text


def test_wrapped_entry_resolves_preserving_continuation_body_verbatim():
    # A WRAPPED entry (bullet + blank + indented body) must survive keep-both with its body intact —
    # guards the correctness point that continuation lines are carried, not dropped.
    ours = "- **2026-07-04** — decision OURS\n\n  rationale ours line"
    theirs = "- **2026-07-05** — decision THEIRS\n\n  rationale theirs line"
    t = _diff3_empty_base(ours, theirs, pre="## History")
    status, lines, results = resolve_file(t)
    assert status == RESOLVED and results[0].label == "log-entry-insertion"
    text = "\n".join(lines)
    for needle in ("decision OURS", "rationale ours line", "decision THEIRS", "rationale theirs line"):
        assert needle in text                                 # every wrapped-body line preserved
    assert "<<<<<<<" not in text


def test_nonlog_prose_insertion_defers_at_resolve_layer():
    # Tightness backstop at the resolve layer: an insertion that is not clean log bullets defers to
    # a human even with an empty base (the bullet-block restriction, not just the empty-base gate).
    t = _diff3_empty_base("- **2026-07-04** — real entry",
                          "an arbitrary concurrent prose paragraph, not a log entry", pre="## History")
    status, lines, _ = resolve_file(t)
    assert status == DEFER
    assert "<<<<<<<" in "\n".join(lines)                      # markers preserved for the human
