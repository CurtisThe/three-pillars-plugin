"""Unit tests for the independent zero-drop verifier."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from verify import verify, atoms  # noqa: E402


def test_zero_drop_passes():
    ours = "### L4: keep me"
    theirs = "### L4: also keep\n### L5: and me"
    resolved = "### L4: keep me\n### L5: also keep\n### L6: and me"
    ok, dropped = verify(ours, theirs, resolved)
    assert ok and dropped == []


def test_renumber_is_not_a_drop():
    # L4 -> L7 is the same atom (ID-independent signature) — must NOT be flagged.
    ours = "### L4: project docs lag"
    theirs = "### L4: other"
    resolved = "### L4: other\n### L7: project docs lag"
    ok, _ = verify(ours, theirs, resolved)
    assert ok


def test_real_drop_is_flagged():
    ours = "### L4: project docs lag"
    theirs = "### L4: other\n### L5: more"
    resolved = "### L4: other\n### L5: more"        # ours' entry silently gone
    ok, dropped = verify(ours, theirs, resolved)
    assert not ok
    assert any("project docs lag" in sig for _, sig in dropped)


def test_row_drop_is_flagged():
    ours = "| D15 | lock-owner-classes | design | x |"
    theirs = "| D14 | foo | design | y |"
    resolved = "| D14 | foo | design | y |"          # D15 row dropped
    ok, dropped = verify(ours, theirs, resolved)
    assert not ok
    assert any("lock-owner-classes" in sig for _, sig in dropped)


def test_prose_is_not_an_atom():
    # prose edits legitimately differ; the verifier must not treat them as drops.
    ours = "Some prose here that changed."
    theirs = "Other prose entirely."
    resolved = "A synthesized human resolution."
    ok, _ = verify(ours, theirs, resolved)
    assert ok


def test_atoms_extracts_entries_and_rows():
    a = atoms("### L1: alpha\n| D2 | beta | design | z |\njust prose")
    kinds = sorted(k for k, _ in a)
    assert kinds == ["entry", "row"]


# ---- C3 log-atom backstop (basesync-prepend-log) --------------------------------------------

def test_log_bullet_drop_is_flagged():
    # A dated `## History` bullet present on an input side but missing from the merged output is a
    # drop — the log class now has a zero-drop backstop (previously log bullets were no atom at all).
    ours = "- **2026-07-04** — decision OURS"
    theirs = "- **2026-07-05** — decision THEIRS"
    resolved = "- **2026-07-05** — decision THEIRS"          # ours' entry silently gone
    ok, dropped = verify(ours, theirs, resolved)
    assert not ok
    assert any("decision ours" in sig for _, sig in dropped)


def test_name_keyed_log_bullet_drop_is_flagged():
    # Same backstop for the name-keyed `### Recent completions` shape.
    ours = "- **`design-a`** — Implemented (2026-07-04)."
    theirs = "- **`design-b`** — Done — archived (2026-07-05)."
    resolved = "- **`design-a`** — Implemented (2026-07-04)."   # theirs' entry dropped
    ok, dropped = verify(ours, theirs, resolved)
    assert not ok
    assert any("design-b" in sig for _, sig in dropped)


def test_log_keep_both_is_zero_drop():
    # Keep-both concatenation preserves every log bullet -> no drop.
    ours = "- **2026-07-04** — decision OURS"
    theirs = "- **2026-07-05** — decision THEIRS"
    resolved = "- **2026-07-04** — decision OURS\n- **2026-07-05** — decision THEIRS"
    ok, dropped = verify(ours, theirs, resolved)
    assert ok and dropped == []


def test_atoms_extracts_dated_and_name_keyed_log_bullets():
    a = atoms("- **2026-07-04** — dated one\n- **`design-x`** — name-keyed two\njust prose")
    assert len(a) == 2 and all(kind == "log" for kind, _ in a)   # prose is not an atom
    sigs = [sig for _, sig in a]
    assert any("dated one" in s for s in sigs)
    assert any("design-x" in s for s in sigs)


def test_file_path_bullet_is_not_a_log_atom():
    # Tightness: file-path description bullets look bold-lead but are excluded (kebab-slug arm), so
    # they never register as a log atom and never read as a drop.
    assert atoms("- **`scripts/foo.py`** — a build helper") == {}
