"""Round 22, T1 — a keep-both merge emits only lines that cannot swallow the other side's entry.

`log-entry-insertion`, `decision-entry-insertion` and `append-only-log` emit ours' lines and then
theirs', and nothing checked how that join renders. A CommonMark HTML block runs until a blank
line, so when ours' inserted entry ended with a `<details>…</details>` block and theirs' block
started directly with its entry, theirs' bullet or `### [tag]` heading rendered as literal text
inside ours' HTML block. Every byte survived, so the merge was RESOLVED, verified, staged, and both
certifiers reproduced it. `line_shapes.keep_both_refusal` now admits only blank lines, the class's
entry start, and plain lines that open no HTML block, code fence, block quote, math block or link
definition, with no carriage return inside a line.

Every real-git case also runs its blobs with the allowlist lifted (`_lifted`), which reproduces
the swallowed entry, so each fails without the fix.

The design-dir decisions.md lane (basesync-three-way-verifier) unions pure appends before diff3, so
on that path the real-git keep-both guard is checked with the lane off (`_lane_off`), and a second
merge with the lane on pins the union (`_real_git_defers`).
"""
import contextlib
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import classify  # noqa: E402
from classify import DECISION_ENTRY, LOG_ENTRY, Hunk, classify_hunk  # noqa: E402
from line_shapes import keep_both_refusal, line_refusal  # noqa: E402
from test_merge_driver import git  # noqa: E402
from test_resolve_three_way import _merge  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_shared"))
import auto_safe_resolution  # noqa: E402
from auto_safe_resolution import RESOLVED, deferred_hunk_reasons, resolve_conflict_bytes  # noqa: E402
from living_doc_carry import _mechanical_resolution  # noqa: E402

ARCH = "three-pillars-docs/architecture.md"
DECISIONS = "three-pillars-docs/tp-designs/x/decisions.md"
SEMANTIC = ["generic-prose: semantic class — needs human"]
HISTORY = "# Architecture\n\n## History\n\n- **2026-01-01** — first\n"
DECISION_LOG = "# Decisions\n\n### [tp-plan] d1\n\nbody1\n\n"
DETAILS = "\n<details>\n<summary>notes</summary>\n\nlong notes\n</details>\n"


def _lifted(monkeypatch):
    """The pre-fix behaviour: no line-shape allowlist in either block predicate."""
    monkeypatch.setattr(classify, "keep_both_refusal", lambda side, entry: None)


def _lane_off():
    """The design-dir decisions.md lane switched off: its union is None, so diff3 alone decides."""
    return mock.patch.object(auto_safe_resolution, "union_decisions", lambda *a, **k: None)


def _real_git_defers(tmp_path, path, base, ours, theirs):
    """The real-git leg of "defers". On the design-dir decisions.md path the lane would union a pure
    append first, so the keep-both guard is checked with the lane off; a second merge in
    `tmp_path/lane-on` then pins the lane: the union, byte for byte, or the same deferral."""
    lane = auto_safe_resolution._DESIGN_DECISIONS_RE.fullmatch(path)
    with _lane_off() if lane else contextlib.nullcontext():
        repo, report = _merge(tmp_path, path, base, ours, theirs)
    assert path not in report.auto_resolved and report.needs_human, report.to_json()
    assert git(repo, "ls-files", "-u", "--", path).stdout.strip(), "must stay unmerged"
    if not lane:
        return
    union = auto_safe_resolution.union_decisions(base, ours, theirs)
    (tmp_path / "lane-on").mkdir()
    repo, report = _merge(tmp_path / "lane-on", path, base, ours, theirs)
    unmerged = git(repo, "ls-files", "-u", "--", path).stdout.strip()
    if union is None:
        assert path not in report.auto_resolved and unmerged, report.to_json()
    else:
        assert path in report.auto_resolved and not unmerged, report.to_json()
        assert (repo / path).read_bytes() == union.encode("utf-8")


