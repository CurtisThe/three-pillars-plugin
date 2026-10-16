"""Behavior 8 — an atom a side moved into its archive is not a drop (`archive_moves.py`).
Pure texts first (moves, fail-closed drops, the operator's hardening), then the readers:
`archives_at`, `seam_archives` over a fake git seam, `driver_archives` over a throwaway repo."""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import verify  # noqa: E402
from archive_moves import (  # noqa: E402
    ID_HEADING, ArchiveTexts, archives_at, driver_archives, moved_atoms, seam_archives,
    verify_with_moves,
)
from verify import DROPS_DETECTED, UNVERIFIABLE, VERIFIED  # noqa: E402

KI = "three-pillars-docs/known_issues.md"
ARCH = "three-pillars-docs/known_issues_resolved.md"
M47_BODY = "The lock is never swept after a crash.\n"
M47 = "### M47: stale lock is never swept\n" + M47_BODY + "\n"
M47_ATOM = ("entry", "stale lock is never swept")
M50 = "### M50: other\n"
DUP = "### M48: stale lock is never swept\n" + M47_BODY + "\n"
KI_BASE = "# Known issues\n\n" + M47 + M50
KI_WITHOUT = "# Known issues\n\n" + M50
ARCH_BASE = "# Known Issues — RESOLVED archive\n"
RESOLVED = "\n### M47 (RESOLVED 2026-10-01): stale lock is never swept\n" + M47_BODY
ARCH_M47 = ARCH_BASE + RESOLVED
THEIRS_ARCH = ArchiveTexts(ARCH_BASE, ARCH_BASE, ARCH_M47)

LOG = "- **2026-09-28** — x\n"
LOG_ATOM = ("log", "2026-09-28 — x")
RM_BASE = "# Roadmap\n\n## History\n\n" + LOG + "- **2026-09-29** — y\n"
RM_WITHOUT = "# Roadmap\n\n## History\n\n- **2026-09-29** — y\n"
RM_ARCH = "# Product Roadmap — Archive\n"
RM_ARCH_LOG = RM_ARCH + "\n" + LOG


def moves(base, ours, theirs, resolved, arch):
    return verify_with_moves(base, ours, theirs, resolved, mechanical_applied=True,
                             archives=lambda: arch)


# --- moves that leave the drop list -------------------------------------------------------------

def test_theirs_moved_issue_entry_into_its_resolved_archive():
    plain = verify.verify(KI_BASE, KI_WITHOUT, KI_WITHOUT, base=None, mechanical_applied=True)
    assert plain.verdict == DROPS_DETECTED and plain.dropped == [M47_ATOM]
    r = moves(KI_BASE, KI_BASE, KI_WITHOUT, KI_WITHOUT, THEIRS_ARCH)
    assert r.verdict == VERIFIED and r.dropped == [] and r.ok is True


TWO_COPIES = "# K\n\n" + M47 + DUP + M50
TWIN = "# K\n\n" + M47 + M47 + M50
K_M50 = "# K\n\n" + M50
TWINS_ARCH = ArchiveTexts(ARCH_BASE, ARCH_BASE, ARCH_M47 + RESOLVED)    # two M47 headings
BOTH_ARCHIVED = (ARCH_M47 + "\n### M48 (RESOLVED 2026-10-01): stale lock is never swept\n"
                 + M47_BODY)


@pytest.mark.parametrize("base, ours, theirs, resolved, arch", [
    pytest.param(RM_BASE, RM_BASE, RM_WITHOUT, RM_WITHOUT, ArchiveTexts(RM_ARCH, RM_ARCH,
                 RM_ARCH_LOG), id="theirs-history-line-exact-text"),
    pytest.param(KI_BASE, KI_WITHOUT, KI_BASE, KI_WITHOUT, ArchiveTexts(ARCH_BASE, ARCH_M47,
                 ARCH_BASE), id="mirror-ours-moved-the-entry"),
    pytest.param(RM_BASE, RM_WITHOUT, RM_BASE, RM_WITHOUT, ArchiveTexts(RM_ARCH, RM_ARCH_LOG,
                 RM_ARCH), id="mirror-ours-moved-the-history-line"),
    pytest.param(KI_BASE, KI_BASE, KI_WITHOUT, KI_WITHOUT, ArchiveTexts("", "", ARCH_M47),
                 id="archive-absent-at-merge-base-reads-empty"),
    pytest.param(TWO_COPIES, TWO_COPIES, K_M50, K_M50,
                 ArchiveTexts(ARCH_BASE, ARCH_BASE, BOTH_ARCHIVED), id="both-copies-moved"),
    pytest.param(TWIN, TWIN, K_M50, K_M50, TWINS_ARCH, id="both-identical-twins-moved"),
    pytest.param(RM_BASE + LOG, RM_BASE + LOG, RM_WITHOUT, RM_WITHOUT,
                 ArchiveTexts(RM_ARCH, RM_ARCH, RM_ARCH_LOG + LOG), id="both-log-copies-moved"),
])
def test_a_move_is_not_a_drop(base, ours, theirs, resolved, arch):
    assert verify.verify(ours, theirs, resolved, base=None, mechanical_applied=True).dropped
    r = moves(base, ours, theirs, resolved, arch)
    assert r.verdict == VERIFIED and r.dropped == []


