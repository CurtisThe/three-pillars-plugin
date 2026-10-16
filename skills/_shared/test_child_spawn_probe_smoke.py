"""Tests for child_spawn.py — `probe` runs the smoke verdict with its caches.

strata-session-isolation task 4.7 (design §B8): on a per-run cache miss with every static check
passing, `probe` sweeps stale leftovers first, then uses a cached smoke pass for this `claude
--version`, else runs `smoke`. A pass is cached per repo; a failure is cached only in that run's
`probe.json`, so the next run smokes again. Everything is monkeypatched (static checks, `cmd_sweep`,
`cmd_smoke`, `claude_version`): no test launches any process.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_proc  # noqa: E402
import child_slot  # noqa: E402
import child_spawn  # noqa: E402
from attempt_fixture import commit, git  # noqa: E402


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"README.md": "demo\n"}, "base")
    return repo


class Probe:
    """A repo plus patched checks; `run(id)` probes once and returns `(code, payload)`."""

    def __init__(self, monkeypatch, repo: Path, capsys) -> None:
        self.repo, self.capsys, self.calls = repo, capsys, []
        self.version, self.smoke_result = "1.0.0", {"ok": True, "why": "ok"}
        monkeypatch.delenv("TP_CHILD_SPAWN", raising=False)
        monkeypatch.delenv("TP_CHILD_SPAWN_CLAUDE", raising=False)
        monkeypatch.setattr(shutil, "which", lambda name, *a, **k: f"/usr/bin/{name}")
        monkeypatch.setattr(child_proc, "has_proc", lambda: True)
        monkeypatch.setattr(child_slot, "can_release_session", lambda *a, **k: True)
        monkeypatch.setattr(child_spawn, "claude_version", lambda env=None: self.version)
        monkeypatch.setattr(child_spawn, "cmd_sweep", self._sweep)
        monkeypatch.setattr(child_spawn, "cmd_smoke", self._smoke)

    def _sweep(self, run=None, stale=False, root="."):
        self.calls.append(("sweep", stale))
        return {"stopped": [], "gone": []}

    def _smoke(self, *a, **k):
        self.calls.append(("smoke",))
        return {**self.smoke_result, "claude_version": self.version}

    def smokes(self) -> int:
        return self.calls.count(("smoke",))

    def run(self, run_id: str) -> tuple[int, dict]:
        code = child_spawn.main(["probe", "--run", run_id, "--root", str(self.repo)])
        return code, json.loads(self.capsys.readouterr().out.strip().splitlines()[-1])


def test_pass_cached_per_version(monkeypatch, tmp_path, capsys) -> None:
    p = Probe(monkeypatch, _repo(tmp_path), capsys)
    code, res = p.run("runa0001")
    assert (code, res["mode"]) == (0, "child")
    assert p.smokes() == 1
    code, res = p.run("runb0002")
    assert (code, res["mode"]) == (0, "child")
    assert p.smokes() == 1  # same version: the cached pass answers
    p.version = "2.0.0"
    code, res = p.run("runc0003")
    assert (code, res["mode"]) == (0, "child")
    assert p.smokes() == 2  # a new version is a miss


def test_failure_rechecked_next_run(monkeypatch, tmp_path, capsys) -> None:
    p = Probe(monkeypatch, _repo(tmp_path), capsys)
    p.smoke_result = {"ok": False, "why": "denied: Bash"}
    code, res = p.run("runa0001")
    assert code == 4
    assert res == {"mode": "in-process", "why": "smoke: denied: Bash"}
    assert p.smokes() == 1
    code, res = p.run("runa0001")  # same run: probe.json answers
    assert (code, res["why"]) == (4, "smoke: denied: Bash")
    assert p.smokes() == 1
    p.run("runb0002")  # next run smokes again
    assert p.smokes() == 2


def test_sweep_before_smoke(monkeypatch, tmp_path, capsys) -> None:
    p = Probe(monkeypatch, _repo(tmp_path), capsys)
    p.run("runa0001")
    assert p.calls.index(("sweep", True)) < p.calls.index(("smoke",))
