"""Round 20 minors — headings in every CommonMark form, the far edge, and a hand-built Hunk.

H   The purity predicates treated only a column-0 ATX heading (`^#{1,6}\\s`) as a section heading.
    An ATX heading indented 1-3 spaces, an empty `#`, and a setext heading (a line underlined with
    `---` / `===`) passed as body lines, so a keep-both merge put the other side's entries under
    that section. `classify._heading_at` refuses all of them.
E   The log classes' far-edge boundary (`classify._ends_at_boundary`) was pinned only against an
    indented continuation and an unknown line; accepting any unindented line (`^\\S`) survived.
P   `Hunk.post_context` defaulted to "", which reads as EOF — the value that PASSES the boundary —
    so a hand-built hunk skipped the far-edge arm. It defaults to None (unknown) now.

Round 21 adds one more: a line holding only NBSP is not blank to CommonMark, so a `---` under it is
a setext underline (`_heading_at` used `str.strip()`, which strips NBSP). Round 23 widens the
keep-both classes' heading test to any indentation (`test_keep_both_nested_headings`).

Real-git cases run `git merge-file` through the byte path and `merge_driver.merge_back`.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import resolvers  # noqa: E402
from classify import Hunk, classify_hunk  # noqa: E402
from resolve_totality import CannotPlace  # noqa: E402
from test_merge_driver import git  # noqa: E402
from test_resolve_three_way import _merge  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_shared"))
from auto_safe_resolution import deferred_hunk_reasons  # noqa: E402

ARCH = "three-pillars-docs/architecture.md"
DECISIONS = "three-pillars-docs/tp-designs/x/decisions.md"
A = "# A\n\n## History\n\n- **2026-01-01** — alpha\n"
SEMANTIC = ["generic-prose: semantic class — needs human"]


def _insert(doc, block, anchor="## History\n\n"):
    return doc.replace(anchor, anchor + block)


# ---- H: a heading in any form is foreign to a log insertion, on real git -------------------------

@pytest.mark.parametrize("ours_block", [
    "- **2026-01-03** — ours\n   ## Archive\n",          # ATX indented three spaces
    "- **2026-01-03** — ours\n#\n",                        # an empty ATX heading
    "- **2026-01-03** — ours\n\nArchive\n-------\n",       # setext, `-` underline
    "- **2026-01-03** — ours\n\nArchive\n===\n",           # setext, `=` underline
], ids=["indented-atx", "empty-atx", "setext-dash", "setext-equals"])
def test_h_a_heading_inside_a_log_insertion_defers(tmp_path, ours_block):
    """Pre-fix each of these auto-resolved as `log-entry-insertion`, theirs' bullet emitted under
    ours' heading."""
    ours, theirs = _insert(A, ours_block), _insert(A, "- **2026-01-02** — theirs\n")
    assert deferred_hunk_reasons(base=A, ours=ours, theirs=theirs) == SEMANTIC
    repo, report = _merge(tmp_path, ARCH, A, ours, theirs)
    assert ARCH not in report.auto_resolved, report.to_json()
    assert git(repo, "ls-files", "-u", "--", ARCH).stdout.strip(), "must stay unmerged"


def test_h_control_a_wrapped_entry_still_resolves(tmp_path):
    ours, theirs = _insert(A, "- **2026-01-03** — ours\n  body\n"), _insert(A, "- **2026-01-02** — t\n")
    assert _merge(tmp_path, ARCH, A, ours, theirs)[1].auto_resolved == [ARCH]


@pytest.mark.parametrize("extra", [["  ## Sub"], ["Note", "---"], ["Note", "==="], ["#"]],
                         ids=["indented-atx", "setext-dash", "setext-equals", "empty-atx"])
def test_h_the_decision_insertion_class_refuses_the_same_forms(extra):
    ours = ["### [tp-plan] ours", "**Decided**: yes", *extra]
    h = Hunk(ours=ours, base=[], theirs=["### [tp-plan] theirs"], post_context="")
    assert classify_hunk(h) != "decision-entry-insertion"
    control = Hunk(ours=ours[:2], base=[], theirs=["### [tp-plan] theirs"], post_context="")
    assert classify_hunk(control) == "decision-entry-insertion"


def test_h_the_decision_insertion_class_refuses_an_indented_heading_on_real_git(tmp_path):
    base = "# Decisions\n\n### [tp-design] first\n**Decided**: a\n"
    ours = base + "\n### [tp-plan] ours\n**Decided**: b\n   ## Aside\n"
    theirs = base + "\n### [tp-plan] theirs\n**Decided**: c\n"
    assert deferred_hunk_reasons(base=base, ours=ours, theirs=theirs) == SEMANTIC
    control = _merge(tmp_path, DECISIONS, base, ours.replace("   ## Aside\n", ""), theirs)[1]
    assert DECISIONS in control.auto_resolved, control.to_json()


