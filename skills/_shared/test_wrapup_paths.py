"""wrapup_paths.py — behavior tests on real git repos (run-throughput, operator ruling H1).

The Decision 12 ndjson is staged with the phase wrap-up (interactive step 9) and with the
orchestrator's Tier 3.5 commit, is never gitignored, and rides the design dir's `git mv` into
the archive.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import archive_allowlist  # noqa: E402 — the real /tp-design-complete prune rule
import wrapup_paths  # noqa: E402
from task_scope import _git_env  # noqa: E402

REPO_GITIGNORE = HERE.parent.parent / ".gitignore"
D = "three-pillars-docs/tp-designs/demo"
NDJSON = f"{D}/dispatch-telemetry.ndjson"
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
         "GIT_COMMITTER_EMAIL": "t@t"}


def _git(repo: Path, *args, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check,
                          env=_git_env(**IDENT))


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / D).mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "tp/demo")
    if REPO_GITIGNORE.is_file():  # the dev repo pins its real rules; a consumer copy has none
        shutil.copy(REPO_GITIGNORE, repo / ".gitignore")
    for name in ("plan.md", "decisions.md", "lock.json"):
        (repo / D / name).write_text(f"{name}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _telemetry_row(repo: Path) -> None:
    row = {"role": "task", "task_id": "1.1", "attempt_key": "k1", "served_by": "local"}
    (repo / NDJSON).write_text(json.dumps(row) + "\n", encoding="utf-8")


def _staged(repo: Path) -> set[str]:
    return set(_git(repo, "diff", "--cached", "--name-only").stdout.split())


def test_phase_wrapup_stages_the_ndjson_with_plan_and_decisions(tmp_path, capsys):
    repo = _repo(tmp_path)
    (repo / D / "plan.md").write_text("plan.md\n**Status**: Done ✓\n", encoding="utf-8")
    with open(repo / D / "decisions.md", "a", encoding="utf-8") as fh:
        fh.write("### [tier] 1.1 — done\n")
    _telemetry_row(repo)

    assert wrapup_paths.main(["--design-dir", D, "--root", str(repo), "--stage"]) == 0
    out = json.loads(capsys.readouterr().out)

    assert out == {"paths": [f"{D}/plan.md", f"{D}/decisions.md", NDJSON], "staged": True}
    assert _staged(repo) == {f"{D}/plan.md", f"{D}/decisions.md", NDJSON}  # lock.json unchanged


def test_ndjson_is_not_gitignored_live_or_archived(tmp_path):
    repo = _repo(tmp_path)
    for path in (NDJSON, "three-pillars-docs/completed-tp-designs/demo/dispatch-telemetry.ndjson"):
        assert _git(repo, "check-ignore", "-q", path, check=False).returncode == 1, path


def test_tier_3_5_commit_stages_candidate_artifacts_and_ndjson(tmp_path, capsys):
    repo = _repo(tmp_path)
    cand = repo / D / "candidates" / "single"
    cand.mkdir(parents=True)
    for name in ("branch.txt", "summary.md", "test-results.json", "telemetry.json"):
        (cand / name).write_text("x\n", encoding="utf-8")
    _telemetry_row(repo)

    assert wrapup_paths.main(["--design-dir", D, "--root", str(repo), "--candidate", "single",
                              "--stage"]) == 0
    out = json.loads(capsys.readouterr().out)

    assert out["paths"] == [NDJSON, f"{D}/candidates/single"]
    assert {NDJSON, f"{D}/candidates/single/telemetry.json"} <= _staged(repo)


def test_clean_tree_lists_nothing_and_stages_nothing(tmp_path, capsys):
    repo = _repo(tmp_path)
    assert wrapup_paths.main(["--design-dir", D, "--root", str(repo), "--stage"]) == 0
    assert json.loads(capsys.readouterr().out) == {"paths": [], "staged": False}
    assert _staged(repo) == set()


def test_committed_ndjson_rides_the_archive_git_mv(tmp_path):
    repo = _repo(tmp_path)
    _telemetry_row(repo)
    wrapup_paths.stage(repo, wrapup_paths.paths(D, repo))
    _git(repo, "commit", "-q", "-m", "Implement: demo phase-1 done")
    archived = "three-pillars-docs/completed-tp-designs/demo"
    (repo / archived).parent.mkdir(parents=True)
    _git(repo, "mv", D, archived)
    _git(repo, "commit", "-q", "-m", "Complete design: demo")

    tracked = _git(repo, "ls-files", archived).stdout.split()
    assert f"{archived}/dispatch-telemetry.ndjson" in tracked
    assert wrapup_paths.paths(archived, repo) == []  # nothing left behind untracked


def test_archive_allowlist_keeps_the_unreferenced_ndjson(tmp_path):
    """/tp-design-complete's step-6e2 prune keeps the ndjson though nothing names it."""
    repo = _repo(tmp_path)
    _telemetry_row(repo)
    (repo / D / "scratch-notes.txt").write_text("unreferenced\n", encoding="utf-8")
    wrapup_paths.stage(repo, wrapup_paths.paths(D, repo) + [f"{D}/scratch-notes.txt"])
    _git(repo, "commit", "-q", "-m", "Implement: demo phase-1 done")
    archived = "three-pillars-docs/completed-tp-designs/demo"
    (repo / archived).parent.mkdir(parents=True)
    _git(repo, "mv", D, archived)
    _git(repo, "commit", "-q", "-m", "Complete design: demo")

    plan = archive_allowlist.plan_prune(archived, repo)
    assert f"{archived}/dispatch-telemetry.ndjson" in plan.keep
    assert plan.drop == [f"{archived}/scratch-notes.txt"]  # the prune does run
    archive_allowlist.apply(plan, repo)
    assert (repo / archived / "dispatch-telemetry.ndjson").is_file()
