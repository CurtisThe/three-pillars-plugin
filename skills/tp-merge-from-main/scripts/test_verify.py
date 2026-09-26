"""Unit tests for the independent zero-drop verifier."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from verify import verify, atoms  # noqa: E402


def test_zero_drop_passes():
    ours = "### L4: keep me"
    theirs = "### L4: also keep\n### L5: and me"
    resolved = "### L4: keep me\n### L5: also keep\n### L6: and me"
    r = verify(ours, theirs, resolved, mechanical_applied=True)
    assert r.ok and r.dropped == []


def test_renumber_is_not_a_drop():
    # L4 -> L7 is the same atom (ID-independent signature) — must NOT be flagged.
    ours = "### L4: project docs lag"
    theirs = "### L4: other"
    resolved = "### L4: other\n### L7: project docs lag"
    r = verify(ours, theirs, resolved, mechanical_applied=True)
    assert r.ok


def test_real_drop_is_flagged():
    ours = "### L4: project docs lag"
    theirs = "### L4: other\n### L5: more"
    resolved = "### L4: other\n### L5: more"        # ours' entry silently gone
    r = verify(ours, theirs, resolved, mechanical_applied=True)
    assert not r.ok
    assert any("project docs lag" in sig for _, sig in r.dropped)


def test_row_drop_is_flagged():
    ours = "| D15 | lock-owner-classes | design | x |"
    theirs = "| D14 | foo | design | y |"
    resolved = "| D14 | foo | design | y |"          # D15 row dropped
    r = verify(ours, theirs, resolved, mechanical_applied=True)
    assert not r.ok
    assert any("lock-owner-classes" in sig for _, sig in r.dropped)


def test_prose_is_not_an_atom():
    # prose edits legitimately differ; the verifier must not treat them as drops.
    ours = "Some prose here that changed."
    theirs = "Other prose entirely."
    resolved = "A synthesized human resolution."
    # No mechanical apply on this lane (design Behavior 2) — zero atoms here is not UNVERIFIABLE.
    r = verify(ours, theirs, resolved, mechanical_applied=False)
    assert r.ok


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
    r = verify(ours, theirs, resolved, mechanical_applied=True)
    assert not r.ok
    assert any("decision ours" in sig for _, sig in r.dropped)


def test_name_keyed_log_bullet_drop_is_flagged():
    # Same backstop for the name-keyed `### Recent completions` shape.
    ours = "- **`design-a`** — Implemented (2026-07-04)."
    theirs = "- **`design-b`** — Done — archived (2026-07-05)."
    resolved = "- **`design-a`** — Implemented (2026-07-04)."   # theirs' entry dropped
    r = verify(ours, theirs, resolved, mechanical_applied=True)
    assert not r.ok
    assert any("design-b" in sig for _, sig in r.dropped)


def test_log_keep_both_is_zero_drop():
    # Keep-both concatenation preserves every log bullet -> no drop.
    ours = "- **2026-07-04** — decision OURS"
    theirs = "- **2026-07-05** — decision THEIRS"
    resolved = "- **2026-07-04** — decision OURS\n- **2026-07-05** — decision THEIRS"
    r = verify(ours, theirs, resolved, mechanical_applied=True)
    assert r.ok and r.dropped == []


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


# ---- Fix B: the `decision-entry` atom (`### [{skill-name}] <title>`) -------------------------

_ENTRY_A = ("### [tp-plan] weight class kept at light\n"
            "**Question**: escalate to full?\n"
            "**Decided**: no — one phase\n")
_ENTRY_B = ("### [tp-run-full-design/tier-1] pickup — Mode B\n"
            "**Question**: which mode\n"
            "**Decided**: B\n")


def test_atoms_extracts_decision_entries():
    a = atoms(_ENTRY_A)
    assert len(a) == 1
    (kind, sig), = a
    assert kind == "decision-entry"
    assert sig.startswith("tp-plan|weight class kept at light|")

    # The observed slash-bearing tag form must parse too.
    b = atoms(_ENTRY_B)
    assert len(b) == 1 and list(b)[0][0] == "decision-entry"
    assert list(b)[0][1].startswith("tp-run-full-design/tier-1|pickup — mode b|")


def test_decision_entry_drop_is_flagged():
    resolved = _ENTRY_A                       # theirs' entry silently gone
    r = verify(_ENTRY_A, _ENTRY_B, resolved, mechanical_applied=True)
    assert not r.ok
    assert any("pickup" in sig for _kind, sig in r.dropped)


def test_same_tag_same_title_different_body_are_two_atoms():
    # The measured collision case: the real `worktree-fleet` log carries `### [orchestrator/
    # plan-audit] clip` twice with different bodies. A title-only (or `(tag, title)`) signature
    # would fold them into ONE atom and a drop of one would verify clean.
    ours = "### [orchestrator/plan-audit] clip\n**Decided**: kept finding 1\n"
    theirs = "### [orchestrator/plan-audit] clip\n**Decided**: kept finding 2\n"
    assert len(atoms(ours + theirs)) == 2

    r = verify(ours, theirs, ours, mechanical_applied=True)      # theirs' copy dropped
    assert not r.ok and len(r.dropped) == 1


def test_decision_entry_body_stops_at_the_next_ENTRY_and_nothing_else():
    # The block body runs to the next DECISION-ENTRY heading: a following entry must not be
    # swallowed, or two entries would collapse into one atom.
    two = _ENTRY_A + _ENTRY_B
    assert len(atoms(two)) == 2
    # A plain `## Some Section` does NOT close the block (round 7). It used to, and the prose
    # after it then belonged to no atom — deleting `trailing prose` left every signature
    # unchanged and verified clean. It is body now, so the tail is covered.
    tail = _ENTRY_A + "## Some Section\n\ntrailing prose\n"
    assert len(atoms(tail)) == len(atoms(_ENTRY_A)) == 1
    assert atoms(tail) != atoms(_ENTRY_A)
    assert atoms(tail) != atoms(_ENTRY_A + "## Some Section\n\ndifferent prose\n")


def test_id_heading_is_still_an_entry_not_a_decision_entry():
    a = atoms("### L4: keep me")
    assert list(a)[0][0] == "entry"
    assert not any(k == "decision-entry" for k, _ in a)


def test_log_shaped_body_line_yields_BOTH_atoms():
    """Double-capture is INTENDED and measured, not hypothetical.

    Modelled on the real `three-pillars-docs/completed-tp-designs/basesync-prepend-log/
    decisions.md:124`, whose Reasoning body opens with a changelog bullet in exactly `LOG`'s
    bold-lead shape. 3 of 11,702 entry-body lines across this repo's 102 real `decisions.md`
    files already match `LOG`, so SKIPPING already-consumed block lines would DELETE `log` atoms
    `atoms()` emits today — a sensitivity regression, and it would falsify the purely-additive
    claim. The block scan therefore runs ALONGSIDE the per-line scan with no skip.
    """
    text = ("### [REDESIGN AS-BUILT 2026-07-06] shipped + dogfood-gated\n"
            "Landed on the design branch:\n"
            "- **`fde5bdc1`** — classify.py: log-entry-insertion now fires on an empty base\n")
    a = atoms(text)
    kinds = sorted(k for k, _ in a)
    # (i) BOTH atoms fire over the same lines.
    assert kinds == ["decision-entry", "log"], kinds
    # (ii) the keys do not collide — the kinds differ, so one dict holds both.
    assert len(a) == 2

    # (iii) dropping EITHER is reported.
    without_bullet = "\n".join(text.splitlines()[:2]) + "\n"
    r = verify(text, "", without_bullet, mechanical_applied=True)
    # the `log` atom AND the now-digest-changed `decision-entry` atom are both lost
    assert len(r.dropped) == 2, r.dropped
    assert sorted(k for k, _ in r.dropped) == ["decision-entry", "log"]

    r_all = verify(text, "", "unrelated prose\n", mechanical_applied=True)
    assert sorted(k for k, _ in r_all.dropped) == ["decision-entry", "log"]


def test_atom_kinds_is_verifys_self_description():
    import verify as _v
    assert _v.ATOM_KINDS == ("entry", "row", "log", "decision-entry")
