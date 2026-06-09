"""Unit tests for the mechanical resolvers + deferral."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from resolve import resolve_file, RESOLVED, DEFER  # noqa: E402


def _diff3(ours, base, theirs, pre=""):
    block = "<<<<<<< ours\n" + ours + "\n||||||| base\n" + base + "\n=======\n" + theirs + "\n>>>>>>> theirs"
    return (pre + "\n" + block) if pre else block


def test_id_renumber_is_zero_drop_and_monotonic():
    # ours claims L4; theirs claims L4,L5,L6 -> all six survive, monotonically numbered.
    t = "### L3: prior\n" + _diff3(
        "### L4: ours unique",
        "",
        "### L4: theirs a\n### L5: theirs b\n### L6: theirs c",
    )
    status, lines, results = resolve_file(t)
    heads = [l for l in lines if l.startswith("### ")]
    titles = " ".join(heads)
    # zero-drop: every entry's title present
    for needle in ["ours unique", "theirs a", "theirs b", "theirs c"]:
        assert needle in titles
    # monotonic IDs L3..L6 (ours L4 kept; theirs renumbered contiguously after)
    nums = [int(h.split(":")[0].split("L")[1]) for h in heads]
    assert nums == sorted(nums), nums
    # theirs' colliding L4 was remapped
    rmap = results[0].renumbered
    assert rmap.get("L4") == "L5"


def test_id_renumber_updates_cross_references():
    t = _diff3(
        "### L4: ours",
        "",
        "### L4: theirs (see L5 for detail)\n### L5: detail",
    )
    _, lines, _ = resolve_file(t)
    text = "\n".join(lines)
    # theirs L4->L5 and L5->L6, so the cross-ref 'see L5' must become 'see L6'
    assert "see L6 for detail" in text
    assert "see L5 for detail" not in text


def test_xref_no_cascade_on_chained_renumber():
    # Regression (Copilot round-2 #4): chained remap L4->L5, L5->L6 must map each ref to its
    # DIRECT target in one pass — not cascade L4->L5->L6.
    t = _diff3(
        "### L4: ours",
        "",
        "### L4: theirs (refs L4 and L5)\n### L5: detail",
    )
    _, lines, results = resolve_file(t)
    text = "\n".join(lines)
    # theirs L4->L5, L5->L6; body 'refs L4 and L5' must become 'refs L5 and L6' (no cascade to L6,L6)
    assert "refs L5 and L6" in text, text
    assert "L6 and L6" not in text
    # heading retag is consistent and not double-applied
    assert "### L5: theirs" in text


def test_inventory_union_prefers_theirs_zero_row_drop():
    t = _diff3(
        "| D12 | a | design | OURS |\n| D15 | c | design | x |",
        "",
        "| D12 | a | design | THEIRS |\n| D14 | b | design | y |",
    )
    status, lines, _ = resolve_file(t)
    ids = [l for l in lines if l.startswith("| D")]
    keys = [l.split("|")[1].strip() for l in ids]
    assert set(keys) == {"D12", "D14", "D15"}          # no row dropped
    assert any("THEIRS" in l for l in ids)             # theirs won the D12 conflict


def test_inventory_preserves_header_and_separator_lines():
    # Regression (Feynman CRITICAL #6): non-ID lines (header, separator, blanks) must survive.
    t = _diff3(
        "| Design | Name | Status |\n| --- | --- | --- |\n| D12 | a | OURS |",
        "",
        "| Design | Name | Status |\n| --- | --- | --- |\n| D12 | a | THEIRS |\n| D14 | b | y |",
    )
    _, lines, _ = resolve_file(t)
    text = "\n".join(lines)
    assert "| Design | Name | Status |" in text        # header not dropped
    assert "| --- | --- | --- |" in text               # separator not dropped
    assert "D14" in text and "THEIRS" in text


def test_xref_does_not_corrupt_urls_or_anchors():
    # Regression (Feynman MAJOR #4): L<n> inside an anchor/link must NOT be rewritten.
    t = _diff3(
        "### L4: ours",
        "",
        "### L4: theirs (prose ref see L5; anchor [L5](#L5-detail))\n### L5: detail body",
    )
    _, lines, _ = resolve_file(t)
    text = "\n".join(lines)
    # theirs L4->L5, L5->L6: bare prose ref 'see L5' becomes 'see L6'...
    assert "see L6" in text
    # ...but the anchor/link forms must be left intact (not corrupted to L6).
    assert "[L5](#L5-detail)" in text


def test_append_only_log_rule_unions_tails():
    # The append-only rule itself is correct (union of tails) — exercised directly.
    from classify import Hunk
    from resolve import resolve_append_log
    h = Hunk(ours=["x", "y", "ours-tail"], base=["x", "y"], theirs=["x", "y", "theirs-tail"])
    r = resolve_append_log(h)
    assert r.lines == ["x", "y", "ours-tail", "theirs-tail"]


def test_append_only_log_is_gated_to_human_by_default():
    # ...but the GATED policy defers it (no isolated ground-truth fixture yet).
    base = "x\ny"
    t = _diff3("x\ny\nours-tail", base, "x\ny\ntheirs-tail")
    status, lines, results = resolve_file(t)
    assert status == DEFER
    assert results[0].status == DEFER
    assert "gated" in results[0].reason
    assert "<<<<<<<" in "\n".join(lines)        # left for the human


def test_low_confidence_mechanical_hunk_defers():
    # A hunk classified mechanical but mixing a preamble line is not confident -> defer.
    from classify import Hunk, classify_hunk, is_confident
    h = Hunk(ours=["### L4: ours", "*Last updated: 2026-05-17*"], base=[],
             theirs=["### L4: theirs"])
    # classify sees the preamble first and labels it preamble (already semantic) — but to test the
    # confidence gate directly, force an id-renumber label on a mixed hunk:
    h2 = Hunk(ours=["### L4: ours", "| D9 | x | design | y |"], base=[], theirs=["### L4: theirs"])
    h2.label = "id-renumber-collision"
    assert is_confident(h2) is False
    from resolve import resolve_hunk
    r = resolve_hunk(h2)
    assert r.status == DEFER and "not confident" in r.reason


def test_semantic_defers_by_default():
    t = _diff3("Some prose A", "base", "Some prose B")
    status, lines, results = resolve_file(t)
    assert status == DEFER
    assert results[0].status == DEFER
    assert "<<<<<<<" in "\n".join(lines)   # markers preserved for the human


def test_force_bypasses_deferral():
    t = _diff3("Some prose A", "base", "Some prose B")
    status, lines, results = resolve_file(t, force=True)
    assert status == RESOLVED
    assert "Some prose B" in "\n".join(lines)
    assert "<<<<<<<" not in "\n".join(lines)


def test_mixed_file_resolves_mechanical_keeps_semantic_markers():
    t = _diff3("*Last updated: 2026-05-17*", "*Last updated: 2026-05-15*", "*Last updated: 2026-05-16*") + \
        "\nmid\n" + _diff3("### L4: ours", "", "### L4: theirs")
    status, lines, results = resolve_file(t)
    text = "\n".join(lines)
    assert status == DEFER                      # preamble keeps it from full-resolve
    assert "### L4: ours" in text and "### L5: theirs" in text   # mechanical hunk resolved
    assert "Last updated" in text and "<<<<<<<" in text          # semantic hunk still marked
