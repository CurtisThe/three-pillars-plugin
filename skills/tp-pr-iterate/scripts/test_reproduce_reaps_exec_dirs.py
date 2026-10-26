"""reproduce.py deletes the round's angle exec dirs once the replies are merged.

design: run-scratch-in-fence (review r2, PR #391)

Why: in a launched run (TMPDIR = <wt>/.tp-scratch/run) `prepare` makes each angle's
`tp-angle-*` exec dir (a full tree copy) in the system temp, a `scratch_leftovers`
watch area. The clean-round `provision` + `check --expect` runs before `tail-check`,
so the exec dirs must be gone by then: `reproduce.py` (round tail step 1) reaps them,
guarded, and `tail-check` stays the idempotent backstop.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "_shared"))

import angles  # noqa: E402 — first: it puts skills/_shared on sys.path
import reproduce  # noqa: E402
import round_scratch as rs  # noqa: E402
import run_scratch  # noqa: E402
from test_round_scratch_exec_dir import _write_env  # noqa: E402
from test_scratch_leftovers import fx  # noqa: E402,F401 — the scratch_leftovers fixture

PR = "https://github.com/o/r/pull/42"
_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1"}


@pytest.fixture
def made():
    dirs = []
    yield dirs
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)


def _git(repo, *args) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                         env={**os.environ, **_GIT_ENV}, check=True)
    return out.stdout.strip()


def _commit(repo: Path) -> str:
    (repo / "src").mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        _git(repo, "init", "-q", "-b", "main")
    (repo / "src" / "a.py").write_text("a = 1\n", encoding="utf-8")
    _git(repo, "add", "src/a.py")
    _git(repo, "commit", "-q", "-m", "base")
    return _git(repo, "rev-parse", "HEAD")


def _manifest(rd: Path) -> dict:
    return json.loads((rd / "angles.json").read_text(encoding="utf-8"))


def _prep(root: Path, repo: Path, head: str, made) -> Path:
    rd = rs.prepare(root, PR, angles.DEFAULT_ANGLES, base=head, head=head, effort="high",
                    state_path=str(root / "state.json"), log_path=str(root / "log.md"),
                    repo=str(repo))
    made.extend(e["exec_dir"] for e in _manifest(rd)["angles"])
    return rd


def _clean_replies(rd: Path) -> None:
    for e in _manifest(rd)["angles"]:
        if not e.get("skipped"):
            Path(e["reply_path"]).write_text(
                "```json\n" + json.dumps({"findings": []}) + "\n```\n", encoding="utf-8")


def _reproduce(rd: Path, repo: Path, head: str, capsys) -> int:
    rc = reproduce.main(["--round-dir", str(rd), "--cwd", str(repo), "--head", head])
    out = capsys.readouterr().out
    assert rc == 0, out
    return rc


def test_reproduce_removes_every_exec_dir_of_the_round(tmp_path, made, capsys):
    repo = tmp_path / "repo"
    head = _commit(repo)
    rd = _prep(tmp_path / "proof", repo, head, made)
    execs = [Path(e["exec_dir"]) for e in _manifest(rd)["angles"]]
    assert execs and all(d.is_dir() for d in execs)
    assert any((d / "tree").is_dir() for d in execs)  # the full tree copies
    _clean_replies(rd)
    _reproduce(rd, repo, head, capsys)
    assert not any(d.exists() for d in execs), execs
    assert (rd / "tail" / "findings.json").is_file()
    _write_env(rd)  # tail-check after the reap: an idempotent backstop
    assert rs.main(["tail-check", "--round-dir", str(rd)]) == 0
    assert json.loads(capsys.readouterr().out.strip())["ok"] is True


def test_launched_run_clean_round_scratch_check_passes(fx, made, monkeypatch, capsys):
    """The r2 reproducer's shape, end to end: a launched run's clean round reaches the
    gate with no `tp-angle-*` dir left in the watched system temp."""
    monkeypatch.setattr(run_scratch, "_SYSTEM_TMP", str(fx.tmp))
    head = _commit(fx.wt)
    run = run_scratch.run_dir(fx.wt)
    env = dict(fx.env, TMPDIR=run)
    assert fx.run("provision", env=env)[0] == 0  # Tier 1 baseline
    monkeypatch.setenv("TMPDIR", run)
    rd = _prep(fx.root / "proof", fx.wt, head, made)
    execs = [Path(e["exec_dir"]) for e in _manifest(rd)["angles"]]
    wt, run_r = fx.wt.resolve(), Path(run).resolve()
    for d in execs:  # outside the checkout and the run dir, in the (fake) system temp
        assert d.parent == fx.tmp, d
        assert wt not in d.resolve().parents and run_r not in d.resolve().parents
    rc, out = fx.run("check", env=env)  # control: before the reap the gate would stop
    assert rc == 1 and "tp-angle-" in out
    _clean_replies(rd)
    _reproduce(rd, fx.wt, head, capsys)
    assert not any(d.exists() for d in execs)
    fx.run("provision", env=env)  # clean round, step 4
    rc, out = fx.run("check", "--expect", env=env)
    assert rc == 0, out


def _hand_round(tmp_path: Path, exec_dirs) -> Path:
    rd = tmp_path / "proof" / "rounds" / "42" / "r1"
    (rd / "tail").mkdir(parents=True)
    m = {"pr_url": PR, "round": 1, "ordinal": "r1",
         "angles": [{"name": f"a{i}", "exec_dir": str(d)} for i, d in enumerate(exec_dirs)]}
    (rd / "angles.json").write_text(json.dumps(m), encoding="utf-8")
    return rd


def test_symlink_and_foreign_paths_are_left_alone(tmp_path, monkeypatch, capsys):
    systmp = tmp_path / "systmp"
    systmp.mkdir()
    monkeypatch.setattr(run_scratch, "_SYSTEM_TMP", str(systmp))
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("k", encoding="utf-8")
    link = systmp / "tp-angle-link-1"
    link.symlink_to(victim, target_is_directory=True)
    foreign = systmp / "other-dir"
    nested = systmp / "sub" / "tp-angle-deep-1"
    via_link = systmp / "hop"
    via_link.symlink_to(victim, target_is_directory=True)
    (victim / "tp-angle-hop-1").mkdir()
    good = systmp / "tp-angle-good-1"
    for d in (foreign, nested, good / "tree"):
        d.mkdir(parents=True)
    hop = via_link / "tp-angle-hop-1"
    rd = _hand_round(tmp_path, [link, foreign, nested, hop, good, "relative/tp-angle-x"])
    res = rs.reap_exec_dirs(rd)
    assert not good.exists()
    assert link.is_symlink() and (victim / "keep.txt").is_file()
    assert foreign.is_dir() and nested.is_dir() and (victim / "tp-angle-hop-1").is_dir()
    assert set(res["exec_refused"]) == {str(link), str(foreign), str(nested), str(hop),
                                        "relative/tp-angle-x"}
    assert res["exec_failed"] == []
    assert "left in place" in capsys.readouterr().err


def test_missing_exec_dir_and_bad_manifest_are_fine(tmp_path, monkeypatch):
    systmp = tmp_path / "systmp"
    systmp.mkdir()
    monkeypatch.setattr(run_scratch, "_SYSTEM_TMP", str(systmp))
    rd = _hand_round(tmp_path, [systmp / "tp-angle-gone-1"])
    assert rs.reap_exec_dirs(rd) == {"exec_failed": [], "exec_refused": []}
    (rd / "angles.json").write_text("{not json", encoding="utf-8")
    assert rs.reap_exec_dirs(rd) == {"exec_failed": [], "exec_refused": []}


def test_tail_check_still_removes_anything_left(tmp_path, made, monkeypatch, capsys):
    """A round whose reproduce never reaped (an aborted tail, a refused path): tail-check
    still deletes every manifest exec dir."""
    repo = tmp_path / "repo"
    head = _commit(repo)
    rd = _prep(tmp_path / "proof", repo, head, made)
    execs = [Path(e["exec_dir"]) for e in _manifest(rd)["angles"]]
    monkeypatch.setattr(rs, "_reapable", lambda d: False)  # reproduce refuses every path
    _clean_replies(rd)
    _reproduce(rd, repo, head, capsys)
    assert all(d.is_dir() for d in execs)
    _write_env(rd)
    assert rs.main(["tail-check", "--round-dir", str(rd)]) == 0
    assert not any(d.exists() for d in execs)
