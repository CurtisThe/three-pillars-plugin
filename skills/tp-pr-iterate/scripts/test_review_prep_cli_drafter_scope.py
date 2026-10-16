"""Review-prep drafter I/O stays inside the drafter's project (PR #209 review r1).

`tp-drafter` is project-scoped (Read/Edit/Write only), while W sits under the
proof root, which in a linked worktree is `<main>/.git/worktrees/<wt>/...`. So
`open` stages every drafter-facing path (facts, inputs, out_path) under the
gitignored `<repo>/.tp-scratch/` (cheap-dispatch.md, Scratch), and `settle`
harvests the draft back into W. `open` calls `scratch_root.ensure_excluded`
first, so a repo with no ignore line is skipped only when that write fails too.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLI = HERE / "review_prep_cli.py"
PROOF = HERE / "proof_root.py"
PR = "https://github.com/o/r/pull/7"
_GIT = ["-c", "user.email=a@b", "-c", "user.name=a", "-c", "commit.gpgsign=false"]


def _git(cwd, *a):
    return subprocess.run(["git", *_GIT, *a], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def _cli(cwd, *a):
    return json.loads(subprocess.run([sys.executable, str(CLI), *a], cwd=cwd,
                                     capture_output=True, text=True, check=True).stdout)


def _linked(tmp_path, ignore=True):
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q")
    if ignore:
        (main / ".gitignore").write_text("/.tp-scratch/\n", encoding="utf-8")
        _git(main, "add", ".gitignore")
    _git(main, "commit", "-q", "--allow-empty", "-m", "base")
    base = _git(main, "rev-parse", "HEAD")
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "-b", "tp/x", str(wt))
    (wt / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(wt, "add", "a.py")
    _git(wt, "commit", "-q", "-m", "c")
    head = _git(wt, "rev-parse", "HEAD")
    root = subprocess.run([sys.executable, str(PROOF), "--no-migrate"], cwd=wt,
                          capture_output=True, text=True, check=True).stdout.strip()
    work = _cli(wt, "begin", "--root", root, "--pr-url", PR, "--base", base, "--head", head,
                "--log", str(tmp_path / "log.md"))["work"]
    return wt, head, work


def test_drafter_paths_are_inside_the_drafters_project(tmp_path):
    wt, head, work = _linked(tmp_path)
    spawn = _cli(wt, "open", "--work", work, "--head", head, "--slot", "review_refs",
                 "--unit", "_")
    assert spawn["state"] == "spawn"
    top = Path(_git(wt, "rev-parse", "--show-toplevel")).resolve()
    facts = json.loads(Path(spawn["facts_path"]).read_text(encoding="utf-8"))
    for path in (spawn["facts_path"], spawn["out_path"], facts["out_path"], facts["diff_path"]):
        assert Path(path).resolve().is_relative_to(top), f"{path} is outside {top}"
    assert facts["out_path"] == spawn["out_path"]
    assert Path(facts["diff_path"]).read_bytes() == (Path(work) / "diff.patch").read_bytes()


def test_settle_harvests_the_staged_draft_into_w_and_cleans_up(tmp_path):
    wt, head, work = _linked(tmp_path)
    _cli(wt, "batch", "--work", work)
    spawn = _cli(wt, "open", "--work", work, "--head", head, "--slot", "review_refs",
                 "--unit", "_")
    draft = {"refs": [{"path": "a.py", "line": 1, "note": "n"}]}
    Path(spawn["out_path"]).write_text(json.dumps(draft), encoding="utf-8")
    _cli(wt, "batch-end", "--work", work, "--head", head, "--loop-ids", "review_refs--_")
    res = _cli(wt, "settle", "--work", work, "--head", head, "--slot", "review_refs",
               "--unit", "_", "--loop-id", "review_refs--_")
    assert res["action"] == "accept", res
    acc = Path(work) / "accepted" / "review_refs--_.json"
    assert json.loads(acc.read_text(encoding="utf-8")) == draft
    assert not Path(spawn["out_path"]).parent.exists()  # the staged unit dir is gone


def test_open_skips_when_the_scratch_dir_is_not_gitignored(tmp_path):
    """No ignore line and `ensure_excluded` cannot write `info/exclude` → skip."""
    wt, head, work = _linked(tmp_path, ignore=False)
    common = Path(_git(wt, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = wt / common
    exclude = common / "info" / "exclude"
    exclude.unlink(missing_ok=True)
    exclude.mkdir(parents=True)  # the write in ensure_excluded must fail
    res = _cli(wt, "open", "--work", work, "--head", head, "--slot", "review_refs",
               "--unit", "_")
    assert res["state"] == "skip"
    assert not (wt / ".tp-scratch").exists()
