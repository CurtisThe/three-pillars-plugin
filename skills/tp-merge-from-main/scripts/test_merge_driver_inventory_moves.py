"""`merge_back` merges Design Inventory rows moved on both sides without a drop (Behavior 6).

A design branch and master each run `inventory_archive.move_completed` for a different slug, then
apply the flip production's `close` makes (`Completion PR pending` -> `Done (completion PR)`) as a
literal byte edit (`pending_flip` is a same-phase sibling; Task 3.4 drives the real `close`).
Merging the two must leave each moved row in the archive exactly once, in neither live file, with
no conflict marker. The Recent-completions roll is not slug-scoped, so both sides roll the same
oldest bullet.

Fixture notes. The archive mirrors the real one: a Recent-completions older-entries section and an
`### Active` table under the Design Inventory heading, so a moved row is appended to that table.
Row `c` sits between `a` and `b` in the live table, so the two deletions are not adjacent lines
(git conflicts on adjacent hunks, which is a separate matter from the move rule).

Each test pins one property, so a fault fails one node: the ARCHIVE side (both appended rows kept,
each once, no marker) in the branch-a / master-b order; the LIVE side (neither moved row left, `c`
and both flips and History lines kept, no marker) in the symmetric branch-b / master-a order; and
the shared Recent-completions roll. Every assertion's message names the violation.
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
from inventory_archive import RC_KEEP, move_completed  # noqa: E402
from merge_driver import merge_back  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402  # shipped scrub; git_env is dev-only

LIVE = "three-pillars-docs/product_roadmap.md"
ARCH = "three-pillars-docs/product_roadmap_archive.md"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
PENDING, DONE = "Completion PR pending", "Done (completion PR)"
NO_ROW = "no-such-slug"  # a slug with no row: the mover then only rolls Recent completions

ROW = "| {s} | What for {s}. | design | " + PENDING + " |\n"
BULLET = "- Thing {s} (`{s}`, 2026-10-02; " + PENDING + ").\n"
RC_OLD = [f"- **`rc-{n}`** — Done — PR #{n}\n" for n in range(2, RC_KEEP + 2)]  # newest first
ARCHIVE_BASE = (
    "# Product Roadmap — Archive\n\n"
    "## Current Focus — historical (moved from the live roadmap)\n\n"
    "### Recent completions — older entries (the newest four stay in the live roadmap)\n\n"
    "- **`rc-ancient`** — Done — PR #1\n\n"
    "## Design Inventory — completed and superseded rows\n\n### Active\n\n"
    "| Design | What | Status |\n|---|---|---|\n| prior | A prior row. | design | Done — PR #9 |\n")
LIVE_BASE = (
    "# Product Roadmap\n\n## Current State\n\n**What works today:**\n"
    + BULLET.format(s="a") + "- stable middle line\n" + BULLET.format(s="b") + "\n"
    "## Current Focus — seeds\n\n### Recent completions\n" + "".join(RC_OLD) + "\n"
    "## Design Inventory\n\n### Active\n\n| Design | What | Status |\n|---|---|---|\n"
    + ROW.format(s="a") + ROW.format(s="c") + ROW.format(s="b") + "\n"
    "## Roadmap History\n- **2026-09-01** — seed\n")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, env=clean_git_env(**IDENTITY))


def read(repo, rel):
    return (repo / rel).read_text(encoding="utf-8")


def write(repo, rel, content):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def flip(text, slug):
    """The byte edit `close` makes: `pending` -> done on the slug's row and Current State bullet."""
    return "".join(
        ln.replace(PENDING, DONE) if (f"`{slug}`" in ln or ln.startswith(f"| {slug} |")) else ln
        for ln in text.splitlines(keepends=True))


