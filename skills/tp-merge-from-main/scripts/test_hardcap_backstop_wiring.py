"""`merge_back` calls the B3 hard-cap backstop before it computes `needs_human` (Task 5.2).

The driver resolves a living doc and stages it, and today can stage it OVER its `file_size_guard`
hard cap when the MERGE is what pushed it over (neither input side was). `apply_hard_cap_backstop`
(5.1) fixes that; this module proves the driver actually RUNS it: a real `merge_back` over a tmp
repo whose merged doc is over the cap ends with the doc rolled and staged at or under the cap,
nothing unmerged left for it, and a report that needs no human.

Rule: skills/_shared/test-fragility.md — behaviour only. A deferred file keeps git's conflict
markers that QUOTE both sides, so the assertions are on the DECISIONS (report buckets, the index's
own `git ls-files -u`, the staged bytes), never on markdown prose.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

if shutil.which("git") is None:
    pytest.skip("git unavailable", allow_module_level=True)

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
import file_size_guard  # noqa: E402
import living_doc_archive  # noqa: E402
import merge_driver  # noqa: E402
from merge_driver import merge_back  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402  # shipped scrub; git_env is dev-only

LIVE = "three-pillars-docs/product_roadmap.md"
ARCH = living_doc_archive.ARCHIVES[LIVE]
SOFT, HARD = file_size_guard.char_caps(LIVE, False)
HEAD_TXT = "# Product Roadmap\n\n## History\n\n"
ARCH_BASE = "# Product Roadmap — Archive\n\n## History\n\n- 2026-09-01 — ancient entry\n"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def entry(n, size=700):
    """One plain-date History bullet, padded to exactly `size` chars."""
    body = "- 2026-%02d-%02d — entry %d" % (n // 28 + 1, n % 28 + 1, n)
    return "%s %s\n" % (body, "x" * (size - len(body) - 1))


def doc(numbers, size=700):
    return HEAD_TXT + "".join(entry(n, size) for n in numbers)


BASE_DOC = doc([1])
OURS_DOC = doc(list(range(2, 13)) + [1])       # under the hard cap
THEIRS_DOC = doc(list(range(30, 41)) + [1])    # under the hard cap
MERGED_COUNTS = list(range(2, 13)) + list(range(30, 41)) + [1]
assert len(OURS_DOC) < HARD and len(THEIRS_DOC) < HARD, "each side starts under the cap"
assert len(doc(MERGED_COUNTS)) > HARD, "the merge is what pushes the doc over the cap"


def git(repo, *args, check=False):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=check, env=clean_git_env(**IDENTITY))


def write(repo, rel, content):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def commit(repo, msg):
    git(repo, "add", "-A", check=True)
    git(repo, "commit", "-q", "-m", msg, check=True)


def setup(tmp_path):
    """Base commit, a `feat` side adding its own History bullets, a `master` side adding different
    ones, checked out on `feat` — the shape `merge_back` is used in."""
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master", check=True)
    write(repo, LIVE, BASE_DOC)
    write(repo, ARCH, ARCH_BASE)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "feat", check=True)
    write(repo, LIVE, OURS_DOC)
    commit(repo, "feat")
    git(repo, "checkout", "-q", "master", check=True)
    write(repo, LIVE, THEIRS_DOC)
    commit(repo, "master")
    git(repo, "checkout", "-q", "feat", check=True)
    return repo


def unmerged(repo):
    """`git ls-files -u`: the index's own statement of what is still conflicted."""
    out = git(repo, "ls-files", "-u").stdout
    return {ln.split("\t", 1)[1] for ln in out.splitlines() if ln.strip()}


def stage0(repo, path):
    """Index stage 0 (the resolved entry) of `path`, or None when the index holds no such stage."""
    r = git(repo, "show", ":%d:%s" % (0, path))
    return r.stdout if r.returncode == 0 else None


def outcome_of(rep, path):
    return next(o for o in rep.outcomes if o["path"] == path)


def test_merge_back_rolls_a_doc_the_merge_pushed_over_its_cap(tmp_path):
    """Both sides are under the hard cap; the merged doc is over it. `merge_back` must run the
    backstop: the doc ends rolled at or under the cap, staged with its archive, with nothing
    unmerged left for it, and the report needs no human."""
    repo = setup(tmp_path)
    report = merge_back(str(repo), "master")
    live = (repo / LIVE).read_text(encoding="utf-8")
    arch = (repo / ARCH).read_text(encoding="utf-8")
    assert LIVE in report.auto_resolved, report.to_json()
    assert report.deferred == [] and report.partially_resolved == [], report.to_json()
    assert report.needs_human is False, report.to_json()
    assert len(live) <= HARD, len(live)
    assert unmerged(repo) == set(), unmerged(repo)
    assert stage0(repo, LIVE) == live, "the rolled doc is not what the index holds"
    assert stage0(repo, ARCH) == arch, "the rolled archive is not what the index holds"
    for n in MERGED_COUNTS:                        # the roll moved entries, it lost none
        assert (live + arch).count(entry(n)) == 1, n
    assert "hard-cap-rollover" in outcome_of(report, LIVE)["resolved_classes"], report.to_json()


def test_the_backstop_runs_before_needs_human_is_computed(tmp_path):
    """A backstop deferral moves the path out of `auto_resolved` into `deferred`, so `needs_human`
    can only be right if the backstop ran BEFORE that field was computed. With no deferral the
    report says no human is needed — the ordering this task pins."""
    repo = setup(tmp_path)
    report = merge_back(str(repo), "master")
    assert report.deferred == [], report.to_json()
    assert report.needs_human is bool(report.partially_resolved or report.deferred), report.to_json()
    assert report.needs_human is False, report.to_json()


def test_the_driver_prints_exactly_one_json_document(tmp_path, capsys):
    """The backstop must not print: `_main`'s stdout is the report and nothing else, so it stays
    parseable by the skill."""
    repo = setup(tmp_path)
    code = merge_driver._main([str(repo), "master"])
    out = capsys.readouterr().out
    assert code == 0, out
    doc_out = json.loads(out)
    assert doc_out["needs_human"] is False and LIVE in doc_out["auto_resolved"], out
    assert len((repo / LIVE).read_text(encoding="utf-8")) <= HARD
