"""Tests for archive_sweep.py — one-time archive sweep CLI (plan Task 1.9).

The sweep lists the per-design drops and the byte totals over
``three-pillars-docs/completed-tp-designs/*`` from ONE
``archive_allowlist.plan_prune_many`` call over every archived design dir
(never a per-design loop, which is order-dependent). Dry-run is the default
and changes nothing; ``--apply`` ``git rm``s the tracked drops; ``design.md``
is never a drop. A repo with no ``completed-tp-designs/`` prints
"nothing to sweep" and exits 0.

Run with: python -m pytest skills/_shared/test_archive_sweep.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPL = "three-pillars-docs/completed-tp-designs"


def _git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=True, env=env,
    )


def _commit(root, msg="fixture", *paths):
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


def _build_archive(repo: Path, design_b: bool = True):
    """Two archived designs (A: one named keep, one cross-design drop; B: a
    plain drop). Only design.md (allowlist) and keep-me.json (named by
    design.md) survive the fixpoint."""
    _write(repo, f"{COMPL}/aslug/design.md",
           "---\ncompleted: 2026-09-01\n---\n"
           "# design a\nkept candidates/keep-me.json for the record\n")
    _write(repo, f"{COMPL}/aslug/candidates/keep-me.json",
           '{"role": "named"}\n')
    _write(repo, f"{COMPL}/aslug/candidates/stale.json",
           f"names {COMPL}/bslug/candidates/b.json for the record\n")  # 85
    _write(repo, f"{COMPL}/aslug/demos/run.log", "run output\n")  # 11
    if design_b:
        _write(repo, f"{COMPL}/bslug/design.md",
               "---\ncompleted: 2026-09-01\n---\n# design b\n")
        _write(repo, f"{COMPL}/bslug/candidates/b.json", "{}\n")
    _commit(repo, "archive", ".")


def _run(repo, *args, expect=0):
    out = subprocess.run(
        [sys.executable, str(HERE / "archive_sweep.py"), *args,
         "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    assert out.returncode == expect, (
        f"exit {out.returncode}, expected {expect}\n"
        f"stdout: {out.stdout}\nstderr: {out.stderr}"
    )
    return out


def _tracked(root: Path) -> set[str]:
    r = _git(root, "ls-files")
    return set(r.stdout.splitlines())


def test_dry_run_changes_nothing_and_reports(tmp_path: Path):
    repo = tmp_path
    _init_repo(repo)
    _build_archive(repo)
    before = _tracked(repo)
    out = _run(repo)
    assert _tracked(repo) == before, "dry-run must not touch the index"
    assert "aslug: 2 files, 96 bytes" in out.stdout
    assert "bslug: 1 files, 3 bytes" in out.stdout
    assert "total: 99 bytes" in out.stdout


def test_apply_removes_only_drops(tmp_path: Path):
    repo = tmp_path
    _init_repo(repo)
    _build_archive(repo)
    out = _run(repo, "--apply")
    a = f"{COMPL}/aslug"
    b = f"{COMPL}/bslug"
    for gone in (f"{a}/candidates/stale.json", f"{a}/demos/run.log",
                 f"{b}/candidates/b.json"):
        assert not (repo / gone).exists(), gone
    for kept in (f"{a}/design.md", f"{a}/candidates/keep-me.json",
                 f"{b}/design.md"):
        assert (repo / kept).exists(), kept
    tracked = _tracked(repo)
    assert tracked == {
        "README.md", f"{a}/design.md", f"{a}/candidates/keep-me.json",
        f"{b}/design.md",
    }
    # apply output still reports what it dropped
    assert "aslug: 2 files, 96 bytes" in out.stdout
    assert "bslug: 1 files, 3 bytes" in out.stdout


def test_design_md_survives_with_stamp(tmp_path: Path):
    repo = tmp_path
    _init_repo(repo)
    _build_archive(repo)
    _run(repo, "--apply")
    for slug in ("aslug", "bslug"):
        p = repo / f"{COMPL}/{slug}/design.md"
        text = p.read_text(encoding="utf-8")
        assert "completed: 2026-09-01" in text, slug
        assert f"{COMPL}/{slug}/design.md" in _tracked(repo)


def test_second_dry_run_reports_zero_drops(tmp_path: Path):
    repo = tmp_path
    _init_repo(repo)
    _build_archive(repo)
    _run(repo, "--apply")
    _commit(repo, "post-apply")
    out = _run(repo)
    data = json.loads(_run(repo, "--json").stdout)
    assert data == {"designs": [], "total_bytes": 0}
    assert "aslug:" not in out.stdout and "bslug:" not in out.stdout


def test_cross_design_reference_drops_both_in_one_pass(tmp_path: Path):
    repo = tmp_path
    _init_repo(repo)
    # Design A's candidate names design B's candidate; neither is named by
    # any allowlisted file, so BOTH drop in the single first pass.
    _write(repo, f"{COMPL}/aslug/design.md",
           "---\ncompleted: 2026-09-01\n---\n# a\n")
    _write(repo, f"{COMPL}/aslug/.handoffs/a.json",
           f"names {COMPL}/bslug/candidates/b.json for the record\n")
    _write(repo, f"{COMPL}/bslug/design.md",
           "---\ncompleted: 2026-09-01\n---\n# b\n")
    _write(repo, f"{COMPL}/bslug/candidates/b.json", "{}\n")
    _commit(repo, "cross-design", ".")
    data = json.loads(_run(repo, "--json").stdout)
    drops = {p for d in data["designs"] for p in d["drop"]}
    assert f"{COMPL}/aslug/.handoffs/a.json" in drops
    assert f"{COMPL}/bslug/candidates/b.json" in drops
    _run(repo, "--apply")
    assert not (repo / f"{COMPL}/aslug/.handoffs/a.json").exists()
    assert not (repo / f"{COMPL}/bslug/candidates/b.json").exists()
    _commit(repo, "post-apply")
    again = json.loads(_run(repo, "--json").stdout)
    assert again == {"designs": [], "total_bytes": 0}


def test_json_shape(tmp_path: Path):
    repo = tmp_path
    _init_repo(repo)
    _build_archive(repo)
    data = json.loads(_run(repo, "--json").stdout)
    assert set(data) == {"designs", "total_bytes"}
    assert [d["slug"] for d in data["designs"]] == ["aslug", "bslug"]
    for d in data["designs"]:
        assert set(d) == {"slug", "drop", "bytes"}
        assert isinstance(d["drop"], list) and d["drop"]
        assert all(isinstance(x, str) and x for x in d["drop"])
        assert isinstance(d["bytes"], int)
    a = next(d for d in data["designs"] if d["slug"] == "aslug")
    b = next(d for d in data["designs"] if d["slug"] == "bslug")
    assert a["drop"] == [
        f"{COMPL}/aslug/candidates/stale.json",
        f"{COMPL}/aslug/demos/run.log",
    ]
    assert b["drop"] == [f"{COMPL}/bslug/candidates/b.json"]
    expected = (
        (repo / f"{COMPL}/aslug/candidates/stale.json").stat().st_size
        + (repo / f"{COMPL}/aslug/demos/run.log").stat().st_size
        + (repo / f"{COMPL}/bslug/candidates/b.json").stat().st_size
    )
    assert a["bytes"] + b["bytes"] == expected
    assert data["total_bytes"] == expected


def test_no_completed_dir(tmp_path: Path):
    repo = tmp_path
    _init_repo(repo)
    out = _run(repo)
    assert "nothing to sweep" in out.stdout
    data = json.loads(_run(repo, "--json").stdout)
    assert data == {"designs": [], "total_bytes": 0}


def test_completed_dir_without_designs(tmp_path: Path):
    repo = tmp_path
    _init_repo(repo)
    (repo / "three-pillars-docs").mkdir()
    _write(repo, "three-pillars-docs/README.md", "docs\n")
    _commit(repo, "docs")
    out = _run(repo)
    assert "nothing to sweep" in out.stdout
    data = json.loads(_run(repo, "--json").stdout)
    assert data == {"designs": [], "total_bytes": 0}
