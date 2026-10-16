"""Tier 6's shipped writeback, scoped add, commit and push, run verbatim in a fixture repo.

design: design-complete-final-doc-state (plan task 3.3). Oracle: example, per
`skills/_shared/test-fragility.md`. The commands come out of the SKILL.md through the `_chain` of
`test_tier6_doc_writeback.py` (which pins where they sit in Tier 6); this file runs them in a work
repo with a bare origin (the `_shipped` approach of `test_post_merge_inventory_wiring.py`). Each test
pins one property: the exact flipped row, the clean no-op, the edit landing on origin, and a refused
push leaving origin untouched.

Run with: python3 -m pytest skills/tp-run-full-design/scripts/test_tier6_doc_writeback_shipped.py -q
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from test_tier6_doc_writeback import DONE_DIR, LIVE, NUMBERED, NUMBERLESS, REPO_ROOT, ROW, SLUG, _chain

import skill_text

# The Tier 6 commands `_chain` yields are parsed out of this text (no split yet: SKILL.md alone).
SKILL_TEXT = skill_text.read_skill_text("tp-run-full-design")


def _env() -> dict:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=f", "-c", "user.email=f@t", *args],
                          capture_output=True, text=True, check=True, env=_env())


def _argv(words: list[str]) -> list[str]:
    """A shipped command as an argv, its placeholders bound to this checkout and the fixture."""
    argv = [w.replace("$TP_ROOT", str(REPO_ROOT)).replace("{slug}", SLUG).replace("{n}", "42") for w in words]
    return [sys.executable if a == "python3" else a for a in argv]


def _run_shipped(name: str, cwd: Path, paths: list[str] | None = None):
    words = _chain()[name][1].words
    if paths is not None:
        words = [p for w in words for p in (paths if "edits[]" in w else [w])]
    argv = _argv(words)
    if argv[0] == "git":
        argv = ["git", "-c", "user.name=f", "-c", "user.email=f@t", *argv[1:]]
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, env=_env())


def _fixture(tmp_path: Path, *, reject_pushes: bool = False) -> tuple[Path, Path]:
    """A work repo on `tp/{slug}` holding the post-archive number-free row, and its bare origin."""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=_env())
    _git(work, "init", "-q", "-b", f"tp/{SLUG}")
    (work / DONE_DIR).mkdir(parents=True)
    (work / DONE_DIR / "design.md").write_text("# d\n", encoding="utf-8")
    (work / LIVE).write_text("\n".join([
        "# Product Roadmap", "", "## Design Inventory", "", "### Active", "",
        "| Name | What | Type | Status | Track |", "|---|---|---|---|---|",
        "| other | Stays live. | design | Seed | Docs |", ROW, ""]) + "\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "archived")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "origin", f"tp/{SLUG}")
    if reject_pushes:
        hook = origin / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    return work, origin


def _on_origin(origin: Path) -> str:
    return subprocess.run(["git", "--git-dir", str(origin), "show", f"tp/{SLUG}:{LIVE}"],
                          capture_output=True, text=True, check=True, env=_env()).stdout


def _writeback(work: Path) -> dict:
    ran = _run_shipped("writeback", work)
    assert ran.returncode == 0, "writeback exited non-zero: " + ran.stdout + ran.stderr
    return json.loads(ran.stdout)


def _write_add_commit(work: Path) -> None:
    paths = [e["path"] for e in _writeback(work)["edits"]]
    assert _run_shipped("add", work, paths).returncode == 0, "the scoped add failed"
    committed = _run_shipped("commit", work)
    assert committed.returncode == 0, "the writeback commit failed: " + committed.stdout + committed.stderr


def test_shipped_writeback_flips_the_row_to_the_pr_number(tmp_path):
    work, _origin = _fixture(tmp_path)

    payload = _writeback(work)

    assert [e["path"] for e in payload["edits"]] == [LIVE], f"writeback edited {payload['edits']}, not [{LIVE}]"
    status = _git(work, "status", "--porcelain", "--untracked-files=all").stdout.splitlines()
    touched = sorted(ln[3:] for ln in status if ln.strip())
    assert touched == [LIVE], f"writeback touched paths beyond {LIVE}: {touched}"
    rows = [ln for ln in (work / LIVE).read_text(encoding="utf-8").splitlines() if ln.startswith(f"| {SLUG} ")]
    expected = ROW.replace(NUMBERLESS, NUMBERED)
    assert rows == [expected], f"flipped row is not exactly {expected!r}: {rows}"


def test_shipped_writeback_with_nothing_to_flip_exits_clean_and_edits_nothing(tmp_path):
    work, _origin = _fixture(tmp_path)
    (work / LIVE).write_text("# Product Roadmap\n", encoding="utf-8")
    _git(work, "commit", "-q", "-am", "no row")

    edits = _writeback(work)["edits"]

    assert edits == [], f"no-op writeback reported edits: {edits}"
    status = _git(work, "status", "--porcelain").stdout
    assert status == "", f"no-op writeback dirtied the tree: {status}"


def test_shipped_add_commit_and_push_land_the_number_on_the_branch(tmp_path):
    work, origin = _fixture(tmp_path)
    before = _on_origin(origin)
    _write_add_commit(work)

    pushed = _run_shipped("push", work)

    assert pushed.returncode == 0, "the writeback push failed: " + pushed.stdout + pushed.stderr
    local_head = _git(work, "rev-parse", "HEAD").stdout.strip()
    remote_head = subprocess.run(["git", "--git-dir", str(origin), "rev-parse", f"tp/{SLUG}"],
                                 capture_output=True, text=True, check=True, env=_env()).stdout.strip()
    assert remote_head == local_head, f"origin tp/{SLUG} is {remote_head}, not the writeback commit {local_head}"
    landed = _on_origin(origin)
    assert landed != before, "the writeback push landed no change on origin"
    assert landed == (work / LIVE).read_text(encoding="utf-8"), "origin's roadmap differs from the written-back one"


def test_a_failed_push_leaves_the_number_free_text_on_the_head(tmp_path):
    work, origin = _fixture(tmp_path, reject_pushes=True)
    before = _on_origin(origin)
    _write_add_commit(work)

    pushed = _run_shipped("push", work)

    assert pushed.returncode != 0, "a push the origin rejects exited zero"
    assert _on_origin(origin) == before, "a rejected push changed origin's roadmap"
