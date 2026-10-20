"""Multi-root scratch for reviewer_delete_guard (design delete-fence-own-tree 1.1).

`classify(cmd, scratch=...)` takes one root, a list of roots, or a callable
returning either. A path is allowed when it is strictly inside at least one
root. Fixtures live under tmp_path; no command is ever executed.
"""
import pytest

from reviewer_delete_guard import classify


@pytest.fixture
def roots(tmp_path):
    r1, r2, out = tmp_path / "r1", tmp_path / "r2", tmp_path / "out"
    for d in (r1, r2, out):
        d.mkdir()
    (r1 / "a.txt").write_text("")
    (r1 / "b.txt").write_text("")
    (r2 / "x").mkdir()
    (out / "keep").write_text("")
    return str(r1), str(r2), str(out)


def _v(cmd, roots, cwd=None, scratch="multi"):
    r1, r2, out = roots
    cmd = cmd.replace("<R1>", r1).replace("<R2>", r2).replace("<O>", out)
    cwd = cwd.replace("<R1>", r1).replace("<R2>", r2) if cwd else (cwd or r1)
    sc = [r1, r2] if scratch == "multi" else scratch
    return classify(cmd, scratch=sc, cwd=cwd)


def test_first_root_allowed(roots):
    assert _v("rm -rf <R1>/x", roots).allowed


def test_second_root_allowed_nested(roots):
    assert _v("rm -rf <R2>/x/y", roots).allowed


def test_outside_all_roots_denied(roots):
    verdict = _v("rm -rf <O>/x", roots)
    assert not verdict.allowed
    assert "outside scratch" in verdict.reason


def test_root_itself_denied(roots):
    assert not _v("rm -rf <R1>", roots).allowed


def test_relative_operand_follows_cwd_into_second_root(roots):
    assert _v("rm -rf x", roots, cwd="<R2>").allowed


def test_any_operand_outside_denies(roots):
    assert not _v("rm -rf <R1>/x <O>/y", roots).allowed


def test_glob_inside_a_root_allowed(roots):
    assert _v("rm <R1>/*.txt", roots).allowed


def test_empty_root_list_is_no_scratch(roots):
    verdict = _v("rm -rf <R1>/x", roots, scratch=[])
    assert not verdict.allowed
    assert "no scratch known" in verdict.reason


def test_none_scratch_is_no_scratch(roots):
    verdict = _v("rm -rf <R1>/x", roots, scratch=None)
    assert not verdict.allowed
    assert "no scratch known" in verdict.reason


def test_callable_returning_list(roots):
    r1, r2, _out = roots
    assert _v("rm -rf <R2>/x", roots, scratch=lambda: [r1, r2]).allowed
    assert not _v("rm -rf <O>/x", roots, scratch=lambda: [r1, r2]).allowed


def test_callable_returning_single_root(roots):
    r1 = roots[0]
    assert _v("rm -rf <R1>/x", roots, scratch=lambda: r1).allowed
    assert not _v("rm -rf <R2>/x", roots, scratch=lambda: r1).allowed


def test_plain_string_root_behaves_as_before(roots):
    r1, r2 = roots[0], roots[1]
    assert _v("rm -rf <R1>/x", roots, scratch=r1).allowed
    assert not _v("rm -rf <R2>/x", roots, scratch=r1).allowed
    assert not _v("rm -rf <R1>", roots, scratch=r1).allowed


def test_single_root_reason_strings_stay_byte_for_byte(roots):
    r1, out = roots[0], roots[2]
    assert _v("rm -rf <R1>", roots, scratch=r1).reason == \
        "rm outside scratch: outside scratch: " + r1
    assert _v("rm -rf <O>/x", roots, scratch=r1).reason == \
        "rm outside scratch: outside scratch: " + out + "/x"
    assert _v("rm $D/x", roots, scratch=r1).reason == \
        "rm outside scratch: unprovable operand '$D/x' (expansion)"
    assert _v("find <R2> -delete", roots, scratch=r1).reason == \
        "find outside scratch: outside scratch: " + roots[1]


def test_multiroot_destructive_forms(roots):
    assert _v("find <R2>/x -delete", roots).allowed
    assert _v("mv <R1>/a.txt <R2>/a.txt", roots).allowed
    assert not _v("mv <O>/keep <R1>/keep", roots).allowed
    assert not _v("rsync -a --delete <R1>/ <O>/", roots).allowed
