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
