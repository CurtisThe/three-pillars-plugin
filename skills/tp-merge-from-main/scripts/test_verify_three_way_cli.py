"""The standalone verifier's optional merge base: `verify.py ... --base PATH` and `verify_paths(base_p=)`.

Spec: basesync-three-way-verifier detailed-design.md Interfaces (`verify.verify_paths` / CLI).
`--base` is optional; without it the check is two-way and today's verdicts are unchanged. The exit
codes keep their meanings (0 zero-drop, 1 drops, 2 unverifiable, 3 usage or read error), and an
unreadable `--base` is exit 3 (a read error, not a drop or a usage error). The CLI runs as a subprocess on files in `tmp_path`;
expectations are hand-traced from the spec (skills/_shared/test-fragility.md).
"""
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from verify import DROPS_DETECTED, VERIFIED, verify_paths  # noqa: E402

VERIFY = HERE / "verify.py"

BASE = "### M44: Old title\nbody\n"                              # the merge base
RETITLED = "### M44 (RESOLVED 2026-09-30): New title\nbody\n"    # one side retitles in place
EXCUSED = [("entry", "old title")]                                # the base atom that retitle excuses
PROSE = "Some prose, no atoms at all.\n"


def write(tmp_path, **files):
    paths = {}
    for name, text in files.items():
        paths[name] = tmp_path / f"{name}.md"
        paths[name].write_text(text, encoding="utf-8")
    return paths


def run(*args):
    return subprocess.run([sys.executable, str(VERIFY), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8")


def retitle_files(tmp_path):
    """Ours is untouched, theirs retitles the entry, and the resolution takes theirs."""
    return write(tmp_path, base=BASE, ours=BASE, theirs=RETITLED, resolved=RETITLED)


# --- the CLI ------------------------------------------------------------------------------------

def test_a_one_side_retitle_exits_0_with_a_base(tmp_path):
    p = retitle_files(tmp_path)
    r = run(p["ours"], p["theirs"], p["resolved"], "--base", p["base"])
    assert (r.returncode, r.stdout.strip()) == (0, "ZERO-DROP")


def test_the_same_retitle_without_a_base_exits_1(tmp_path):
    p = retitle_files(tmp_path)
    r = run(p["ours"], p["theirs"], p["resolved"])
    assert r.returncode == 1


def test_the_changing_sides_new_atoms_must_still_survive_with_a_base(tmp_path):
    p = write(tmp_path, base=BASE, ours=BASE, theirs=RETITLED, resolved="nothing left\n")
    r = run(p["ours"], p["theirs"], p["resolved"], "--base", p["base"])
    assert r.returncode == 1


def test_an_unreadable_base_path_exits_3(tmp_path):
    p = retitle_files(tmp_path)
    r = run(p["ours"], p["theirs"], p["resolved"], "--base", tmp_path / "no-such-base.md")
    assert (r.returncode, "cannot read input" in r.stderr) == (3, True)   # not an argparse usage error


def test_an_undecodable_base_exits_3(tmp_path):
    p = retitle_files(tmp_path)
    p["base"].write_bytes(b"\xff\xfe\x00 not utf-8 \x80\n")
    r = run(p["ours"], p["theirs"], p["resolved"], "--base", p["base"])
    assert (r.returncode, "cannot read input" in r.stderr) == (3, True)


def test_an_atomless_file_with_a_base_is_still_unverifiable(tmp_path):
    p = write(tmp_path, base=PROSE, ours=PROSE, theirs=PROSE, resolved=PROSE)
    r = run(p["ours"], p["theirs"], p["resolved"], "--mechanical-applied", "--base", p["base"])
    assert r.returncode == 2


def test_an_atomless_file_with_a_base_is_a_pass_when_nothing_mechanical_was_applied(tmp_path):
    p = write(tmp_path, base=PROSE, ours=PROSE, theirs=PROSE, resolved=PROSE)
    r = run(p["ours"], p["theirs"], p["resolved"], "--base", p["base"])
    assert r.returncode == 0


# --- verify_paths -------------------------------------------------------------------------------

def test_verify_paths_with_base_p_populates_excused(tmp_path):
    p = retitle_files(tmp_path)
    r = verify_paths(p["ours"], p["theirs"], p["resolved"], mechanical_applied=True,
                     base_p=p["base"])
    assert (r.verdict, r.dropped, r.excused) == (VERIFIED, [], EXCUSED)


def test_verify_paths_accepts_the_base_as_a_str(tmp_path):
    p = retitle_files(tmp_path)
    r = verify_paths(str(p["ours"]), str(p["theirs"]), str(p["resolved"]),
                     mechanical_applied=True, base_p=str(p["base"]))
    assert (r.verdict, r.excused) == (VERIFIED, EXCUSED)


def test_verify_paths_without_base_p_is_the_two_way_check(tmp_path):
    p = retitle_files(tmp_path)
    r = verify_paths(p["ours"], p["theirs"], p["resolved"], mechanical_applied=True)
    assert (r.verdict, r.dropped, r.excused) == (DROPS_DETECTED, EXCUSED, [])


def test_verify_paths_base_p_is_keyword_only(tmp_path):
    p = retitle_files(tmp_path)
    with pytest.raises(TypeError):
        verify_paths(p["ours"], p["theirs"], p["resolved"], True, p["base"])


def test_verify_paths_raises_on_an_unreadable_base(tmp_path):
    p = retitle_files(tmp_path)
    with pytest.raises(OSError):
        verify_paths(p["ours"], p["theirs"], p["resolved"], mechanical_applied=True,
                     base_p=tmp_path / "no-such-base.md")
