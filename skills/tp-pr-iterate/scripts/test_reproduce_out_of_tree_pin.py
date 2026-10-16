"""test_reproduce_out_of_tree_pin.py — a reproducer whose round scratch sits under the
git-dir proof root runs against the reviewed linked worktree, never the main checkout,
with the reviewed tree's own pytest config and conftest chain (PR #197 rounds 1-3).

design: review-proof-out-of-tree (PR #197 structural fix)

The default proof root of a linked worktree is `<main>/.git/worktrees/<name>/...`, so
`R/tail/repro_<i>.py` has the MAIN checkout as an ancestor. Run from there, pytest took
that checkout's `pytest.ini` and `conftest.py` and imported its code (round 1), and
emulating pytest's discovery with `--rootdir`/`-c`/`--confcutdir` first missed
`pytest.toml` (round 2) and then dropped the tree's own root `conftest.py` (round 3).
`reproduce` now runs a transient copy from INSIDE the reviewed tree
(`reproduce.SCRATCH_PARTS`), so pytest's own discovery applies, and removes it in a
`finally` so nothing is left under `.three-pillars/`.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import loop_itest as it  # noqa: E402
import proof_root  # noqa: E402
import reproduce  # noqa: E402

GOOD = "def add(a, b):\n    return a + b\n"
BAD = "def add(a, b):\n    return a - b\n"  # the PR head's bug
REPRO = {"kind": "test",
         "source": "import calc\n\n\ndef test_add():\n    assert calc.add(2, 3) == 5\n"}
CONFTEST = "import pytest\n\n\n@pytest.fixture\ndef expected():\n    return 5\n"
REPRO_FIXTURE = {"kind": "test", "source": ("import calc\n\n\ndef test_add(expected):\n"
                                            "    assert calc.add(2, 3) == expected\n")}


def _finding(repro=REPRO) -> dict:
    return {"file": "calc.py", "line_range": [1, 2], "summary": "add subtracts",
            "class": "P", "blocking": True, "verdict": "structural", "reproducer": repro}


def _main_and_pr(tmp_path, *, tracked_ini: bool, head=BAD, conftest=""):
    """A main checkout with a correct `calc.add` and a linked worktree whose PR head
    carries `head`. `tracked_ini=False` keeps the main checkout's pytest config
    untracked, so the worktree has none of its own. `conftest` is a tracked root
    conftest shared by both checkouts."""
    main = tmp_path / "main"
    main.mkdir()
    it.git(main, "init", "-q", "-b", "main")
    it.write(main, "calc.py", GOOD)
    if tracked_ini:
        it.write(main, "pytest.ini", "[pytest]\npythonpath = .\n")
        it.write(main, "conftest.py", conftest)
    elif conftest:
        it.write(main, "conftest.py", conftest)
    it.git(main, "add", "-A")
    it.git(main, "commit", "-q", "-m", "base")
    if not tracked_ini:
        it.write(main, "pytest.ini", "[pytest]\npythonpath = .\n")
        it.write(main, "conftest.py", conftest)
    wt = tmp_path / "wt"
    it.git(main, "worktree", "add", "-q", "-b", "pr", str(wt))
    it.write(wt, "calc.py", head)
    it.git(wt, "commit", "-q", "--allow-empty", "-am", "head")
    return main, wt


def _tail(wt) -> Path:
    root = proof_root.resolve_proof_root(start=wt, config={}, env={})
    return root / "rounds" / "1" / "r1" / "tail"


def _run(wt, finding=None, runner=subprocess.run):
    out, records = reproduce.run_reproducers([finding or _finding()], cwd=str(wt),
                                             scratch_dir=_tail(wt), runner=runner,
                                             timeout=120)
    return out[0], records


# --- round 1: the main checkout's config and code must not leak in ------------------


def test_scratch_sits_under_the_main_checkout(tmp_path):
    main, wt = _main_and_pr(tmp_path, tracked_ini=True)
    assert main.resolve() in _tail(wt).resolve().parents  # the precondition of the bug


def test_pr_head_defect_reproduces_when_both_checkouts_carry_a_config(tmp_path, monkeypatch):
    _, wt = _main_and_pr(tmp_path, tracked_ini=True)
    monkeypatch.chdir(wt)
    f, records = _run(wt)
    assert f["blocking"] is True and "downgrade" not in f, (f.get("downgrade"), records)


def test_pr_head_defect_reproduces_when_only_main_has_a_config(tmp_path, monkeypatch):
    _, wt = _main_and_pr(tmp_path, tracked_ini=False)
    assert not (wt / "pytest.ini").exists()
    monkeypatch.chdir(wt)
    f, records = _run(wt)
    assert f["blocking"] is True and "downgrade" not in f, (f.get("downgrade"), records)


# --- round 3: the reviewed tree's own root conftest reaches the reproducer ----------


@pytest.mark.parametrize("tracked_ini", [True, False], ids=["with-ini", "no-ini"])
def test_root_conftest_fixture_reaches_the_reproducer_on_a_correct_head(tmp_path, tracked_ini):
    _, wt = _main_and_pr(tmp_path, tracked_ini=tracked_ini, head=GOOD, conftest=CONFTEST)
    assert (wt / "conftest.py").read_text(encoding="utf-8") == CONFTEST
    f, records = _run(wt, _finding(REPRO_FIXTURE))
    assert f["blocking"] is False and f["downgrade"]["reason"] == "not-reproduced", records


def test_root_conftest_fixture_still_lets_a_real_defect_reproduce(tmp_path):
    _, wt = _main_and_pr(tmp_path, tracked_ini=True, head=BAD, conftest=CONFTEST)
    f, records = _run(wt, _finding(REPRO_FIXTURE))
    assert f["blocking"] is True and "downgrade" not in f, (f.get("downgrade"), records)


# --- round 2: a tree configured by pytest.toml keeps its config ---------------------


def test_pytest_toml_config_of_the_reviewed_tree_is_honoured(tmp_path):
    tree = tmp_path / "tree"
    (tree / "src").mkdir(parents=True)
    (tree / "pytest.toml").write_text('[pytest]\npythonpath = ["src"]\n')
    (tree / "src" / "calc.py").write_text(GOOD)
    out, _ = reproduce.run_reproducers([_finding()], cwd=str(tree),
                                       scratch_dir=tmp_path / "scratch",
                                       runner=subprocess.run, timeout=120)
    assert out[0]["blocking"] is False, out[0].get("downgrade")


# --- nothing is left under .three-pillars/ --------------------------------------------


def _tree(tmp_path, *, with_config=False) -> Path:
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "pytest.ini").write_text("[pytest]\npythonpath = .\n")
    (tree / "calc.py").write_text(GOOD)
    if with_config:
        (tree / ".three-pillars").mkdir()
        (tree / ".three-pillars" / "config.json").write_text("{}\n")
    return tree


def _run_tree(tree, tmp_path, runner=subprocess.run):
    return reproduce.run_reproducers([_finding()], cwd=str(tree),
                                     scratch_dir=tmp_path / "scratch", runner=runner,
                                     timeout=120)


def test_nothing_left_under_three_pillars_after_a_run(tmp_path):
    tree = _tree(tmp_path)
    out, _ = _run_tree(tree, tmp_path)
    assert out[0]["blocking"] is False, out[0].get("downgrade")
    assert not (tree / ".three-pillars").exists()
    assert (tmp_path / "scratch" / "repro_0.py").read_text(encoding="utf-8") == REPRO["source"]  # audit copy


def test_a_pre_existing_three_pillars_dir_is_left_as_found(tmp_path):
    tree = _tree(tmp_path, with_config=True)
    _run_tree(tree, tmp_path)
    assert sorted(p.name for p in (tree / ".three-pillars").iterdir()) == ["config.json"]


def test_nothing_left_when_the_runner_raises_or_times_out(tmp_path):
    tree = _tree(tmp_path)

    def boom(argv, **kw):
        raise RuntimeError("runner crashed")

    with pytest.raises(RuntimeError):
        _run_tree(tree, tmp_path, runner=boom)
    assert not (tree / ".three-pillars").exists()

    def slow(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    out, _ = _run_tree(tree, tmp_path, runner=slow)
    assert out[0]["downgrade"]["reason"] == "inconclusive"
    assert not (tree / ".three-pillars").exists()


def test_stale_leftover_of_a_dead_run_is_cleared_and_a_live_siblings_is_kept(tmp_path):
    tree = _tree(tmp_path)
    parent = tree / ".three-pillars" / "repro-scratch"
    dead = next(p for p in range(4194300, 2, -1) if not reproduce._alive(p))
    (parent / f"{dead}-deadbeef").mkdir(parents=True)
    (parent / f"{dead}-deadbeef" / "repro_0.py").write_text("x")
    (parent / f"{os.getpid()}-live").mkdir()
    (parent / "not-a-pid").mkdir()
    _run_tree(tree, tmp_path)
    assert sorted(p.name for p in parent.iterdir()) == [f"{os.getpid()}-live"]