# --- fail-closed: these stay drops --------------------------------------------------------------

M12_ARCH = ARCH_BASE + "\n### M12: stale lock is never swept\nold copy\n"
M4_BASE = "# K\n\n### M4: t\nbody\n\n" + M50
RETITLED = "# Known issues\n\n### M47: renamed title\n" + M47_BODY + "\n" + M50
EDITED = KI_BASE.replace(M47_BODY, "The lock is swept now.\n")
APPENDED = KI_BASE.replace(M47, M47 + "An extra note ours appended.\n\n")
assert M47 in APPENDED            # the base block is a substring of ours: must still be a drop


@pytest.mark.parametrize("base, ours, theirs, arch, atom", [
    pytest.param(KI_BASE, KI_BASE, KI_WITHOUT, ArchiveTexts(ARCH_BASE, ARCH_BASE, ARCH_BASE),
                 M47_ATOM, id="deleted-with-no-archive-copy"),
    pytest.param(KI_BASE, KI_BASE, KI_WITHOUT, ArchiveTexts(ARCH_M47, ARCH_M47, ARCH_M47),
                 M47_ATOM, id="base-archive-held-the-id-heading"),
    pytest.param(KI_BASE, KI_BASE, KI_WITHOUT, ArchiveTexts(M12_ARCH, M12_ARCH,
                 M12_ARCH + RESOLVED), M47_ATOM, id="base-archive-held-the-exact-atom"),
    pytest.param(RM_BASE, RM_BASE, RM_WITHOUT, ArchiveTexts(RM_ARCH_LOG, RM_ARCH_LOG,
                 RM_ARCH_LOG), LOG_ATOM, id="base-archive-held-the-log-line"),
    pytest.param(KI_BASE, EDITED, KI_WITHOUT, THEIRS_ARCH, M47_ATOM, id="other-side-edited-body"),
    pytest.param(KI_WITHOUT, KI_BASE, KI_WITHOUT, THEIRS_ARCH, M47_ATOM, id="lost-addition"),
    pytest.param(M4_BASE, M4_BASE, K_M50, ArchiveTexts(ARCH_BASE, ARCH_BASE, ARCH_BASE
                 + "\n### M47 (RESOLVED 2026-10-01): t\n"), ("entry", "t"), id="id-prefix-guard"),
    pytest.param(KI_BASE, KI_BASE, KI_WITHOUT, ArchiveTexts(ARCH_BASE, ARCH_M47, ARCH_BASE),
                 M47_ATOM, id="only-the-removing-sides-archive-counts"),
    pytest.param(KI_BASE, KI_BASE, KI_WITHOUT, ArchiveTexts(None, ARCH_BASE, ARCH_M47),
                 M47_ATOM, id="unreadable-base-archive"),
    pytest.param(KI_BASE, KI_BASE, KI_WITHOUT, ArchiveTexts(ARCH_BASE, ARCH_BASE, None),
                 M47_ATOM, id="unreadable-removing-archive"),
    pytest.param(KI_BASE, KI_BASE, KI_WITHOUT, ArchiveTexts("", "", ""), M47_ATOM,
                 id="removing-archive-absent"),
    # hardening (a): a signature several lines yield needs equal counts in base and the other side
    pytest.param(KI_BASE, KI_BASE + DUP, KI_WITHOUT, THEIRS_ARCH, M47_ATOM,
                 id="a-same-title-entry-the-other-side-added"),
    pytest.param(TWO_COPIES, "# K\n\n" + M47 + M50, K_M50, THEIRS_ARCH, M47_ATOM,
                 id="a-base-duplicate-the-other-side-deleted"),
    pytest.param(TWO_COPIES, TWO_COPIES, K_M50, THEIRS_ARCH, M47_ATOM, id="base-dup-one-archived"),
    pytest.param(TWIN, TWIN, K_M50, THEIRS_ARCH, M47_ATOM, id="twin-ids-one-archived-heading"),
    pytest.param(TWIN, "# K\n\n" + M47 + M50, K_M50, TWINS_ARCH, M47_ATOM,
                 id="an-identical-base-twin-the-other-side-deleted"),
    pytest.param(RM_BASE + LOG, RM_BASE + LOG, RM_WITHOUT, ArchiveTexts(RM_ARCH, RM_ARCH,
                 RM_ARCH_LOG), LOG_ATOM, id="a-duplicated-log-line-with-one-archived-copy"),
    # hardening (b): the other side's cut block must EQUAL the base block, never contain it
    pytest.param(KI_BASE, APPENDED, KI_WITHOUT, THEIRS_ARCH, M47_ATOM,
                 id="other-side-appended-a-non-atom-body-line"),
    pytest.param(KI_BASE, KI_BASE.replace(M47, M47 + "\n"), KI_WITHOUT, THEIRS_ARCH, M47_ATOM,
                 id="other-side-changed-the-blank-line-tail"),
])
def test_it_stays_a_drop(base, ours, theirs, arch, atom):
    r = moves(base, ours, theirs, theirs, arch)
    assert r.verdict == DROPS_DETECTED and atom in r.dropped


