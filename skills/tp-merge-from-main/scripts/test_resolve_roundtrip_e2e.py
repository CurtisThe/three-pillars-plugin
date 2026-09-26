"""The S1 blank-line claim, driven END TO END through real `git merge-file --diff3` output.

Companion to `test_resolve_roundtrip.py`, split from it by responsibility: that module asserts the
`parse_conflict` -> `resolve_file` property against HAND-BUILT diff3 strings, which is the right
shape for a unit property but leaves the load-bearing sentence — "git's diff3 minimization leaves a
blank immediately before `<<<<<<<` on essentially every real markdown living-doc conflict" — as an
ASSERTION ABOUT GIT that nothing executes. A hand-written fixture proves the resolver is lossless
on a string the test author chose; it cannot prove git ever produces that string.

Everything here therefore goes through the real thing: an on-disk fixture repo, two diverging
commits on an allowlisted living doc, and the driver's own byte-production path
(`merge_driver.merge_back` -> `resolve_conflict_bytes_detail` -> `git merge-file --diff3`). The
assertion is byte-level, because the verifier cannot see this class at all: no atom kind is
blank-line-shaped and `_digest` excludes blank lines deliberately, so the pre-fix output was
VERIFIED and written to the worktree.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "_shared"))
import merge_driver  # noqa: E402
from test_merge_driver import commit, git, make_repo, write  # noqa: E402

from auto_safe_resolution import _diff3_conflict_text  # noqa: E402

ARCH = "three-pillars-docs/architecture.md"
HEAD = "# Architecture\n\nSome prose about the system.\n\n## History\n\n"
TAIL = "- **2026-01-01** — the previous entry\n"

BASE = HEAD + TAIL
OURS = HEAD + "- **2026-02-01** — ours appended this\n" + TAIL
THEIRS = HEAD + "- **2026-02-02** — theirs appended this\n" + TAIL


def _history_conflict_repo(tmp_path):
    """A REAL conflicted merge in the `## History` shape: both sides prepend a dated bullet under
    the same heading, which is the append-only-log class the mechanical lane exists for."""
    repo = make_repo(tmp_path)
    write(repo, ARCH, BASE)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, ARCH, OURS)
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, ARCH, THEIRS)
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    return repo


def test_git_really_does_leave_a_blank_line_before_the_marker():
    """The premise, executed rather than asserted. `git merge-file --diff3` minimizes the shared
    `## History` header out as the common prefix, so the clean segment it emits ends in the blank
    line that separates heading from list — exactly the segment the pre-fix `splitlines()` round
    trip ate one line off."""
    text = _diff3_conflict_text(base=BASE, ours=OURS, theirs=THEIRS)
    lines = text.split("\n")
    marker = next(i for i, ln in enumerate(lines) if ln.startswith("<<<<<<<"))
    assert lines[marker - 1] == "", (lines[marker - 3:marker + 1])
    assert lines[marker - 2] == "## History", (lines[marker - 3:marker + 1])


def test_the_blank_line_survives_the_real_driver_byte_for_byte(tmp_path):
    """The claim itself, on what actually reaches the worktree. Pre-fix the driver wrote
    `## History\\n- **2026-02-01**` — the blank silently deleted, and VERIFIED clean."""
    repo = _history_conflict_repo(tmp_path)
    report = merge_driver.merge_back(str(repo), "master")
    assert ARCH in report.auto_resolved, report.to_json()
    written = (repo / ARCH).read_bytes().decode("utf-8")
    assert "<<<<<<<" not in written, written
    assert written.startswith(HEAD), repr(written[:len(HEAD) + 40])
    assert "## History\n\n- **2026-0" in written, repr(written)
    # Both sides' bullets are kept, so the blank did not survive by the resolution being a no-op.
    assert "ours appended this" in written and "theirs appended this" in written


def test_every_clean_region_of_the_real_output_is_byte_identical(tmp_path):
    """Stronger than the one blank: the loss was one line PER clean segment, so the check is that
    the unconflicted regions of the file — head and tail — come back unchanged as bytes."""
    repo = _history_conflict_repo(tmp_path)
    merge_driver.merge_back(str(repo), "master")
    written = (repo / ARCH).read_bytes().decode("utf-8")
    assert written.startswith(HEAD) and written.endswith(TAIL), repr(written)
    # Blank-line count is conserved: the head's three blanks plus the trailing structure.
    assert written.count("\n\n") == OURS.count("\n\n"), repr(written)
