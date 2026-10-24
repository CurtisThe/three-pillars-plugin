"""Tests for archive_allowlist.py — design-archive allowlist + reference check
(plan Task 1.8).

Behavior 4: `plan_prune_many(design_dirs, repo_root)` computes one global
least fixpoint over every given design dir: candidates are each dir's tracked
non-allowlisted files; sources are the kept files plus every tracked text file
outside the union of all candidates; a candidate a source names becomes kept
and a source; iterate until stable. `plan_prune` is `plan_prune_many` of one
dir. Cases: a `.handoffs/` file named by `decisions.md` or by a test file is
kept; a design-root reference names the dir alone and keeps nothing extra;
an ignored file is reported `ignored` and never removed; an untracked
non-ignored file is kept; ambiguity keeps; cross-design references drop both
and a second `plan_prune_many` after `apply` has no drops; `apply` git-rms
only the tracked drops.

Run with: python -m pytest skills/_shared/test_archive_allowlist.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from archive_allowlist import (
    ALLOWLIST,
    PrunePlan,
    apply,
    plan_prune,
    plan_prune_many,
)

COMPL = "three-pillars-docs/completed-tp-designs"
D = f"{COMPL}/dslug"


def _git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=True, env=env,
    )


def _commit(root, msg="fix", *paths):
    if paths:
        _git(root, "add", "--", *paths)
    _git(root, "-c", "user.name=fixture", "-c", "user.email=fixture@test",
         "commit", "-q", "-m", msg, "--allow-empty")


def _write(root, rel, content):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _init_repo(root: Path):
    _git(root, "init", "-q", "-b", "master")
    _write(root, "README.md", "repo\n")
    _commit(root, "base", ".")


def _build_big(root: Path):
    """The Behavior-4 fixture: one design dir with a mix of allowlisted,
    named (kept), untracked and drop candidates."""
    for rel, content in {
        "design.md": "# design\n",
        "plan.md": "see notes.md for the rollout order\n",
        "decisions.md": "kept the .handoffs/kept.json bundle\n",
        "lock.json": '{"owner": "fixture"}\n',
        "implementation-audit.md": "audited\n",
        "handoff.md": "handoff\n",
        "detailed-design.md": "blueprint\n",
        "candidates/x.json": "{}\n",
        ".handoffs/round1-bundle.json": "{}\n",
        ".handoffs/kept.json": "{}\n",
        "demos/a/run.log": "run output\n",
        "notes.md": "notes\n",
    }.items():
        _write(root, D + "/" + rel, content)
    # Untracked external source (the repo's own test file) that keeps demos/a/
    # alive with a live design-root reference.
    _write(root, "skills/_shared/test_x.py",
           f"# fixture keeps {D}/demos/a/ alive\n")
    _commit(root, "design dir", ".")
    # Untracked on purpose: kept by the plan (design-complete stages it).
    _write(root, D + "/scratch.md", "scratch\n")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _init_repo(tmp_path)
    _build_big(tmp_path)
    return tmp_path


def test_allowlist_names():
    for name in ("design.md", "plan.md", "decisions.md", "lock.json",
                 "handoff.md", "seed.md", "research.md", "spike-results.md",
                 "implementation-audit.md", "retro-findings.json",
                 "retro-outbox.json"):
        assert name in ALLOWLIST
    assert "detailed-design*.md" in ALLOWLIST
    assert "review*.md" in ALLOWLIST


def test_retro_artifacts_survive_the_prune(tmp_path: Path):
    # design-learn-retro: `run_retro.py pr-section` reads the archived dir, so the
    # step-6e2 prune keeps both top-level retro files even when nothing names them.
    _init_repo(tmp_path)
    d = f"{COMPL}/rslug"
    for rel in ("design.md", "retro-findings.json", "retro-outbox.json",
                "scratch/retro-outbox.json", "junk.txt"):
        _write(tmp_path, d + "/" + rel, "{}\n")
    _commit(tmp_path, "archived design", ".")
    plan = plan_prune(d, tmp_path)
    assert d + "/retro-findings.json" in plan.keep
    assert d + "/retro-outbox.json" in plan.keep
    # only top-level names are allowlistable: a nested copy is still a candidate
    assert plan.drop == [d + "/junk.txt", d + "/scratch/retro-outbox.json"]
    apply(plan, tmp_path)
    assert (tmp_path / d / "retro-findings.json").exists()
    assert (tmp_path / d / "retro-outbox.json").exists()


def test_behavior_4_fixpoint(repo: Path):
    # A chain: plan.md (kept) names notes.md (candidate X); notes.md alone
    # names demos/b/trace.log (candidate Y). A least fixpoint must rescan the
    # newly kept X as a source and keep Y; a single pass would drop it.
    _write(repo, D + "/notes.md", "notes; the trace lives at demos/b/trace.log\n")
    _write(repo, D + "/demos/b/trace.log", "trace\n")
    _write(repo, D + "/demos/c/orphan.log", "named by nobody\n")
    # A dropped candidate is never a source: candidates/x.json (named by
    # nothing kept) names demos/e/chain.log, and nothing else names it ->
    # both drop. A candidate cycle (p names q, q names p) with no kept or
    # external entry point also drops whole.
    _write(repo, D + "/candidates/x.json",
           '{"trace": "' + D + '/demos/e/chain.log"}\n')
    _write(repo, D + "/demos/e/chain.log", "named only by a dropped candidate\n")
    _write(repo, D + "/demos/f/p.log", "pairs with " + D + "/demos/f/q.log\n")
    _write(repo, D + "/demos/f/q.log", "pairs with " + D + "/demos/f/p.log\n")
    _commit(repo, "chain", D + "/notes.md", D + "/demos",
            D + "/candidates")  # scratch.md stays untracked
    plan = plan_prune(D, repo)
    assert isinstance(plan, PrunePlan)
    keep = set(plan.keep)
    drop = set(plan.drop)
    assert keep == {
        D + r for r in (
            "/design.md", "/detailed-design.md", "/plan.md", "/decisions.md",
            "/lock.json", "/implementation-audit.md", "/handoff.md",
            "/.handoffs/kept.json", "/demos/a/run.log", "/notes.md",
            "/demos/b/trace.log", "/scratch.md",
        )
    }, "fixpoint must keep the chained candidate named only by a kept candidate"
    assert drop == {
        D + "/candidates/x.json", D + "/.handoffs/round1-bundle.json",
        D + "/demos/c/orphan.log", D + "/demos/e/chain.log",
        D + "/demos/f/p.log", D + "/demos/f/q.log",
    }, "unnamed candidates (incl. ones named only by dropped candidates) must drop"
    assert plan.ignored == []
    assert plan.bytes == sum((repo / p).stat().st_size for p in drop)


def test_root_reference_names_nothing(repo: Path):
    _write(repo, D + "/decisions.md",
           "kept .handoffs/kept.json; whole archive " + D + "/ archived\n")
    _commit(repo, "root ref", D + "/decisions.md")
    plan = plan_prune(D, repo)
    assert D + "/.handoffs/round1-bundle.json" in plan.drop
    assert D + "/.handoffs/kept.json" in plan.keep


def test_ambiguity_keeps(repo: Path):
    # A reference under the other root (tp-designs/, not completed-tp-designs/)
    # still names the candidate — ambiguity keeps.
    _write(repo, D + "/decisions.md",
           "see tp-designs/dslug/candidates/x.json for the ambiguity call\n")
    _commit(repo, "ambiguity", D + "/decisions.md")
    plan = plan_prune(D, repo)
    assert D + "/candidates/x.json" in plan.keep
    assert D + "/.handoffs/round1-bundle.json" in plan.drop


def test_cross_design_reference_and_apply(tmp_path: Path):
    _init_repo(tmp_path)
    # Design A's candidate names design B's candidate; both must drop.
    _write(tmp_path, f"{COMPL}/aslug/design.md", "# a\n")
    _write(tmp_path, f"{COMPL}/aslug/.handoffs/a.json",
           f"names {COMPL}/bslug/candidates/b.json for the record\n")
    _write(tmp_path, f"{COMPL}/bslug/design.md", "# b\n")
    _write(tmp_path, f"{COMPL}/bslug/candidates/b.json", "{}\n")
    _commit(tmp_path, "two design dirs", ".")

    a = f"{COMPL}/aslug"
    b = f"{COMPL}/bslug"
    plan = plan_prune_many([a, b], tmp_path)
    assert a + "/.handoffs/a.json" in plan.drop
    assert b + "/candidates/b.json" in plan.drop
    apply(plan, tmp_path)
    assert not (tmp_path / a / ".handoffs" / "a.json").exists()
    assert not (tmp_path / b / "candidates" / "b.json").exists()
    _commit(tmp_path, "post-apply", ".")

    again = plan_prune_many([a, b], tmp_path)
    assert again.drop == []
    assert again.ignored == []
    assert a + "/design.md" in again.keep
    assert b + "/design.md" in again.keep


def test_ignored_and_untracked(tmp_path: Path):
    _init_repo(tmp_path)
    # A .gitignore that ignores the .handoffs dir, then an ignored file and an
    # untracked non-ignored file created on top of it.
    _write(tmp_path, f"{COMPL}/islug/design.md", "# i\n")
    _commit(tmp_path, "design dir", ".")
    _write(tmp_path, ".gitignore", f"{COMPL}/*/.handoffs/*\n")
    _commit(tmp_path, "gitignore", ".")
    _write(tmp_path, f"{COMPL}/islug/.handoffs/x.json", "{}\n")
    _write(tmp_path, f"{COMPL}/islug/scratch.md", "scratch\n")

    d = f"{COMPL}/islug"
    plan = plan_prune(d, tmp_path)
    assert d + "/.handoffs/x.json" in plan.ignored
    assert d + "/.handoffs/x.json" not in plan.drop
    assert d + "/scratch.md" in plan.keep
    apply(plan, tmp_path)
    assert (tmp_path / d / ".handoffs" / "x.json").exists()
    assert d + "/scratch.md" in plan_prune(d, tmp_path).keep


def test_cli(repo: Path):
    here = Path(__file__).resolve().parent
    args = [sys.executable, str(here / "archive_allowlist.py")]
    out = subprocess.run(
        [*args, "plan", "--design-dir", D, "--repo-root", str(repo)],
        capture_output=True, text=True, check=True,
    )
    assert D + "/.handoffs/round1-bundle.json" in out.stdout
    assert "total: " in out.stdout and " bytes" in out.stdout

    out = subprocess.run(
        [*args, "plan", "--design-dir", D, "--repo-root", str(repo), "--json"],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(out.stdout)
    assert set(data) == {"keep", "drop", "ignored", "bytes"}
    assert D + "/.handoffs/round1-bundle.json" in data["drop"]
    assert isinstance(data["bytes"], int) and data["bytes"] > 0

    out = subprocess.run(
        [*args, "apply", "--design-dir", D, "--repo-root", str(repo)],
        capture_output=True, text=True, check=True,
    )
    assert D + "/.handoffs/round1-bundle.json" in out.stdout
    assert not (repo / D / ".handoffs" / "round1-bundle.json").exists()
    assert not (repo / D / "candidates" / "x.json").exists()
    # Kept files are untouched by apply.
    assert (repo / D / "design.md").exists()


def test_apply_after_design_complete_git_mv(tmp_path: Path):
    # PR #177 r1: design-complete step 6c `git mv`s the design dir (a staged,
    # uncommitted rename) and step 6e2 then runs `apply` on the archived dir,
    # so every drop is staged-added vs HEAD; a plain `git rm` refused it.
    _init_repo(tmp_path)
    live = "three-pillars-docs/tp-designs/foo"
    _write(tmp_path, live + "/design.md", "# foo\n")
    _write(tmp_path, live + "/candidates/summary.md", "scratch\n")
    _commit(tmp_path, "design", ".")
    (tmp_path / COMPL).mkdir(parents=True)
    _git(tmp_path, "mv", live, COMPL + "/foo")
    d = COMPL + "/foo"
    plan = plan_prune(d, tmp_path)
    assert plan.drop == [d + "/candidates/summary.md"]
    apply(plan, tmp_path)
    assert _git(tmp_path, "ls-files", "--", d).stdout.split() == [d + "/design.md"]
    assert not (tmp_path / d / "candidates" / "summary.md").exists()
    assert (tmp_path / d / "design.md").exists()
