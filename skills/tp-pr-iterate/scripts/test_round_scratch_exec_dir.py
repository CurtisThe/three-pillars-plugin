"""Tests for per-angle exec dirs and the angle-dir strip in round_scratch.

design: fragile-test-prevention (Task 12.2)
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import angles  # noqa: E402
import round_scratch as rs  # noqa: E402

PR = "https://github.com/o/r/pull/42"


def _env(terminal=None):
    return {"schema": "tp-pr-iterate/round-tail/v1", "round": 1, "head_reviewed": "a" * 40,
            "head_after": "b" * 40,
            "tally": {"P": 0, "X": 0, "T": 0, "C": 0, "blocking": 0, "degraded": 0},
            "downgraded": 0, "notes": 0, "action": "noop", "fix_commit": None,
            "terminal": terminal, "converged": False,
            "budget": {"iteration": 1, "round_cap": 6, "signal": None, "holding": []},
            "finalizer_stop": None, "summary": "s"}


def _write_env(rd: Path, terminal=None):
    (rd / "tail" / "envelope.json").write_text(json.dumps(_env(terminal)), encoding="utf-8")


def _manifest(rd: Path):
    return json.loads((rd / "angles.json").read_text(encoding="utf-8"))


@pytest.fixture
def made():
    dirs = []
    yield dirs
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)


def _prep(root, made):
    rd = rs.prepare(root, PR, angles.DEFAULT_ANGLES, base="b0", head="h1", effort="high",
                    state_path=str(root / "state.json"), log_path=str(root / "log.md"))
    made.extend(e["exec_dir"] for e in _manifest(rd)["angles"])
    return rd


def test_exec_dir_outside_root_absolute_existing_and_in_prompt(tmp_path, made):
    root = tmp_path / "proof"
    rd = _prep(root, made)
    for e in _manifest(rd)["angles"]:
        d = Path(e["exec_dir"])
        assert d.is_absolute() and d.is_dir()
        assert d.name.startswith(f"tp-angle-{e['name']}-")
        assert root.resolve() not in d.resolve().parents
        assert e["exec_dir"] in e["prompt"]


def test_tail_check_deletes_exec_dirs(tmp_path, made, capsys):
    rd = _prep(tmp_path / "proof", made)
    _write_env(rd)
    assert rs.main(["tail-check", "--round-dir", str(rd)]) == 0
    assert capsys.readouterr().out.strip() == json.dumps({"ok": True})
    assert not any(Path(d).exists() for d in made)


def test_deletion_failure_is_reported_and_round_does_not_fail(tmp_path, made, monkeypatch, capsys):
    rd = _prep(tmp_path / "proof", made)
    _write_env(rd)

    def boom(*a, **k):
        raise PermissionError("nope")

    # Scoped: the fixtures' own teardown (made, skills/conftest.py) also calls
    # shutil.rmtree, and runs while an unscoped patch is still active.
    with monkeypatch.context() as patched:
        patched.setattr(rs.shutil, "rmtree", boom)
        assert rs.main(["tail-check", "--round-dir", str(rd)]) == 0
        cap = capsys.readouterr()
        assert cap.out.strip() == json.dumps({"ok": True})
        assert "tp-angle-" in cap.err
        assert rs.cleanup_round(rd, strip=False)["exec_failed"]


def test_prepare_strips_previous_round_but_keeps_reply(tmp_path, made, capsys):
    root = tmp_path / "proof"
    r1 = _prep(root, made)
    name = _manifest(r1)["angles"][0]["name"]
    (r1 / name / "reply.md").write_text("reply", encoding="utf-8")
    (r1 / name / "stray.py").write_text("x", encoding="utf-8")
    _write_env(r1)
    _prep(root, made)
    assert (r1 / name / "reply.md").read_text(encoding="utf-8") == "reply"
    assert not (r1 / name / "stray.py").exists()
    assert f"stripped {name}/stray.py" in capsys.readouterr().err


@pytest.mark.parametrize("terminal,stripped", [(None, False), ("two-stable", True)])
def test_tail_check_strips_only_when_loop_closing(tmp_path, made, terminal, stripped):
    rd = _prep(tmp_path / "proof", made)
    name = _manifest(rd)["angles"][0]["name"]
    (rd / name / "reply.md").write_text("reply", encoding="utf-8")
    (rd / name / "stray.py").write_text("x", encoding="utf-8")
    _write_env(rd, terminal)
    assert rs.main(["tail-check", "--round-dir", str(rd)]) == 0
    assert (rd / name / "stray.py").exists() is (not stripped)
    assert (rd / name / "reply.md").exists()


def test_manifest_without_exec_dir_still_tail_checks(tmp_path, made):
    rd = _prep(tmp_path / "proof", made)
    m = _manifest(rd)
    for e in m["angles"]:
        e.pop("exec_dir")
    (rd / "angles.json").write_text(json.dumps(m), encoding="utf-8")
    _write_env(rd)
    assert rs.main(["tail-check", "--round-dir", str(rd)]) == 0


def test_prepare_reaps_exec_dirs_of_a_round_that_never_tail_checked(tmp_path, made):
    root = tmp_path / "proof"
    r1 = _prep(root, made)
    leaked = [Path(e["exec_dir"]) for e in _manifest(r1)["angles"]]
    assert leaked and all(d.is_dir() for d in leaked)
    _write_env(r1)  # the tail delivered, but the loop aborted before tail-check
    _prep(root, made)
    assert not any(d.exists() for d in leaked)


def test_exec_dirs_leave_an_in_tree_run_tmpdir(tmp_path, made, monkeypatch):
    """Review r1 (PR #391): a run's TMPDIR is inside its checkout, so a reviewer copy made under
    it would let a git command in the copy act on the run's branch; the exec dir goes outside."""
    import run_scratch
    sysdir = tmp_path / "systmp"
    sysdir.mkdir()
    monkeypatch.setattr(run_scratch, "_SYSTEM_TMP", str(sysdir))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "wt" / ".tp-scratch" / "run"))
    rd = _prep(tmp_path / "proof", made)
    for e in _manifest(rd)["angles"]:
        assert Path(e["exec_dir"]).parent == sysdir, e["exec_dir"]
