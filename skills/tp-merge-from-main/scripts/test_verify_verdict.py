"""Three-state verdict tests for the zero-drop verifier (VERIFIED / DROPS_DETECTED / UNVERIFIABLE).

The no-op regression this pins: a file the resolver *mechanically resolved* from which the verifier
parsed ZERO atoms used to return `(True, [])` and read as ZERO-DROP — "I examined nothing" was
indistinguishable from "I examined atoms and none were lost". It is now `UNVERIFIABLE`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import verify as _verify  # noqa: E402
from verify import DROPS_DETECTED, UNVERIFIABLE, VERIFIED, verify  # noqa: E402

PROSE_OURS = "Some prose here that changed."
PROSE_THEIRS = "Other prose entirely."
PROSE_RESOLVED = "A synthesized human resolution."


def test_zero_atoms_with_mechanical_applied_is_unverifiable():
    # The design's no-op regression: mechanically resolved + zero atoms is NEVER a pass.
    r = verify(PROSE_OURS, PROSE_THEIRS, PROSE_RESOLVED, mechanical_applied=True)
    assert r.verdict == UNVERIFIABLE
    assert r.ok is False


def test_zero_atoms_without_mechanical_applied_is_verified():
    # Behavior 2 — a deferred / hand-resolved prose-only file is not blocked by the verifier.
    r = verify(PROSE_OURS, PROSE_THEIRS, PROSE_RESOLVED, mechanical_applied=False)
    assert r.verdict == VERIFIED
    assert r.ok is True
    assert r.dropped == []


def test_verified_and_drops_detected_verdicts():
    ours = "### L4: keep me"
    theirs = "### L4: also keep\n### L5: and me"
    good = verify(ours, theirs, "### L4: keep me\n### L5: also keep\n### L6: and me",
                  mechanical_applied=True)
    assert good.verdict == VERIFIED and good.ok and good.dropped == []

    bad = verify(ours, theirs, "### L4: also keep\n### L5: and me", mechanical_applied=True)
    assert bad.verdict == DROPS_DETECTED
    assert bad.ok is False
    assert any("keep me" in sig for _kind, sig in bad.dropped)


def test_drops_detected_wins_over_unverifiable_only_when_atoms_exist():
    # DROPS_DETECTED requires atoms; with atoms present, mechanical_applied cannot make it
    # UNVERIFIABLE — UNVERIFIABLE is strictly the zero-atom verdict.
    r = verify("### L4: a", "", "", mechanical_applied=True)
    assert r.verdict == DROPS_DETECTED and r.pre_atoms == 1


def test_result_carries_atom_counts():
    ours = "### L4: keep me\n\nprose line"
    theirs = "### L5: and me"
    r = verify(ours, theirs, "### L4: keep me\n### L5: and me", mechanical_applied=True)
    assert r.pre_atoms == 2
    assert r.post_atoms == 2
    assert r.ours_lines == 2          # blank line not counted
    assert r.theirs_lines == 1

    empty = verify(PROSE_OURS, PROSE_THEIRS, PROSE_RESOLVED, mechanical_applied=True)
    assert empty.pre_atoms == 0 and empty.post_atoms == 0
    assert empty.ours_lines == 1 and empty.theirs_lines == 1


def test_mechanical_applied_is_keyword_only_with_no_default():
    # Fail-loud device: an unmigrated 3-positional call must raise, never silently default.
    try:
        verify(PROSE_OURS, PROSE_THEIRS, PROSE_RESOLVED)
    except TypeError:
        pass
    else:
        raise AssertionError("verify() must require keyword-only mechanical_applied")


def test_result_is_frozen():
    r = verify(PROSE_OURS, PROSE_THEIRS, PROSE_RESOLVED, mechanical_applied=False)
    try:
        r.verdict = UNVERIFIABLE          # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("VerifyResult must be immutable")
    assert isinstance(_verify.VerifyResult, type)


# ---- Task 1.2: CLI exit codes + message shape ------------------------------------------------

def _triple(tmp_path, ours, theirs, resolved):
    tmp_path.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, text in (("ours", ours), ("theirs", theirs), ("resolved", resolved)):
        p = tmp_path / f"{name}.md"
        p.write_text(text, encoding="utf-8")
        paths.append(str(p))
    return paths


def test_cli_exit_codes_are_0_1_2(tmp_path, capsys):
    clean = _triple(tmp_path / "a", "### L4: keep me", "### L5: and me",
                    "### L4: keep me\n### L5: and me")
    assert _verify._main(clean) == 0
    assert "ZERO-DROP" in capsys.readouterr().out

    dropped = _triple(tmp_path / "b", "### L4: keep me", "### L5: and me", "### L5: and me")
    assert _verify._main(dropped) == 1
    assert "DROPS DETECTED (1):" in capsys.readouterr().out

    unknown = _triple(tmp_path / "c", PROSE_OURS, PROSE_THEIRS, PROSE_RESOLVED)
    # Without the flag the shape is simply unrecognised on a lane that never applied a
    # mechanical resolution — exit 0, per design Behavior 2.
    assert _verify._main(unknown) == 0
    capsys.readouterr()
    assert _verify._main(unknown + ["--mechanical-applied"]) == 2


def test_cli_unverifiable_message_shape(tmp_path, capsys):
    ours = "prose one\n\nprose two"          # 2 non-blank lines
    theirs = "just one prose line"           # 1 non-blank line
    argv = _triple(tmp_path, ours, theirs, "a human synthesis") + ["--mechanical-applied"]
    assert _verify._main(argv) == 2
    out = capsys.readouterr().out
    assert out.strip() == (
        "UNVERIFIABLE — 0 atoms parsed from ours∪theirs (2/1 non-blank lines); "
        "this file's shape is unknown to the verifier."
    )
    assert "ZERO-DROP" not in out
