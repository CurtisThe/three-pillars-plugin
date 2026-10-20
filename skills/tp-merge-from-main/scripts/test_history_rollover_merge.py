"""`merge_back` end to end on a plain-date History rollover (Behaviors 8, 9, 10).

The 2026-10-16 stalls were `product_roadmap.md` History hunks whose bullets carry a PLAIN date
(`- 2026-10-16 — …`) and whose rollover REMOVES bullets that the same side adds to its archive
sibling. These tests drive the real driver (`merge_back`) over throwaway git repos holding a
living doc and its archive, so the whole chain — parse, classify, resolve, the stage oracle, the
zero-drop verifier with the archive-move rule — is what is under test, not one predicate.

Rule: skills/_shared/test-fragility.md — behaviour only (report buckets, resulting file text,
verifier verdict), never markdown wording.
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
from archive_moves import ArchiveTexts, driver_archives, verify_with_moves  # noqa: E402
from merge_driver import merge_back  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402  # shipped scrub; git_env is dev-only
from verify import VERIFIED  # noqa: E402

LIVE = "three-pillars-docs/product_roadmap.md"
ARCH = "three-pillars-docs/product_roadmap_archive.md"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

A = "- 2026-10-10 — first rollover entry\n"
B = "- 2026-10-09 — second rollover entry\n"
X = "- 2026-10-15 — ours new entry\n"
Y = "- 2026-10-14 — theirs new entry\n"
OLD = "- 2026-10-08 — still in the live doc\n"
S = "- 2026-10-13 — a bullet both sides added\n"
A_OURS = "- 2026-10-10 — first rollover entry EDITED BY OURS\n"
A_THEIRS = "- 2026-10-10 — first rollover entry EDITED BY THEIRS\n"

LIVE_BASE = f"# Product Roadmap\n\n## History\n\n{A}{B}{OLD}"
ARCH_BASE = "# Product Roadmap — Archive\n\n## History\n\n- 2026-09-01 — ancient entry\n"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, env=clean_git_env(**IDENTITY))


def write(repo, rel, content):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def setup(tmp_path, branch_live: str, branch_arch: str, master_live: str, master_arch: str):
    """Base commit, then a `feat` side and a `master` side, then check out `feat` so `merge_back`
    merges master into the design branch exactly as the driver is used."""
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    write(repo, LIVE, LIVE_BASE)
    write(repo, ARCH, ARCH_BASE)
    commit(repo, "base")

    git(repo, "checkout", "-q", "-b", "feat")
    write(repo, LIVE, branch_live)
    write(repo, ARCH, branch_arch)
    commit(repo, "feat")

    git(repo, "checkout", "-q", "master")
    write(repo, LIVE, master_live)
    write(repo, ARCH, master_arch)
    commit(repo, "master")

    git(repo, "checkout", "-q", "feat")
    return repo


def outcome(report, path):
    return next(o for o in report.outcomes if o["path"] == path)


def assert_no_markers(*texts):
    for text in texts:
        assert "<<<<<<<" not in text and ">>>>>>>" not in text, text


def merged_text(repo, path):
    return (repo / path).read_text(encoding="utf-8")


def body(live_history: str) -> str:
    return "# Product Roadmap\n\n## History\n\n" + live_history


def test_both_sides_prepend_over_empty_history_base(tmp_path):
    """Behavior 8, empty base: both sides prepend a different plain-date bullet into an empty
    History, so the whole region is an insertion and the merge places ours' first."""
    repo = setup(tmp_path, body(X), ARCH_BASE, body(Y), ARCH_BASE)
    report = merge_back(str(repo), "master")
    assert LIVE in report.auto_resolved, report.to_json()
    assert report.deferred == [] and report.partially_resolved == [], report.to_json()
    text = merged_text(repo, LIVE)
    assert_no_markers(text)
    assert text == body(X + Y), text


def test_both_sides_prepend_over_nonempty_history_base(tmp_path):
    """Behavior 8, non-empty base: each side prepends its own bullet above a shared older bullet;
    the doc auto-resolves newest-first with the base bullet last."""
    repo = setup(tmp_path, body(X + OLD), ARCH_BASE, body(Y + OLD), ARCH_BASE)
    report = merge_back(str(repo), "master")
    assert LIVE in report.auto_resolved, report.to_json()
    assert report.deferred == [] and report.partially_resolved == [], report.to_json()
    text = merged_text(repo, LIVE)
    assert_no_markers(text)
    assert text == body(X + Y + OLD), text


def test_bullet_both_sides_added_is_placed_once(tmp_path):
    """Behavior 8's dedupe: both sides added the SAME rollover line S alongside their own distinct
    bullets, so the region really conflicts; the merged doc holds S once, not twice (the #307
    duplicated-bullet defect)."""
    repo = setup(tmp_path, body(X + S + OLD), ARCH_BASE, body(Y + S + OLD), ARCH_BASE)
    report = merge_back(str(repo), "master")
    assert LIVE in report.auto_resolved, report.to_json()
    text = merged_text(repo, LIVE)
    assert_no_markers(text)
    assert text.count(S) == 1, text
    assert text == body(X + S + Y + OLD), text   # ours' run first, then theirs' new lines


def _rollover_overlap(tmp_path):
    """Behavior 9: ours moves A and B to the archive and adds X; theirs moves only A and adds Y."""
    return setup(tmp_path, body(X + OLD), ARCH_BASE + A + B, body(Y + B + OLD), ARCH_BASE + A)