def _defers_on_every_path(tmp_path, path, base, ours, theirs):
    assert deferred_hunk_reasons(base=base, ours=ours, theirs=theirs) == SEMANTIC
    assert resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)[0] != RESOLVED
    assert _mechanical_resolution(base, ours, theirs) is None          # the carry lane
    _real_git_defers(tmp_path, path, base, ours, theirs)


# ---- the reviewer's repros, on real git -----------------------------------------------------------

def test_t1_a_details_block_ending_ours_history_append_does_not_swallow_theirs_entry(
        tmp_path, monkeypatch):
    ours = HISTORY + "- **2026-02-10** — ours entry\n" + DETAILS
    theirs = HISTORY + "- **2026-02-11** — theirs entry\n  with a wrapped body line\n"
    _defers_on_every_path(tmp_path, ARCH, HISTORY, ours, theirs)
    _lifted(monkeypatch)
    status, merged = resolve_conflict_bytes(base=HISTORY, ours=ours, theirs=theirs)
    assert status == RESOLVED and "</details>\n- **2026-02-11** — theirs entry\n" in merged, merged


def test_t1_a_details_block_ending_ours_decision_does_not_swallow_theirs_heading(
        tmp_path, monkeypatch):
    ours = (DECISION_LOG + "### [tp-run-full-design] ours choice\n\n**Decided**: o\n\n<details>\n"
            "<summary>why</summary>\n\nlong reasoning\n</details>\n")
    theirs = DECISION_LOG + "### [tp-worker] theirs choice\n\n**Question**: q\n**Decided**: t\n\n"
    _defers_on_every_path(tmp_path, DECISIONS, DECISION_LOG, ours, theirs)
    _lifted(monkeypatch)
    status, merged = resolve_conflict_bytes(base=DECISION_LOG, ours=ours, theirs=theirs)
    assert status == RESOLVED and "</details>\n### [tp-worker] theirs choice\n" in merged, merged


def test_t1_a_bare_cr_hiding_a_heading_in_ours_entry_defers(tmp_path, monkeypatch):
    """`ours body\\r## Won't Fix` is ONE line to the parse, which splits on `\\n`, and two to
    CommonMark: the second is a section heading theirs' entry would sit under."""
    ours = HISTORY + "- **2026-01-03** — ours body\r## Won't Fix\n"
    theirs = HISTORY + "- **2026-01-02** — theirs\n"
    _defers_on_every_path(tmp_path, ARCH, HISTORY, ours, theirs)
    _lifted(monkeypatch)
    status, merged = resolve_conflict_bytes(base=HISTORY, ours=ours, theirs=theirs)
    assert status == RESOLVED and "\r## Won't Fix\n- **2026-01-02** — theirs\n" in merged, merged


def test_t1_control_a_plain_wrapped_entry_on_each_side_still_resolves(tmp_path):
    ours = HISTORY + "- **2026-02-10** — ours entry\n\n  `argv[:2] == [\"pr\"]:` | a | b |\n"
    theirs = HISTORY + "- **2026-02-11** — theirs entry\n"
    repo, report = _merge(tmp_path, ARCH, HISTORY, ours, theirs)
    assert report.auto_resolved == [ARCH], report.to_json()


# ---- each refused shape, in each keep-both class ----------------------------------------------------