def _boom():
    raise RuntimeError("git went away")


@pytest.mark.parametrize("loader", [None, lambda: None, _boom], ids=["no-loader",
                         "loader-returns-none", "loader-raises"])
def test_a_missing_failing_or_empty_loader_leaves_every_drop(loader):
    r = verify_with_moves(KI_BASE, KI_BASE, KI_WITHOUT, KI_WITHOUT, mechanical_applied=True,
                          archives=loader)
    assert r.verdict == DROPS_DETECTED and r.dropped == [M47_ATOM]


def test_partial_one_moved_atom_and_one_plain_drop_calls_the_loader_once():
    calls, base, theirs = [], "# K\n\n" + M47 + M50 + "\n", "# K\n"   # M50 plainly dropped
    plain = verify.verify(base, theirs, theirs, base=None, mechanical_applied=True)
    assert len(plain.dropped) == 2
    r = verify_with_moves(base, base, theirs, theirs, mechanical_applied=True,
                          archives=lambda: calls.append(1) or THEIRS_ARCH)
    assert r.verdict == DROPS_DETECTED and r.dropped == [("entry", "other")]
    assert (r.pre_atoms, r.post_atoms) == (plain.pre_atoms, plain.post_atoms)
    assert calls == [1]


def test_verified_and_unverifiable_pass_through_and_never_read_the_archives():
    calls = []
    loader = lambda: calls.append(1) or THEIRS_ARCH  # noqa: E731
    clean = verify_with_moves(KI_BASE, KI_BASE, KI_BASE, KI_BASE, mechanical_applied=True,
                              archives=loader)
    assert clean == verify.verify(KI_BASE, KI_BASE, KI_BASE, base=None, mechanical_applied=True)
    assert clean.verdict == VERIFIED
    prose = "no atoms here\n"
    unv = verify_with_moves(prose, prose, prose, "x\n", mechanical_applied=True, archives=loader)
    assert unv == verify.verify(prose, prose, "x\n", base=None, mechanical_applied=True)
    assert unv.verdict == UNVERIFIABLE
    assert calls == []


def test_moved_atoms_names_only_the_moved_atom_and_none_without_archives():
    kw = dict(base=KI_BASE, ours=KI_BASE, theirs=KI_WITHOUT)
    assert moved_atoms([M47_ATOM, ("entry", "other")], archives=THEIRS_ARCH, **kw) == {M47_ATOM}
    assert moved_atoms([M47_ATOM], archives=None, **kw) == set()


def test_id_heading_matches_h_m_l_ids_only_as_a_whole_number():
    found = ID_HEADING.findall(
        "### M47 (RESOLVED x): t\n### M4: t\n### H12: t\n### L3\n### X1: t\n### M: t\n")
    assert found == ["M47", "M4", "H12", "L3"]


# --- readers: archives_at, seam_archives (fake seam), driver_archives (real repo) ---------------

def test_archives_at_reads_the_archive_at_base_ours_and_theirs():
    seen = []
    got = archives_at(KI, ("b", "o", "t"), lambda rev, p: seen.append((rev, p)) or f"@{rev}")
    assert seen == [("b", ARCH), ("o", ARCH), ("t", ARCH)]
    assert got == ArchiveTexts("@b", "@o", "@t")
    assert archives_at(KI, ("b", "o", "t"), lambda rev, p: None if rev == "o" else "x") is None


@pytest.mark.parametrize("path", [ARCH, "README.md"])
def test_archives_at_a_path_without_an_archive_is_none_and_reads_nothing(path):
    seen = []
    assert archives_at(path, ("b", "o", "t"), lambda rev, p: seen.append(rev)) is None
    assert seen == []


ERR = object()          # ls-tree fails: a real git error, not "absent"
SHOW_ERR = object()     # the path exists but `git show` fails
BLOBS = {("mb0", ARCH): "base", ("h0", ARCH): "ours", ("p2", ARCH): "theirs"}


