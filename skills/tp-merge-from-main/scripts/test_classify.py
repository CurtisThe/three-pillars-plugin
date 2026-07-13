"""Unit tests for the structural conflict classifier."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from classify import classify_file, parse_conflict, MECHANICAL, SEMANTIC  # noqa: E402


def _diff3(ours, base, theirs, pre=""):
    block = "<<<<<<< ours\n" + ours + "\n||||||| base\n" + base + "\n=======\n" + theirs + "\n>>>>>>> theirs"
    return (pre + "\n" + block) if pre else block


def labels(text):
    pf = classify_file(text)
    return [s.label for s in pf.segments if not isinstance(s, str)]


def test_preamble():
    t = _diff3("*Last updated: 2026-05-17*", "*Last updated: 2026-05-15*", "*Last updated: 2026-05-16*")
    assert labels(t) == ["preamble"]


def test_id_renumber_collision():
    t = _diff3("### L4: ours entry\nbody", "", "### L4: theirs entry\nbody2\n### L5: another")
    assert labels(t) == ["id-renumber-collision"]
    assert "id-renumber-collision" in MECHANICAL


def test_design_inventory_row():
    t = _diff3("| D12 | foo | design | x |", "", "| D12 | foo | design | y |\n| D14 | bar | design | z |")
    assert labels(t) == ["design-inventory-row-merge"]


def test_current_focus_is_semantic():
    pre = "## Current Focus\n\n| Priority | Design | Next Action | Blocked By |"
    t = _diff3("| 3 | foo | act | — |", "", "| 3 | foo | other-act | — |", pre=pre)
    out = labels(t)
    assert out == ["current-focus-reprioritization"]
    assert "current-focus-reprioritization" in SEMANTIC


def test_generic_prose_defaults_semantic():
    t = _diff3("Some prose here.", "Base prose.", "Other prose here.")
    assert labels(t) == ["generic-prose"]


def test_append_only_log():
    base = "line a\nline b"
    t = _diff3("line a\nline b\nours tail", base, "line a\nline b\ntheirs tail")
    assert labels(t) == ["append-only-log"]


def _diff3_empty_base(ours, theirs, pre=""):
    # Real git-minimized concurrent-insertion shape: EMPTY base (no line between the base markers).
    block = "<<<<<<< ours\n" + ours + "\n||||||| base\n=======\n" + theirs + "\n>>>>>>> theirs"
    return (pre + "\n" + block) if pre else block


def test_log_entry_insertion_dated_bullet_real_empty_base_shape():
    # The REAL git-minimized shape: empty base, both sides insert a dated bold-lead-bullet entry
    # (architecture.md `## History` form) — what `git merge-file --diff3` actually produces.
    t = _diff3_empty_base("- **2026-07-04** — decision OURS", "- **2026-07-05** — decision THEIRS",
                          pre="## History")
    assert labels(t) == ["log-entry-insertion"]
    assert "log-entry-insertion" in MECHANICAL


def test_log_entry_insertion_name_keyed_bullet():
    # product_roadmap.md `### Recent completions` form: name-keyed `- **`slug`** — …` bullets.
    t = _diff3_empty_base("- **`design-a`** — Implemented (2026-07-04).",
                          "- **`design-b`** — Done — archived (2026-07-05).",
                          pre="### Recent completions")
    assert labels(t) == ["log-entry-insertion"]


def test_log_entry_insertion_wrapped_multiline_entry():
    # An entry that WRAPS across a blank + indented continuation body must STILL classify as a log
    # insertion (the correctness point: continuation lines are allowed — not every line is a bullet).
    ours = "- **2026-07-04** — decision OURS\n\n  rat ours"
    theirs = "- **2026-07-05** — decision THEIRS\n\n  rat theirs"
    t = _diff3_empty_base(ours, theirs, pre="## History")
    assert labels(t) == ["log-entry-insertion"]


def test_log_entry_insertion_defers_on_nonlog_prose():
    # Tightness: a side whose insertion is arbitrary prose (not a log bullet) is NOT a clean log
    # insertion -> defer to a human. The bullet-block restriction still limits keep-both.
    t = _diff3_empty_base("- **2026-07-04** — real entry", "just some concurrent prose paragraph",
                          pre="## History")
    assert labels(t) == ["generic-prose"]


def test_log_entry_insertion_defers_on_file_path_bullet():
    # Tightness: file-path description bullets (Canon-reframe style) look bold-lead but are NOT log
    # entries — the kebab-slug arm excludes `/`/`.`, so they defer to a human.
    t = _diff3_empty_base("- **`scripts/foo.py`** — a build helper",
                          "- **`scripts/bar.py`** — another helper")
    assert labels(t) == ["generic-prose"]


def test_parse_roundtrip_multiple_hunks():
    t = "clean head\n" + _diff3("*Last updated: x*", "*Last updated: w*", "*Last updated: y*") + \
        "\nmiddle\n" + _diff3("### L4: a", "", "### L4: b")
    pf = parse_conflict(t)
    hunks = [s for s in pf.segments if not isinstance(s, str)]
    assert len(hunks) == 2
    # second hunk should carry the 'middle' pre-context line
    assert hunks[1].pre_context == "middle"
