"""End-to-end behaviour tests on real git merges (Task 4.1).

Each test builds a throwaway temp repo (never under `/tmp` — see TMPDIR), drives real git
commits across `master` and a `design` branch, and exercises the shipped CLI
(`number_issues.py`) and the merge driver (`merge_driver.merge_back`) exactly as a human would
run them, in that order. These are integration tests: no module internals are mocked.

Behaviors covered (design: basesync-autoresolve-coverage):
  B1 — a placeholder known-issue ID numbers against a base ref that already advanced, and the
       resulting disjoint-key headings auto-resolve through the merge driver.
  B2 — two independently-started branches each number a placeholder in turn; the second reads
       the FIRST's already-landed number off the live base ref and never reuses it.
  B3 — a preamble-only (`*Last updated:*`) conflict auto-resolves to the later date.
  B7 — a concurrently-added prose paragraph (not a log entry) is not mechanical and still
       requires a human: the driver never stages it.
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
from merge_driver import merge_back  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402  # shipped scrub; git_env is dev-only

NUMBER_ISSUES = str(Path(__file__).resolve().parent.parent.parent / "_shared" / "number_issues.py")

KI = "three-pillars-docs/known_issues.md"
PR = "three-pillars-docs/product_roadmap.md"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=check, env=clean_git_env(**IDENTITY))


def write(repo, rel, content):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def make_repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    (repo / "three-pillars-docs").mkdir()
    return repo


def run_number_issues(repo, base):
    r = subprocess.run(["python3", NUMBER_ISSUES, "--repo", str(repo), "--base", base,
                        "--commit"], env=clean_git_env(**IDENTITY), capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout, r.stderr)
    return r


def test_b1_placeholder_numbers_against_base_then_auto_resolves(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, KI, "# Known issues\n\n## Medium\n\n### L1: next entry\nbody\n")
    write(repo, PR, "# Roadmap\n\nSee L1 for details.\n")
    commit(repo, "base")

    git(repo, "checkout", "-q", "-b", "design")
    write(repo, KI, "# Known issues\n\n## Medium\n\n"
          "### M-new-reset-not-runaway: design issue\ndesign body\n\n"
          "### L1: next entry\nbody\n")
    write(repo, PR, "# Roadmap\n\nSee M-new-reset-not-runaway for details.\n")
    commit(repo, "design: placeholder")

    git(repo, "checkout", "-q", "master")
    write(repo, KI, "# Known issues\n\n## Medium\n\n"
          "### M48: master issue\nmaster body\n\n"
          "### L1: next entry\nbody\n")
    commit(repo, "master: m48")

    git(repo, "checkout", "-q", "design")
    run_number_issues(repo, "master")

    ki_text = (repo / KI).read_text(encoding="utf-8")
    pr_text = (repo / PR).read_text(encoding="utf-8")
    assert "M49" in ki_text, ki_text
    assert "M49" in pr_text, pr_text
    assert "M-new-reset-not-runaway" not in ki_text

    report = merge_back(str(repo), "master")
    assert KI in report.auto_resolved, report.to_json()
    assert not report.needs_human
    content = (repo / KI).read_text(encoding="utf-8")
    assert "M49" in content and "M48" in content


def test_b2_two_branches_number_in_turn_never_reuse(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, KI, "# Known issues\n\n## Medium\n\n"
          "### M48: seed issue\nseed body\n\n### L1: next entry\nbody\n")
    commit(repo, "base")

    # branch-a off master: add a placeholder, number it, land it on master.
    git(repo, "checkout", "-q", "-b", "branch-a")
    write(repo, KI, "# Known issues\n\n## Medium\n\n"
          "### M48: seed issue\nseed body\n\n"
          "### M-new-a: branch a issue\na body\n\n### L1: next entry\nbody\n")
    commit(repo, "branch-a: placeholder")
    run_number_issues(repo, "master")
    a_text = (repo / KI).read_text(encoding="utf-8")
    assert "M49" in a_text and "M-new-a" not in a_text

    # branch-b created from the SAME original master commit, independently of branch-a.
    git(repo, "checkout", "-q", "master")
    git(repo, "checkout", "-q", "-b", "branch-b")
    write(repo, KI, "# Known issues\n\n## Medium\n\n"
          "### M48: seed issue\nseed body\n\n"
          "### M-new-b: branch b issue\nb body\n\n### L1: next entry\nbody\n")
    commit(repo, "branch-b: placeholder")

    # branch-a lands on master BEFORE branch-b numbers against it.
    git(repo, "checkout", "-q", "master")
    git(repo, "merge", "-q", "--no-ff", "branch-a", "-m", "merge branch-a")

    git(repo, "checkout", "-q", "branch-b")
    run_number_issues(repo, "master")
    b_text = (repo / KI).read_text(encoding="utf-8")
    assert "M50" in b_text and "M-new-b" not in b_text   # M49 already taken, never reused


def test_b3_preamble_only_conflict_resolves_to_later_date(tmp_path):
    body = "\n### L1: base issue\nbody\n\n## History\n\n- **2026-05-01** — base entry\n"
    repo = make_repo(tmp_path)
    write(repo, KI, "*Last updated: 2026-06-01*\n\n# Known issues\n" + body)
    commit(repo, "base")

    git(repo, "checkout", "-q", "-b", "design")
    write(repo, KI, "*Last updated: 2026-06-02*\n\n# Known issues\n" + body)
    commit(repo, "design: bump date")

    git(repo, "checkout", "-q", "master")
    write(repo, KI, "*Last updated: 2026-06-03*\n\n# Known issues\n" + body)
    commit(repo, "master: bump date")

    git(repo, "checkout", "-q", "design")
    report = merge_back(str(repo), "master")
    assert KI in report.auto_resolved, report.to_json()
    assert not report.needs_human
    content = (repo / KI).read_text(encoding="utf-8")
    assert "2026-06-03" in content
    assert "<<<<<<<" not in content


def test_b7_added_prose_paragraph_still_defers(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, KI, "# Title\n\n## History\n\n- **2026-07-01** — seed\n")
    commit(repo, "base")

    git(repo, "checkout", "-q", "-b", "design")
    write(repo, KI, "# Title\n\n## History\n\n"
          "a design-side prose paragraph, not a log entry\n"
          "- **2026-07-01** — seed\n")
    commit(repo, "design: prose")

    git(repo, "checkout", "-q", "master")
    write(repo, KI, "# Title\n\n## History\n\n"
          "a master-side prose paragraph, not a log entry\n"
          "- **2026-07-01** — seed\n")
    commit(repo, "master: prose")

    git(repo, "checkout", "-q", "design")
    report = merge_back(str(repo), "master")
    assert KI not in report.auto_resolved, report.to_json()
    assert report.needs_human
    unmerged = git(repo, "diff", "--name-only", "--diff-filter=U").stdout
    assert KI in unmerged                                # never staged for the human to confirm