def test_rollover_overlap_live_doc(tmp_path):
    """Behavior 9: the live doc holds X and Y and NOT B (ours proved that move)."""
    repo = _rollover_overlap(tmp_path)
    report = merge_back(str(repo), "master")
    assert LIVE in report.auto_resolved, report.to_json()
    assert report.deferred == [] and report.partially_resolved == [], report.to_json()
    text = merged_text(repo, LIVE)
    assert_no_markers(text)
    assert X in text and Y in text and OLD in text, text
    assert A not in text and B not in text, text


def test_rollover_overlap_archive_holds_each_moved_bullet_once(tmp_path):
    """Behavior 9: the archive holds A and B exactly once each — no duplicated bullet, and no
    archived bullet re-added to the live doc (the #307 defects)."""
    repo = _rollover_overlap(tmp_path)
    report = merge_back(str(repo), "master")
    assert ARCH in report.auto_resolved, report.to_json()
    arch = merged_text(repo, ARCH)
    live = merged_text(repo, LIVE)
    assert_no_markers(arch)
    assert arch.count(A) == 1 and arch.count(B) == 1, arch
    assert A not in live and B not in live, live


def test_rollover_overlap_verifier_is_zero_drop(tmp_path):
    """Behavior 9's gate: `verify_with_moves` over the staged result reports ZERO-DROP."""
    repo = _rollover_overlap(tmp_path)
    report = merge_back(str(repo), "master")
    assert LIVE in report.auto_resolved, report.to_json()
    mb = git(repo, "merge-base", "HEAD", "MERGE_HEAD").stdout.strip()
    base = git(repo, "show", f"{mb}:{LIVE}").stdout
    ours = git(repo, "show", f"HEAD:{LIVE}").stdout
    theirs = git(repo, "show", f"MERGE_HEAD:{LIVE}").stdout
    merged = merged_text(repo, LIVE)
    archives = driver_archives(str(repo), LIVE)
    assert isinstance(archives(), ArchiveTexts), archives
    r = verify_with_moves(base, ours, theirs, merged, mechanical_applied=True, archives=archives)
    assert r.verdict == VERIFIED, r
    assert r.dropped == [], r


def test_unproven_removal_defers(tmp_path):
    """Behavior 10: a side removes a plain-date bullet its archive does not hold — the file
    defers, markers left in place, with the missing atom named."""
    repo = setup(tmp_path, body(X + OLD), ARCH_BASE, body(Y + B + OLD), ARCH_BASE)
    report = merge_back(str(repo), "master")
    assert LIVE in report.deferred, report.to_json()
    o = outcome(report, LIVE)
    dropped = [tuple(x.split(":", 1)) for x in o["dropped"]]
    assert any(kind == "log" and "second rollover" in sig for kind, sig in dropped), o
    assert "<<<<<<<" in merged_text(repo, LIVE), merged_text(repo, LIVE)


def test_edited_plain_bullet_defers(tmp_path):
    """Behavior 10's other arm: a side EDITS an existing plain-date bullet. A plain bullet has no
    key, so no class may merge it — the file defers."""
    edited = "- 2026-10-08 — still in the live doc (master reworded it)\n"
    repo = setup(tmp_path, body(X + OLD), ARCH_BASE, body(Y + edited), ARCH_BASE)
    report = merge_back(str(repo), "master")
    assert LIVE in report.deferred, report.to_json()
    assert "<<<<<<<" in merged_text(repo, LIVE), merged_text(repo, LIVE)


def assert_deferred(report):
    """The decision assertion for a refused hunk. A deferred file keeps git's conflict markers,
    which QUOTE both sides' text, so the file's text decides nothing here — only the bucket does.
    A pre-resolved mechanical hunk elsewhere in the file lands the doc in `partially_resolved`
    rather than `deferred`; either answer is a refusal. `auto_resolved` is the only wrong one."""
    assert LIVE not in report.auto_resolved, report.to_json()
    assert LIVE in report.deferred or LIVE in report.partially_resolved, report.to_json()


def test_edit_vs_archive_defers(tmp_path):
    """Behavior 11: ours EDITS the plain bullet A while master rolls A to the archive (its archive
    now holds A, its live doc dropped it). Both sides dropped base's A and ours' near-identical
    same-date line is an edit of it — auto-resolving writes the edited text into the live doc and
    the pre-edit text into the archive, a split only the operator can decide."""
    repo = setup(tmp_path, body(A_OURS + B + OLD), ARCH_BASE, body(B + OLD), ARCH_BASE + A)
    report = merge_back(str(repo), "master")
    assert_deferred(report)


def test_edit_vs_archive_defers_mirrored(tmp_path):
    """The same shape with the sides swapped: ours archives A, theirs edits it."""
    repo = setup(tmp_path, body(X + B + OLD), ARCH_BASE + A, body(A_THEIRS + B + OLD), ARCH_BASE)
    report = merge_back(str(repo), "master")
    assert_deferred(report)


def test_both_sides_edit_one_plain_bullet_defers(tmp_path):
    """Both sides reworded the same plain bullet differently, so neither kept base's A: a plain
    bullet has no key to align the two edits by, and keeping both is not a merge."""
    repo = setup(tmp_path, body(A_OURS + B + OLD), ARCH_BASE, body(A_THEIRS + B + OLD), ARCH_BASE)
    report = merge_back(str(repo), "master")
    assert_deferred(report)
