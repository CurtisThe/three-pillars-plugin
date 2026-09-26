"""Pure-unit tests for the relaxed-cond5 helpers of `living_doc_carry.py` (Phase 2).

`_has_conflict_markers` (F5 marker guard, task 2.1) and `_mechanical_resolution`
(M2 zero-drop + F1 kw-only + DEFER→preamble-date upgrade, task 2.2). No git fixtures here —
the git-backed `certify_link_carry` end-to-end lives in `test_base_sync_cert_handres*.py`.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import base_sync_cert  # noqa: E402
from auto_safe_resolution import DEFER, RESOLVED  # noqa: E402
from living_doc_carry import (  # noqa: E402
    _has_conflict_markers,
    _mechanical_resolution,
    _relaxed_resolve,
)

_MERGE_SCRIPTS = os.path.join(os.path.dirname(__file__), os.pardir, "tp-merge-from-main", "scripts")
if _MERGE_SCRIPTS not in sys.path:
    sys.path.insert(0, _MERGE_SCRIPTS)
import verify as _verify  # noqa: E402


def _doc(preamble_date: str, *, extra: str = "", top_history: str = "2026-07-09") -> str:
    """A living doc with a `*Last updated: DATE*` preamble and a dated `## History`."""
    return (
        "# Known Issues\n"
        f"*Last updated: {preamble_date} — see [History](#history).*\n"
        "\n"
        f"{extra}"
        "## History\n"
        "\n"
        f"- **{top_history}** — newest entry\n"
        "- **2026-06-15** — older entry\n"
    )


# ============================================================
# Task 2.1: _has_conflict_markers — the F5 marker guard
# ============================================================


def test_has_conflict_markers_positive_sigils():
    for marker in ("<<<<<<<", ">>>>>>>", "|||||||"):
        text = f"line one\n{marker} HEAD\nline two\n"
        assert _has_conflict_markers(text) is True, marker


def test_has_conflict_markers_orphaned_seven_equals_divider():
    # An orphaned diff3 divider — flanks stripped, the middle `=======` left behind.
    assert _has_conflict_markers("a\n=======\nb\n") is True


def test_has_conflict_markers_clean_text_is_false():
    assert _has_conflict_markers("just some clean\nliving-doc prose\n") is False
    assert _has_conflict_markers("") is False


def test_has_conflict_markers_near_miss_equals_runs_are_false():
    assert _has_conflict_markers("========\n") is False   # eight `=`, not seven
    assert _has_conflict_markers("===\n") is False         # three `=`
    assert _has_conflict_markers("prefix ======= suffix\n") is False  # inline, not whole line


def test_has_conflict_markers_total_on_non_str():
    for bad in (None, 123, ["<<<<<<<"], object()):
        assert _has_conflict_markers(bad) is False, repr(bad)


def test_has_conflict_markers_exact_git_flank_shapes_are_true():
    # git writes each flank/base marker as EXACTLY 7 sigils + a space (label) or end-of-line
    # (bare). Both shapes must still fire.
    assert _has_conflict_markers("<<<<<<< HEAD\n") is True        # labeled flank
    assert _has_conflict_markers("<<<<<<<\n") is True             # bare flank (7 + EOL)
    assert _has_conflict_markers("line\n>>>>>>>\n") is True       # bare end flank
    assert _has_conflict_markers("|||||||  base\n") is True       # diff3 base marker + label


def test_has_conflict_markers_flank_lookalikes_are_false():
    # A marker LOOKALIKE in inert carry-set prose must NOT false-positive (else the carry is
    # needlessly refused → a re-approval on inert prose, the very tax this design removes).
    assert _has_conflict_markers("<<<<<<<<x\n") is False          # 8 sigils, not 7
    assert _has_conflict_markers("<<<<<<<x\n") is False           # 7 sigils + non-space content
    assert _has_conflict_markers(">>>>>>>>\n") is False           # 8 sigils
    assert _has_conflict_markers("|||||||x\n") is False           # 7 sigils + non-space content
    assert _has_conflict_markers("prefix <<<<<<< inline\n") is False   # not at line start
    assert _has_conflict_markers("a fenced <<<<<<<7-arrow example\n") is False  # mid/non-space


# ============================================================
# _relaxed_resolve git-error fail-closed branches (targeted unit — hand-built conflicts + seam)
# ============================================================
#
# Reaching `git error: ls-tree failed` / `git error: cat-file blob failed` through the full
# certifier would require a fake git that also satisfies cond1-4; instead drive `_relaxed_resolve`
# directly with a hand-built `conflicts` dict on a CARRY-SET path (so M1 + the shape gate pass and
# the git-error guard under test is genuinely reached) and the injected `git` seam.

_CARRY = "three-pillars-docs/known_issues.md"


def _stages(mode: str = "100644") -> dict:
    return {1: (mode, "a" * 40), 2: (mode, "b" * 40), 3: (mode, "c" * 40)}


def test_relaxed_resolve_ls_tree_failure_refuses():
    def fake_git(args):
        if args[:1] == ["ls-tree"]:
            return (1, "", "fatal: ls-tree exploded")
        return (0, "", "")

    reason, carry = _relaxed_resolve(fake_git, {_CARRY: _stages()}, "h1")
    assert carry is None
    assert reason == "git error: ls-tree failed"


def test_relaxed_resolve_cat_file_failure_refuses():
    def fake_git(args):
        if args[:1] == ["ls-tree"]:
            # a well-formed 100644 h1 blob line → the ls-tree + mode checks pass, so the refusal
            # must come from the cat-file blob failure below (non-vacuous).
            return (0, "100644 blob " + "d" * 40 + "\t" + _CARRY + "\n", "")
        if args[:1] == ["cat-file"]:
            return (1, "", "fatal: bad object")
        return (0, "", "")

    reason, carry = _relaxed_resolve(fake_git, {_CARRY: _stages()}, "h1")
    assert carry is None
    assert reason == "git error: cat-file blob failed"


# ============================================================
# Task 2.2: _mechanical_resolution — M2 zero-drop + F1 kw-only + DEFER upgrade
# ============================================================


def test_mechanical_resolution_resolved_returns_merged(monkeypatch):
    # RESOLVED with a verify-clean merged text (no atoms dropped) → the merged text.
    # The fixture carries real `entry` atoms deliberately: this lane passes
    # `mechanical_applied=True`, so an atom-less fixture would now verify UNVERIFIABLE (and
    # correctly return None), which would no longer exercise the VERIFIED path this test names.
    merged = "### L1: alpha\n### L2: beta\n"
    monkeypatch.setattr(base_sync_cert, "resolve_conflict_bytes",
                        lambda *, base, ours, theirs: (RESOLVED, merged))
    assert _mechanical_resolution("b\n", "### L1: alpha\n", "### L2: beta\n") == merged


def test_mechanical_resolution_m2_drop_returns_none(monkeypatch):
    # M2: RESOLVED, but the merged text DROPS an atom present on a side → None, EVEN THOUGH
    # the resolver said RESOLVED (mirrors strict _cond5_resolve's re-verify).
    ours = "### L1: kept entry\n"
    theirs = "### L2: dropped entry\n"
    merged = "### L1: kept entry\n"        # L2 dropped
    monkeypatch.setattr(base_sync_cert, "resolve_conflict_bytes",
                        lambda *, base, ours, theirs: (RESOLVED, merged))
    # sanity: verify independently flags the drop
    r = _verify.verify(ours, theirs, merged, mechanical_applied=True)
    assert r.ok is False and r.dropped
    assert _mechanical_resolution("", ours, theirs) is None


def test_mechanical_resolution_f1_keyword_only_call(monkeypatch):
    # F1: _mechanical_resolution calls resolve_conflict_bytes(base=, ours=, theirs=)
    # KEYWORD-ONLY. A kw-only-shaped spy proves it: a positional call would raise TypeError,
    # which the helper's own `except → None` swallows — so a non-None return is the ONLY
    # observable proof the call went through by keyword. (Do NOT wrap pytest.raises around
    # the never-raises helper — it would never see the TypeError.)
    merged = "### L1: alpha\n### L2: beta\n"          # atom-bearing: see the RESOLVED test above

    def kwonly_spy(*, base, ours, theirs):
        return (RESOLVED, merged)

    monkeypatch.setattr(base_sync_cert, "resolve_conflict_bytes", kwonly_spy)
    assert _mechanical_resolution("b\n", "### L1: alpha\n", "### L2: beta\n") == merged


def test_mechanical_resolution_defer_date_only_upgrade(monkeypatch):
    # DEFER + the two sides differ SOLELY in the preamble date → regenerate the date from
    # History (topmost bullet), zero-drop-verify, return the upgraded doc.
    monkeypatch.setattr(base_sync_cert, "resolve_conflict_bytes",
                        lambda *, base, ours, theirs: (DEFER, ""))
    out = _mechanical_resolution(_doc("2026-06-01"), _doc("2026-06-03"), _doc("2026-06-02"))
    assert out == _doc("2026-07-09")   # preamble regenerated to the topmost History date


def test_mechanical_resolution_defer_richer_divergence_returns_none(monkeypatch):
    # DEFER + a divergence richer than the date (an extra ours-only prose line) → genuine
    # defer → None (never fabricates prose).
    monkeypatch.setattr(base_sync_cert, "resolve_conflict_bytes",
                        lambda *, base, ours, theirs: (DEFER, ""))
    ours = _doc("2026-06-03", extra="an ours-only prose line\n")
    theirs = _doc("2026-06-02")
    assert _mechanical_resolution(_doc("2026-06-01"), ours, theirs) is None


def test_mechanical_resolution_total_on_exception(monkeypatch):
    def boom(*, base, ours, theirs):
        raise RuntimeError("resolver blew up")

    monkeypatch.setattr(base_sync_cert, "resolve_conflict_bytes", boom)
    assert _mechanical_resolution("b\n", "o\n", "t\n") is None


# ============================================================
# Task 1.5: the three verifier sites honour the three-state verdict
# ============================================================

# Prose the verifier recognizes NO atom in — the unknown-shape class.
_NO_ATOMS_OURS = "# Doc\n\nOurs rewrote this paragraph.\n"
_NO_ATOMS_THEIRS = "# Doc\n\nTheirs rewrote it differently.\n"


def test_mechanical_resolution_returns_none_on_unverifiable(monkeypatch):
    """RESOLVED branch: the resolver succeeded but the verifier parsed ZERO atoms. This lane
    DID apply a mechanical resolution, so that is UNVERIFIABLE — 'nothing was examined', not
    'nothing was lost' — and `_mechanical_resolution` must fail closed to None. Before the
    three-state verdict this returned the merged text and the carry trusted it."""
    merged = "# Doc\n\nA merged paragraph with no recognized atom.\n"
    monkeypatch.setattr(base_sync_cert, "resolve_conflict_bytes",
                        lambda *, base, ours, theirs: (RESOLVED, merged))
    r = _verify.verify(_NO_ATOMS_OURS, _NO_ATOMS_THEIRS, merged, mechanical_applied=True)
    assert r.verdict == _verify.UNVERIFIABLE          # non-vacuous: the verdict really fires
    assert _mechanical_resolution("# Doc\n", _NO_ATOMS_OURS, _NO_ATOMS_THEIRS) is None


def test_mechanical_resolution_date_upgrade_declares_mechanical_applied(monkeypatch):
    """Date-upgrade branch: the date-substituted candidate is ITSELF a mechanical apply, so
    that site must pass `mechanical_applied=True` too.

    It is asserted via a spy rather than by a zero-atom fixture because the branch cannot
    reach zero atoms: `regenerate_preamble_date` only fires on a `- **YYYY-MM-DD** —` History
    bullet, which is exactly `verify.LOG`'s shape — so any doc that reaches this branch carries
    at least one `log` atom by construction. The spy pins the wiring the fixture cannot.
    """
    seen = {}
    real_verify = _verify.verify

    def spy(ours, theirs, resolved, *, mechanical_applied):
        seen["mechanical_applied"] = mechanical_applied
        return real_verify(ours, theirs, resolved, mechanical_applied=mechanical_applied)

    monkeypatch.setattr(base_sync_cert, "resolve_conflict_bytes",
                        lambda *, base, ours, theirs: (DEFER, ""))
    monkeypatch.setattr(_verify, "verify", spy)
    out = _mechanical_resolution(_doc("2026-06-01"), _doc("2026-06-03"), _doc("2026-06-02"))
    assert out == _doc("2026-07-09")
    assert seen["mechanical_applied"] is True


def test_relaxed_resolve_handres_blob_is_not_unverifiable():
    """The ACCEPTED RESIDUAL EXEMPTION (design §Constraints). `_relaxed_resolve` verifies
    whatever blob is committed at `h1` for the path; no mechanical apply happened on this lane,
    so it passes `mechanical_applied=False` and an atom-less prose file must still succeed —
    `reason == ""` and the path joins `carry_paths`. Behavior 2: this lane legitimately carries
    free-form rewritten prose, so 'parsed zero atoms' is not evidence of a mistake here.

    The consequence is deliberate and recorded: future shape drift arriving on this lane still
    passes silently. Mitigated by Tasks 1.9/1.10, not closed here.
    """
    committed = "# Doc\n\nA synthesized resolution in free-form prose.\n"
    blobs = {"a" * 40: "# Doc\n\nbase prose.\n",
             "b" * 40: _NO_ATOMS_OURS,
             "c" * 40: _NO_ATOMS_THEIRS,
             "d" * 40: committed}

    def fake_git(args):
        if args[:1] == ["ls-tree"]:
            return (0, "100644 blob " + "d" * 40 + "\t" + _CARRY + "\n", "")
        if args[:1] == ["cat-file"]:
            return (0, blobs[args[2]], "")
        return (0, "", "")

    # Non-vacuous: the same blobs on the MECHANICAL lane would be UNVERIFIABLE.
    assert _verify.verify(_NO_ATOMS_OURS, _NO_ATOMS_THEIRS, committed,
                          mechanical_applied=True).verdict == _verify.UNVERIFIABLE

    reason, carry = _relaxed_resolve(fake_git, {_CARRY: _stages()}, "h1")
    assert reason == ""
    assert carry == [_CARRY]