REFUSED = [
    ("<details>", "an HTML block"), ("</details>", "an HTML block"),
    ("  <div>", "an HTML block"), ("- <br>", "an HTML block"), ("\t<!-- note", "an HTML block"),
    ("```", "a fenced code block"), ("~~~python", "a fenced code block"),
    ("    ```", "a fenced code block"), ("1. ```sh", "a fenced code block"),
    ("> quoted", "a block quote"), ("  > quoted", "a block quote"),
    ("$$", "a display-math block"),
    ("[ref]: https://example.com", "definition"), ("- [ref]: https://example.com", "definition"),
    ("[^1]: a footnote", "definition"), ("continued label]: https://example.com", "definition"),
    ("  label with \\[escaped]: /url", "definition"),
    # round 23: the label's end is the FIRST `]:`, and only the text before it may hold its `[`
    ('bar]: /evil "t [x]"', "definition"), ('bar]: /evil "t [x]: y"', "definition"),
    # round 23: every list-marker form is skipped, repeated, with a space or a tab after it
    ("- - <details>", "an HTML block"), ("1) <details>", "an HTML block"),
    ("+ <details>", "an HTML block"), ("* <details>", "an HTML block"),
    ("-\t<details>", "an HTML block"),
    ("body\r## Won't Fix", "carriage return"), ("\r\r", "carriage return"),
]
ADMITTED = [
    "", " \t", "body\r", "plain continuation", "  indented continuation", "    indented code",
    "| run | result |", "|---|---|", "a | b", "`code span` first", "``two ticks``", "~~struck~~",
    "- nested bullet", "1. **ordered** item", "**Decided**: yes", "\\<div> escaped",
    "a <b>inline</b> tag", "[tp-run-full-design/tier-3.5] worktree note",
    "  `gh` shim (`if argv[:2] == [\"pr\", \"create\"]:`) note", "$5 cost", "- **2026-01-09** — x",
]
LOG_O, LOG_T, SEED = "- **2026-01-03** — ours", "- **2026-01-02** — theirs", "- **2026-01-01** — s"
DEC_O, DEC_T = "### [tp-plan] ours", "### [tp-plan] theirs"


def _hunks(extra: str):
    """One hunk per keep-both class, with `extra` as the last line of ours' inserted block."""
    return {
        "log-entry-insertion": Hunk(ours=[LOG_O, extra], base=[], theirs=[LOG_T], post_context=""),
        "decision-entry-insertion": Hunk(ours=[DEC_O, extra], base=[], theirs=[DEC_T],
                                         post_context=""),
        "append-only-log": Hunk(ours=[SEED, LOG_O, extra], base=[SEED], theirs=[SEED, LOG_T],
                                post_context=""),
    }


@pytest.mark.parametrize("line,why", REFUSED, ids=[repr(r[0]) for r in REFUSED])
def test_each_refused_shape_takes_the_hunk_out_of_every_keep_both_class(line, why):
    assert why in line_refusal(line, LOG_ENTRY), line
    for label, h in _hunks(line).items():
        assert classify_hunk(h) == "generic-prose", (label, line)
    for label, h in _hunks("plain body").items():                    # the control
        assert classify_hunk(h) == label


@pytest.mark.parametrize("line", ADMITTED, ids=[repr(a) for a in ADMITTED])
def test_each_admitted_shape_keeps_the_class(line):
    assert line_refusal(line, LOG_ENTRY) is None
    for label, h in _hunks(line).items():
        assert classify_hunk(h) == label, (label, line)


def test_theirs_side_is_held_to_the_allowlist_too():
    h = Hunk(ours=[LOG_O], base=[], theirs=[LOG_T, "<details>"], post_context="")
    assert classify_hunk(h) == "generic-prose"
    d = Hunk(ours=[DEC_O], base=[], theirs=[DEC_T, "```"], post_context="")
    assert classify_hunk(d) == "generic-prose"
    a = Hunk(ours=[SEED, LOG_O], base=[SEED], theirs=[SEED, LOG_T, "> q"], post_context="")
    assert classify_hunk(a) == "generic-prose"


def test_only_the_class_own_entry_start_is_exempt():
    """An entry start is admitted as itself: a log bullet holding `]:` with no `[` before it is
    not a definition. The same line on the decision class is not its entry start, so it is read as
    plain text and refused."""
    bullet = "- **2026-01-09** — ratio 3]: 1"
    assert line_refusal(bullet, LOG_ENTRY) is None
    assert "definition" in line_refusal(bullet, DECISION_ENTRY)
    assert keep_both_refusal([DEC_O, "ok", "<p>"], DECISION_ENTRY).startswith("'<p>' opens")
    assert keep_both_refusal([DEC_O, "ok"], DECISION_ENTRY) is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