def test_h_an_nbsp_only_line_is_not_blank_so_the_rule_under_it_is_a_setext_heading(tmp_path):
    """Round 21. CommonMark's blank line is spaces and tabs only, but `_heading_at` tested the line
    above an underline with `str.strip()`, which also strips NBSP. So `**Decided**: b`, an NBSP-only
    line, then `---` passed as body plus a thematic break. To CommonMark the NBSP line continues the
    paragraph and `---` makes it a setext h2, which master's decision then sat under.

    Round 23: the keep-both allowlist applies the same blank test to a setext-shaped line at any
    indentation (`line_shapes._blank`), so a CommonMark blank line above `---` still admits it and
    this real-git case is refused by both copies; each is pinned alone elsewhere
    (`test_keep_both_nested_headings`, `test_keep_both_setext_blank`)."""
    base = "# Decisions\n\n### [tp-design] first\n**Decided**: a\n"
    ours = base + "\n### [tp-run-full-design/tier-1] design decision\n**Decided**: b\n\u00a0\n---\n"
    theirs = base + "\n### [tp-worker] master decision\n**Decided**: c\n"
    assert deferred_hunk_reasons(base=base, ours=ours, theirs=theirs) == SEMANTIC
    repo, report = _merge(tmp_path, DECISIONS, base, ours, theirs)
    assert DECISIONS not in report.auto_resolved, report.to_json()
    assert git(repo, "ls-files", "-u", "--", DECISIONS).stdout.strip(), "must stay unmerged"
    for blank in ("", " \t", "\r"):                    # a CommonMark blank line: a thematic break
        h = Hunk(ours=["### [tp-plan] ours", "**Decided**: b", blank, "---"], base=[],
                 theirs=["### [tp-plan] theirs"], post_context="")
        assert classify_hunk(h) == "decision-entry-insertion", repr(blank)


# ---- E: an unindented line that continues an entry is not a boundary ----------------------------

def test_e_a_lazy_continuation_after_a_log_insertion_defers_on_real_git(tmp_path):
    """Both sides insert a bullet between alpha and its unindented (lazy) continuation line, so the
    line follows theirs' bullet after a keep-both. With `^\\S` accepted as a boundary this resolved."""
    base = A + "lazy continuation of alpha\n"
    ours = base.replace("— alpha\n", "— alpha\n- **2026-01-03** — ours\n")
    theirs = base.replace("— alpha\n", "— alpha\n- **2026-01-02** — theirs\n")
    assert deferred_hunk_reasons(base=base, ours=ours, theirs=theirs) == SEMANTIC
    repo, report = _merge(tmp_path, ARCH, base, ours, theirs)
    assert ARCH not in report.auto_resolved, report.to_json()


SEED, O_T, T_T = "- **2026-01-01** — seed", ["- **2026-01-03** — ours"], ["- **2026-01-02** — t"]


@pytest.mark.parametrize("post,ok", [
    ("plain prose after the region", False), ("Workaround: rerun.", False), ("", True),
], ids=["prose", "label-line", "eof"])
def test_e_an_unindented_non_entry_line_after_an_append_region_refuses(post, ok):
    """`append-only-log` at the unit level: on real git its region holds base's last line (the one
    without a final newline), and in every shape measured merge-file wrote nothing after it."""
    h = Hunk(ours=[SEED, *O_T], base=[SEED], theirs=[SEED, *T_T], post_context=post)
    assert (classify_hunk(h) == "append-only-log") is ok


# ---- P: a hand-built hunk's post_context is unknown, and unknown refuses ------------------------

def test_p_a_hand_built_hunk_does_not_skip_the_far_edge():
    assert Hunk(ours=[], base=[], theirs=[]).post_context is None
    log = dict(ours=["- **2026-01-03** — o"], base=[], theirs=["- **2026-01-02** — t"])
    assert classify_hunk(Hunk(**log)) == "generic-prose"
    assert classify_hunk(Hunk(**log, post_context="")) == "log-entry-insertion"
    app = Hunk(ours=[SEED, *O_T], base=[SEED], theirs=[SEED, *T_T], label="append-only-log")
    with pytest.raises(CannotPlace, match="whole log entries"):
        resolvers.resolve_append_log(app)
    ren = dict(ours=["### L5: a"], base=[], theirs=["### L5: b"], label="id-renumber-collision")
    with pytest.raises(CannotPlace, match="same-letter collision"):
        resolvers.resolve_id_renumber(Hunk(**ren))
    assert resolvers.resolve_id_renumber(Hunk(**ren, post_context="")).renumbered == {"L5": "L6"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