def side_edit(repo, slug, note, new_bullet=None):
    """One side's archival commit: move the slug's row (and roll Recent completions), flip its
    text, add a History line. `slug=None` moves no row; `new_bullet` is a newer Recent completion."""
    if new_bullet:
        write(repo, LIVE, read(repo, LIVE).replace("### Recent completions\n",
                                                   "### Recent completions\n" + new_bullet))
    result = move_completed(repo, slug or NO_ROW, apply=True)
    assert result.reason is None, f"fixture: move_completed refused {slug or NO_ROW}: {result}"
    if slug:
        for rel in (LIVE, ARCH):
            write(repo, rel, flip(read(repo, rel), slug))
    write(repo, LIVE, read(repo, LIVE).replace("## Roadmap History\n",
                                               "## Roadmap History\n" + note + "\n"))
    commit(repo, f"archive {slug}")


def setup(tmp_path, *, branch, master, new_bullets=(None, None)):
    """`branch` / `master` are the slugs each side moves. A `new_bullets` pair adds one new
    Recent-completions bullet per side, so each side's mover rolls the same oldest bullet."""
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    write(repo, LIVE, LIVE_BASE)
    write(repo, ARCH, ARCHIVE_BASE)
    for slug in "abc":
        write(repo, f"three-pillars-docs/completed-tp-designs/{slug}/design.md", f"# {slug}\n")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "feat")
    side_edit(repo, branch, "- **2026-10-02** — branch history line", new_bullets[0])
    git(repo, "checkout", "-q", "master")
    side_edit(repo, master, "- **2026-10-02** — master history line", new_bullets[1])
    git(repo, "checkout", "-q", "feat")
    return repo


def assert_no_markers(repo, rel):
    text = read(repo, rel)
    assert "<<<<<<<" not in text and ">>>>>>>" not in text, f"conflict marker left in {rel}:\n{text}"


def assert_auto_resolved(report, rel):
    assert rel in report.auto_resolved, f"{rel} was not auto-resolved: {report.to_json()}"


def done_row(slug):
    return f"| {slug} | What for {slug}. | design | {DONE} |"


def test_branch_moves_a_master_moves_b_archive_keeps_each_row_once(tmp_path):
    repo = setup(tmp_path, branch="a", master="b")

    report = merge_back(str(repo), "master")

    assert_no_markers(repo, ARCH)
    assert_auto_resolved(report, ARCH)
    arch = read(repo, ARCH)
    for s in "ab":
        n = arch.count(done_row(s))
        assert n == 1, f"row {s} appears {n} times in archive:\n{arch}"


def test_branch_moves_b_master_moves_a_live_keeps_neither_moved_row(tmp_path):
    repo = setup(tmp_path, branch="b", master="a")

    report = merge_back(str(repo), "master")

    assert_no_markers(repo, LIVE)
    assert_auto_resolved(report, LIVE)
    live = read(repo, LIVE)
    for s in "ba":
        assert f"| {s} | What for" not in live, f"row {s} still live:\n{live}"
    n = live.count(ROW.format(s="c"))
    assert n == 1, f"row c appears {n} times in live (it must stay once):\n{live}"
    pending = live.count(PENDING)
    assert pending == 1, f"a Current State flip was lost: {pending} pending tokens in live, want 1 (c's):\n{live}"
    for side in ("branch", "master"):
        assert f"{side} history line" in live, f"the {side} history line was lost from live:\n{live}"


def test_both_sides_rolling_the_same_oldest_recent_completion_rolls_it_once(tmp_path):
    repo = setup(tmp_path, branch=None, master=None,
                 new_bullets=("- **`rc-branch`** — Done — PR #20\n", "- **`rc-master`** — Done — PR #21\n"))

    report = merge_back(str(repo), "master")

    for rel in (LIVE, ARCH):
        assert_no_markers(repo, rel)
    assert not report.needs_human, f"the shared roll needs a human: {report.to_json()}"
    live, arch = read(repo, LIVE), read(repo, ARCH)
    rolled = RC_OLD[-1]
    n = arch.count(rolled)
    assert n == 1, f"rolled bullet {rolled.strip()!r} appears {n} times in archive:\n{arch}"
    assert rolled not in live, f"rolled bullet {rolled.strip()!r} still live:\n{live}"
    for side in ("branch", "master"):
        assert f"**`rc-{side}`**" in live, f"the {side} side's new Recent completion was lost:\n{live}"
