"""test_ladder_in_tree.py — the four agent-written ladder files live in the tree (Task 2.1).

design: child-spawn-isolated-ladder-write

``F`` (``<id>.reply.txt``), ``V`` (``<id>.review.txt``), ``C`` (``<id>.check.json``) and
``S`` (``<id>.scan.json``) are the only ladder files a ``tp-worker`` ever writes, and a
worktree-isolated worker refuses a path outside its own tree — so ``ladder_files.py paths``
must print those four under ``<worktree>/.tp-scratch/tp-ladder/<slug>/`` while the
dispatcher-owned three (``R``, ``W``, ``P``) stay in ``<git-common-dir>/tp-ladder/<slug>/``.
The in-tree directory
is scratch, so the writes leave ``git status --porcelain`` empty and the next
``task_verify.py open`` reports no ``dirty-tree``; ``--fresh`` and ``sweep`` clear them.

Every CLI call runs as a subprocess against a ``make_seat`` worktree; ``sweep`` is also
called directly. Stdlib only; no ``claude`` calls.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ladder_files  # noqa: E402
from attempt_fixture import DD, IDENTITY, git, make_seat  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402

SLUG = "demo"
TASK = "1.1"
TREE = ".tp-scratch/tp-ladder"
AGENT_WRITTEN = ("reply", "review", "check", "scan")
DISPATCHER_OWNED = ("record", "watch", "poll")


def _run(*args: str, cwd: Path) -> tuple[int, dict]:
    env = clean_git_env(**IDENTITY)
    proc = subprocess.run([sys.executable, str(HERE / "ladder_files.py"), *args],
                          cwd=str(cwd), capture_output=True, text=True, env=env, timeout=120)
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else {})


def _common(wt: Path) -> Path:
    return Path(git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir"))


def _tree(wt: Path) -> Path:
    return Path(git(wt, "rev-parse", "--show-toplevel")) / TREE / SLUG


def _paths(wt: Path, *extra: str) -> dict:
    rc, out = _run("paths", "--slug", SLUG, "--task", TASK, "--root", str(wt), *extra, cwd=wt)
    assert rc == 0, out
    return out


def _write_agent_files(out: dict) -> list[Path]:
    """What the worker does: write ``F`` and ``V`` at the printed paths."""
    written = []
    for key in AGENT_WRITTEN:
        path = Path(out[key])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"claimed": "green"}\n', encoding="utf-8")
        written.append(path)
    return written


def test_agent_written_files_resolve_in_tree(tmp_path):
    """``reply``/``review`` under the worktree's scratch tree, the other five in the common dir."""
    _seat, wt = make_seat(tmp_path)
    out = _paths(wt)
    tree = _tree(wt).resolve()
    common = _common(wt)

    for key in AGENT_WRITTEN:
        got = Path(out[key]).resolve()
        assert got.parent == tree, f"{key} not under the in-tree ladder dir: {got}"
        assert got == tree / f"{TASK}{ladder_files.SIDE[key]}"
        assert common not in got.parents and not str(got).startswith(str(common))
    for key in DISPATCHER_OWNED:
        got = Path(out[key]).resolve()
        assert got.parent == (common / "tp-ladder" / SLUG).resolve(), f"{key} left the common dir"
    assert _tree(wt).is_dir(), "paths must create the in-tree dir"


def test_in_tree_files_keep_tree_clean(tmp_path):
    """Writing ``F``/``V`` at the printed paths leaves ``git status`` empty and ``open`` clean."""
    _seat, wt = make_seat(tmp_path)
    out = _paths(wt)
    written = _write_agent_files(out)
    assert all(p.is_file() for p in written)
    # Both files are inside the worker's own tree, and the tree stays clean.
    root = wt.resolve()
    assert all(p.resolve().is_relative_to(root) for p in written), written
    assert git(wt, "status", "--porcelain") == "", git(wt, "status", "--porcelain")

    env = clean_git_env(**IDENTITY)
    proc = subprocess.run([sys.executable, str(HERE / "task_verify.py"), "open",
                           "--task", TASK, "--design-dir", DD, "--root", str(wt)],
                          cwd=str(wt), capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stdout} {proc.stderr}"
    assert "dirty-tree" not in proc.stdout + proc.stderr


def test_fresh_clears_in_tree_files(tmp_path):
    """``paths --fresh`` removes both agent-written files, in-tree and legacy."""
    _seat, wt = make_seat(tmp_path)
    out = _paths(wt)
    written = _write_agent_files(out)
    tree = _tree(wt)
    in_tree = []
    for key in AGENT_WRITTEN:
        path = tree / f"{TASK}{ladder_files.SIDE[key]}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"claimed": "green"}\n', encoding="utf-8")
        in_tree.append(path)
    legacy = _common(wt) / "tp-ladder" / SLUG
    legacy.mkdir(parents=True, exist_ok=True)
    for key in AGENT_WRITTEN:
        (legacy / f"{TASK}{ladder_files.SIDE[key]}").write_text('{"claimed": "green"}\n',
                                                                encoding="utf-8")

    cleared = _paths(wt, "--fresh")["cleared"]
    removed = {Path(p).resolve() for p in cleared["removed"]}
    assert {p.resolve() for p in in_tree} <= removed, cleared
    assert {p.resolve() for p in written} <= removed, cleared
    assert not any(p.exists() for p in in_tree + written)
    assert not any((legacy / f"{TASK}{ladder_files.SIDE[k]}").exists() for k in AGENT_WRITTEN)


def test_sweep_clears_stale_in_tree_files(tmp_path):
    """With no live attempt record, ``sweep`` clears an in-tree ``F``; a live task's stays."""
    seat, wt = make_seat(tmp_path)
    _paths(wt)
    stale = _tree(wt) / f"{TASK}{ladder_files.SIDE['reply']}"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text('{"claimed": "green"}\n', encoding="utf-8")

    res = ladder_files.sweep(wt, SLUG)
    removed = {Path(p).resolve() for p in res["removed"]}
    assert stale.resolve() in removed, res
    assert not stale.exists()

    # The same task with a live attempt record keeps its in-tree file.
    stale.write_text('{"claimed": "green"}\n', encoding="utf-8")
    rec_dir = _common(wt) / "tp-attempts" / SLUG
    rec_dir.mkdir(parents=True, exist_ok=True)
    (rec_dir / f"{TASK}-live0001.json").write_text(json.dumps({
        "attempt_id": f"{SLUG}/{TASK}-live0001", "task_id": TASK, "status": "open",
        "owner": {"dispatcher_root": str(seat)}, "attempt_dir": "", "branch": ""}),
        encoding="utf-8")
    res = ladder_files.sweep(wt, SLUG)
    assert stale.exists(), res
    assert stale.resolve() not in {Path(x).resolve() for x in res["removed"]}, res
