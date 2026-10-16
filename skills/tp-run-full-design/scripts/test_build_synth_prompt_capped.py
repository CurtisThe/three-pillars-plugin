"""Tests for build_synth_prompt capped_members (review-convergence 7.6).

Design: capped council members (either cheap engine hit the hard limit) are
marked in the synth prompt so the synthesizer copies `capped: true` onto their
escape_dispositions[] items. See skills/_shared/test-fragility.md — assert the
exact line, not a substring of the whole prompt.
"""

from build_synth_prompt import build_synth_prompt


def _args():
    r1 = [{"member": "council-ada", "verdict": "pass-with-notes", "findings": []}]
    return (["a.md"], r1, None, "plan-audit")


def _capped(out):
    return [ln for ln in out.splitlines() if ln.startswith("Capped at the hard limit:")]


def test_capped_line_names_member_on_either_engine():
    for engine in ("opus", "local"):
        out = build_synth_prompt(*_args(), member_engine=engine, capped_members=("feynman",))
        lines = _capped(out)
        assert len(lines) == 1
        assert lines[0].startswith("Capped at the hard limit: feynman")
        assert "capped: true" in lines[0]
        assert "escape_dispositions[]" in lines[0]


def test_empty_capped_leaves_output_unchanged():
    base = build_synth_prompt(*_args())
    assert build_synth_prompt(*_args(), capped_members=()) == base
    assert "Capped at the hard limit" not in base


def test_busy_and_capped_lines_both_appear():
    out = build_synth_prompt(*_args(), member_engine="local",
                             busy_members=["council-ada"], capped_members=("feynman",))
    assert "Sonnet-served (slot busy): council-ada" in out.splitlines()
    assert len(_capped(out)) == 1