def fake_git(blobs, merge_base=(0, "mb0\n"), calls=None):
    """A `git(args) -> (rc, out, err)` seam over {(rev, path): str | bytes | ERR | SHOW_ERR}."""
    calls = [] if calls is None else calls

    def git(args):
        calls.append(list(args))
        if args[0] == "merge-base":
            return (merge_base[0], merge_base[1], "")
        if args[0] == "ls-tree":
            got = blobs.get((args[-3], args[-1]))
            if got is ERR:
                return (128, "", "fatal: not a tree object")
            return (0, "" if got is None else f"100644 blob abc\t{args[-1]}\n", "")
        rev, _, path = args[1].partition(":")
        got = blobs[(rev, path)]
        if got is SHOW_ERR:
            return (128, "", "fatal: cannot read")
        raw = got.encode() if isinstance(got, str) else got
        return (0, raw.decode("utf-8", "surrogateescape"), "")

    return git


def test_seam_archives_with_one_merge_base_reads_the_three_blobs():
    calls = []
    loader = seam_archives(fake_git(BLOBS, calls=calls), KI, ("h0", "p2"))
    assert calls == []                                   # nothing runs until the loader is called
    assert loader() == ArchiveTexts("base", "ours", "theirs")
    assert calls[0] == ["merge-base", "--all", "h0", "p2"]
    assert [c[1] for c in calls if c[0] == "show"] == [f"mb0:{ARCH}", f"h0:{ARCH}", f"p2:{ARCH}"]


def test_seam_archives_an_archive_absent_at_a_rev_reads_as_empty_text():
    blobs = {("h0", ARCH): "ours", ("p2", ARCH): "theirs"}          # absent at the merge base
    assert seam_archives(fake_git(blobs), KI, ("h0", "p2"))() == ArchiveTexts("", "ours", "theirs")
    assert seam_archives(fake_git({}), KI, ("h0", "p2"))() == ArchiveTexts("", "", "")


@pytest.mark.parametrize("merge_base", [(0, "a\nb\n"), (1, ""), (128, "a\n"), (0, ""), (0, " \n")])
def test_seam_archives_without_a_single_merge_base_is_none(merge_base):
    assert seam_archives(fake_git(BLOBS, merge_base=merge_base), KI, ("h0", "p2"))() is None


@pytest.mark.parametrize("key, bad", [(("p2", ARCH), ERR), (("mb0", ARCH), ERR),
                                      (("h0", ARCH), SHOW_ERR), (("h0", ARCH), b"\xff\xfe x")],
                         ids=["ls-tree-error-side", "ls-tree-error-base", "show-error",
                              "undecodable-blob"])
def test_seam_archives_a_git_or_decode_failure_other_than_absence_is_none(key, bad):
    assert seam_archives(fake_git({**BLOBS, key: bad}), KI, ("h0", "p2"))() is None


def test_seam_archives_without_sides_or_an_archive_never_calls_git():
    calls = []
    assert seam_archives(fake_git({}, calls=calls), KI, None) is None
    assert seam_archives(fake_git({}, calls=calls), ARCH, ("h0", "p2"))() is None
    assert calls == []


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repo whose `side` branch moved M47 into the archive, absent at base and on `main`."""
    for var in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
        monkeypatch.delenv(var, raising=False)
    repo = tmp_path

    def git(*args):
        cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(repo), *args]
        subprocess.run(cmd, capture_output=True, text=True, check=True)

    git("init", "-q", "-b", "main")
    (repo / "three-pillars-docs").mkdir()
    (repo / KI).write_text("### M47: t\nbody\n\n### M50: o\n")
    (repo / "unrelated.txt").write_text("a\n")
    git("add", ".")
    git("commit", "-q", "-m", "base")
    git("checkout", "-q", "-b", "side")
    (repo / KI).write_text("### M50: o\n")
    (repo / ARCH).write_text("### M47 (RESOLVED 2026-10-01): t\nbody\n")
    git("add", ".")
    git("commit", "-q", "-m", "side moves M47")
    git("checkout", "-q", "main")
    (repo / "unrelated.txt").write_text("b\n")
    git("commit", "-q", "-am", "main edit")
    return repo, git


def test_driver_archives_reads_head_merge_head_and_the_single_merge_base(repo):
    repo, git = repo
    assert driver_archives(repo, KI)() is None           # no merge in progress: no MERGE_HEAD
    git("merge", "--no-commit", "--no-ff", "side")
    moved = "### M47 (RESOLVED 2026-10-01): t\nbody\n"
    assert driver_archives(repo, KI)() == ArchiveTexts("", "", moved)
