"""`merge_back` reads an archive move as a move, not a drop (Behavior 8)."""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
from merge_driver import merge_back  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402  # shipped scrub; git_env is dev-only

KI = "three-pillars-docs/known_issues.md"
KR = "three-pillars-docs/known_issues_resolved.md"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

LIVE_BASE = (
    "# Known Issues\n\n## Medium\n\n### M47: stale lock is never swept\nbody line\n\n"
    "### M50: other\n\n## History\n\n- **2026-09-01** — seed\n"
)
RESOLVED_BASE = "# R\n"

BRANCH_NOTE = "- **2026-10-01** — branch note\n"
MASTER_NOTE = "- **2026-10-01** — master note\n"
M47_RESOLVED_ENTRY = "### M47 (RESOLVED 2026-10-01): stale lock is never swept\nbody line\n\n"


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


def _with_note(live: str, note: str) -> str:
    return live.replace("- **2026-09-01** — seed\n", note + "- **2026-09-01** — seed\n")


def _without_m47(live: str) -> str:
    return live.replace("### M47: stale lock is never swept\nbody line\n\n", "")


def setup(tmp_path, *, master_moves: bool, branch_moves: bool, branch_edits_m47: bool = False):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    write(repo, KI, LIVE_BASE)
    write(repo, KR, RESOLVED_BASE)
    commit(repo, "base")

    git(repo, "checkout", "-q", "-b", "feat")
    branch_live = _with_note(LIVE_BASE, BRANCH_NOTE)
    if branch_edits_m47:
        branch_live = branch_live.replace("body line\n", "edited body\n")
    if branch_moves:
        branch_live = _without_m47(branch_live)
        write(repo, KR, RESOLVED_BASE + M47_RESOLVED_ENTRY)
    write(repo, KI, branch_live)
    commit(repo, "feat")

    git(repo, "checkout", "-q", "master")
    master_live = _with_note(LIVE_BASE, MASTER_NOTE)
    if master_moves:
        master_live = _without_m47(master_live)
        write(repo, KR, RESOLVED_BASE + M47_RESOLVED_ENTRY)
    write(repo, KI, master_live)
    commit(repo, "master")

    git(repo, "checkout", "-q", "feat")
    return repo


def test_master_moves_m47_to_archive_auto_resolves(tmp_path):
    repo = setup(tmp_path, master_moves=True, branch_moves=False)
    report = merge_back(str(repo), "master")
    assert KI in report.auto_resolved, report.to_json()
    text = (repo / KI).read_text(encoding="utf-8")
    assert "<<<<<<<" not in text
    assert "M47" not in text
    assert "branch note" in text and "master note" in text


def test_branch_moves_m47_to_archive_auto_resolves(tmp_path):
    repo = setup(tmp_path, master_moves=False, branch_moves=True)
    report = merge_back(str(repo), "master")
    assert KI in report.auto_resolved, report.to_json()
    text = (repo / KI).read_text(encoding="utf-8")
    assert "<<<<<<<" not in text
    assert "M47" not in text
    assert "branch note" in text and "master note" in text


def test_plain_deletion_with_no_archive_copy_is_deferred(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    write(repo, KI, LIVE_BASE)
    write(repo, KR, RESOLVED_BASE)
    commit(repo, "base")

    git(repo, "checkout", "-q", "-b", "feat")
    write(repo, KI, _with_note(LIVE_BASE, BRANCH_NOTE))
    commit(repo, "feat")

    git(repo, "checkout", "-q", "master")
    # master deletes M47 but leaves no archive copy behind
    write(repo, KI, _without_m47(_with_note(LIVE_BASE, MASTER_NOTE)))
    commit(repo, "master")

    git(repo, "checkout", "-q", "feat")
    report = merge_back(str(repo), "master")
    assert KI in report.deferred, report.to_json()
    o = next(x for x in report.outcomes if x["path"] == KI)
    assert any("entry" in d and "stale lock" in d for d in o["dropped"]), o


def test_move_vs_edit_of_m47_is_not_auto_resolved(tmp_path):
    repo = setup(tmp_path, master_moves=True, branch_moves=False, branch_edits_m47=True)
    report = merge_back(str(repo), "master")
    assert KI not in report.auto_resolved, report.to_json()
