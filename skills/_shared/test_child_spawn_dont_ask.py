"""test_child_spawn_dont_ask.py — the A4 capability fallback: `dontAsk` when the CLI has it.

strata-classifier-cost-followups task 1.4 (design §A4): the probe records whether the installed
`claude` accepts `dontAsk` — its `--help` names the mode — and `start` launches with that answer,
re-checking the CLI only when the run has no cached probe. An older CLI that lacks `dontAsk` gets
the same allow and deny lists under `--permission-mode auto` plus exactly one `W:` line naming the
~1 classifier check per session the fallback costs; never `bypassPermissions`. A smoke pass is
cached per `claude --version` **and** the mode it was earned in, so a pass recorded under `auto`
never lets a `dontAsk` probe skip its smoke (or the other way round).

Nothing here starts a live `claude`, router or GPU job: the claude is `child_spawn_fixture`'s fake
reached through `TP_CHILD_SPAWN_CLAUDE` (its `--help` prints the modes it accepts, and
`FAKE_PERMISSION_MODES` narrows them to an older CLI without `dontAsk`), `FAKE_ARGV_OUT` records the
argv the fake actually parsed, and the probe tests patch every static check so no process starts at
all. Every `start` test reaps the one group it launched, on a failing assert too.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_permissions as cp  # noqa: E402
import child_proc  # noqa: E402
import child_slot  # noqa: E402
import child_spawn  # noqa: E402
import child_state  # noqa: E402
import stopped_agents  # noqa: E402
from attempt_fixture import commit, git  # noqa: E402
from child_spawn_fixture import FAKE_VERSION_DEFAULT, write_fake_claude  # noqa: E402

RUN = "dontask1"
AGENT_REF = "three-pillars:tp-runbook"
MODEL = "haiku"
SITE = "S1"
PROMPT = "Report the output of `git status --porcelain`.\n"
REAP_TIMEOUT_S = 15
# An older CLI's `--permission-mode` choices: no `dontAsk` (design §A4's fallback).
OLD_CLI_MODES = "acceptEdits,auto,manual,plan"


def _write_broken_claude(dir) -> Path:
    """An executable that exits 1 for every argv — a `--help` nobody can read."""
    out = Path(dir) / "claude"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    out.chmod(0o755)
    return out


def test_dont_ask_supported_default_fake(monkeypatch, tmp_path) -> None:
    """The default fake names `dontAsk` in its `--help`, like CLI 2.1.296."""
    monkeypatch.setenv("TP_CHILD_SPAWN_CLAUDE", str(write_fake_claude(tmp_path / "bin")))
    assert cp.dont_ask_supported(os.environ) is True


def test_dont_ask_supported_old_cli_has_no_dontask(monkeypatch, tmp_path) -> None:
    """`FAKE_PERMISSION_MODES` without `dontAsk`: the answer is False, not an exception."""
    monkeypatch.setenv("TP_CHILD_SPAWN_CLAUDE", str(write_fake_claude(tmp_path / "bin")))
    monkeypatch.setenv("FAKE_PERMISSION_MODES", OLD_CLI_MODES)
    assert cp.dont_ask_supported(os.environ) is False


def test_dont_ask_supported_missing_binary_is_false(monkeypatch, tmp_path) -> None:
    """No binary at all: False. A capability check never raises past its answer."""
    monkeypatch.setenv("TP_CHILD_SPAWN_CLAUDE", str(tmp_path / "nope" / "claude"))
    assert cp.dont_ask_supported(os.environ) is False


def test_dont_ask_supported_help_that_exits_1_is_false(monkeypatch, tmp_path) -> None:
    """A `--help` that fails is no evidence of the mode: False."""
    monkeypatch.setenv("TP_CHILD_SPAWN_CLAUDE", str(_write_broken_claude(tmp_path / "bin")))
    assert cp.dont_ask_supported(os.environ) is False


class _Probe:
    """One repo, every static check patched; `run(id)` probes once and answers `(code, payload)`."""

    def __init__(self, monkeypatch, tmp_path: Path, capsys) -> None:
        self.tmp, self.capsys = tmp_path, capsys
        self.repo = tmp_path / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        commit(self.repo, {"README.md": "demo\n"}, "base")
        self.smokes = 0
        monkeypatch.delenv("TP_CHILD_SPAWN", raising=False)
        monkeypatch.setenv("TP_CHILD_SPAWN_CLAUDE", str(write_fake_claude(tmp_path / "bin")))
        monkeypatch.setattr(shutil, "which", lambda name, *a, **k: f"/usr/bin/{name}")
        monkeypatch.setattr(child_proc, "has_proc", lambda: True)
        monkeypatch.setattr(child_slot, "can_release_session", lambda *a, **k: True)
        monkeypatch.setattr(child_spawn, "claude_version", lambda env=None: FAKE_VERSION_DEFAULT)
        monkeypatch.setattr(child_spawn, "cmd_sweep", lambda *a, **k: {"stopped": [], "gone": []})
        monkeypatch.setattr(child_spawn, "cmd_smoke", self._smoke)

    def _smoke(self, *a, **k) -> dict:
        self.smokes += 1
        return {"ok": True, "why": "smoke passed", "claude_version": FAKE_VERSION_DEFAULT}

    def run(self, run_id: str) -> tuple[int, dict]:
        code = child_spawn.main(["probe", "--run", run_id, "--root", str(self.repo)])
        return code, json.loads(self.capsys.readouterr().out.strip().splitlines()[-1])

    def smoke_entry(self) -> dict:
        """The repo's `tp-children/smoke.json` — the pass this probe just cached."""
        path = self.repo / ".git" / child_state.CHILDREN_DIR / child_state.SMOKE_CACHE
        return json.loads(path.read_text(encoding="utf-8"))


def test_probe_records_dont_ask_in_its_cached_verdict(monkeypatch, tmp_path, capsys) -> None:
    """The CLI that has `dontAsk`: the verdict says so, and the pass is cached under `dontAsk`."""
    p = _Probe(monkeypatch, tmp_path, capsys)
    code, res = p.run("runa0001")
    assert (code, res["mode"], res["dont_ask"]) == (0, "child", True)
    rd = child_state.run_dir("runa0001", root=p.repo)
    assert child_state.probe_cache(rd)["dont_ask"] is True
    assert p.smoke_entry()["permission_mode"] == "dontAsk"


def test_probe_records_no_dont_ask_for_an_older_cli(monkeypatch, tmp_path, capsys) -> None:
    """The CLI without `dontAsk`: the verdict says False and the pass is cached under `auto`."""
    p = _Probe(monkeypatch, tmp_path, capsys)
    monkeypatch.setenv("FAKE_PERMISSION_MODES", OLD_CLI_MODES)
    code, res = p.run("runa0001")
    assert (code, res["mode"], res["dont_ask"]) == (0, "child", False)
    assert child_state.probe_cache(child_state.run_dir("runa0001", root=p.repo))["dont_ask"] is False
    assert p.smoke_entry()["permission_mode"] == "auto"


def test_probe_smoke_cache_is_keyed_by_the_mode(monkeypatch, tmp_path, capsys) -> None:
    """A pass earned under `auto` never answers a `dontAsk` probe — that probe smokes again."""
    p = _Probe(monkeypatch, tmp_path, capsys)
    monkeypatch.setenv("FAKE_PERMISSION_MODES", OLD_CLI_MODES)
    code, res = p.run("runa0001")
    assert (code, res["mode"], res["dont_ask"]) == (0, "child", False)
    assert p.smokes == 1
    monkeypatch.delenv("FAKE_PERMISSION_MODES")
    code, res = p.run("runb0002")  # same version, but the cached pass was earned under `auto`
    assert (code, res["mode"], res["dont_ask"]) == (0, "child", True)
    assert p.smokes == 2, "a mode change must not reuse another mode's smoke pass"
    code, res = p.run("runc0003")  # now a `dontAsk` pass is cached for this version
    assert p.smokes == 2


class _Start:
    """One `start` against the fake claude (happy mode), reaped no matter how the test ends."""

    def __init__(self, monkeypatch, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.repo = tmp_path / "repo"
        self.wt = tmp_path / "wt"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        commit(self.repo, {"README.md": "demo\n"}, "base")
        git(self.repo, "worktree", "add", "-q", "-b", "wt", str(self.wt))
        self.launches: list = []
        self.argv_out = tmp_path / "argv.json"

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", RUN)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.setenv("TP_CHILD_SPAWN_CLAUDE", str(write_fake_claude(tmp_path / "bin")))
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "happy")
        monkeypatch.setenv("FAKE_ARGV_OUT", str(self.argv_out))
        monkeypatch.setenv("TP_CHILD_RESOLVE_S", "20")

        real_launch = child_proc.launch

        def launch(argv, cwd, out_path, env):
            rec = real_launch(argv, cwd, out_path, env)
            self.launches.append({"argv": argv, "rec": rec})
            return rec

        monkeypatch.setattr(child_slot, "note_policy", lambda *a, **k: True)
        monkeypatch.setattr(child_slot, "release", lambda *a, **k: {"agent": "skipped"})
        monkeypatch.setattr(stopped_agents, "append", lambda *a, **k: "skipped")
        monkeypatch.setattr(child_proc, "launch", launch)

    def write_probe(self, verdict: dict) -> None:
        """Cache this run's probe verdict — the answer `start` reads instead of re-checking."""
        child_state.write_probe(child_state.run_dir(RUN, root=self.wt), verdict)

    def run(self, capsys) -> tuple[int, dict, str]:
        """`(exit code, reply, stderr)` for one `start` in this fixture's worktree."""
        prompt = self.tmp / "prompt.md"
        prompt.write_text(PROMPT, encoding="utf-8")
        try:
            code = child_spawn.main(["start", "--site", SITE, "--agent-ref", AGENT_REF,
                                     "--model", MODEL, "--prompt-file", str(prompt),
                                     "--cwd", str(self.wt), "--run", RUN])
            cap = capsys.readouterr()
            lines = [ln for ln in cap.out.splitlines() if ln.strip()]
            assert len(lines) == 1, lines
            return code, json.loads(lines[0]), cap.err
        finally:
            self.cleanup()

    def recorded(self) -> dict:
        """What the fake claude parsed out of the launch argv."""
        return json.loads(self.argv_out.read_text(encoding="utf-8"))

    def cleanup(self) -> None:
        """Signal only the group this test launched, then wait for it to be gone."""
        for rec in self.launches:
            info = rec["rec"]
            if "pid" not in info:
                continue
            pid, ticks = int(info["pid"]), int(info["start_ticks"] or 0)
            child_proc.stop_group(pid, int(info["pgid"]), ticks, grace_s=2)
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
            deadline = time.monotonic() + REAP_TIMEOUT_S
            while time.monotonic() < deadline and child_proc.alive(pid, ticks):
                time.sleep(0.05)


def test_start_launches_auto_when_the_probe_says_no_dont_ask(monkeypatch, tmp_path, capsys) -> None:
    """§A4: a cached `dont_ask: false` — same lists, `auto`, one `W:` line naming the cost."""
    sp = _Start(monkeypatch, tmp_path)
    sp.write_probe({"mode": "child", "why": "smoke passed", "dont_ask": False})
    code, res, err = sp.run(capsys)
    assert code == 0, res
    got = sp.recorded()
    assert got["permission_mode"] == "auto"
    assert got["disallowed"] == cp.DEFAULT_DENY
    assert "bypassPermissions" not in got["argv"]
    warns = [ln for ln in err.splitlines() if ln.startswith("W:")]
    assert len(warns) == 1, err
    assert warns[0].startswith("W: claude lacks dontAsk"), warns
    assert "1 classifier check per session" in warns[0], warns
    assert res["permission_mode"] == "auto"
    assert child_state.read(res["state_path"])["permission_mode"] == "auto"


def test_start_launches_dont_ask_when_the_probe_says_yes(monkeypatch, tmp_path, capsys) -> None:
    """The mode the probe proved: `dontAsk`, and no warning line at all."""
    sp = _Start(monkeypatch, tmp_path)
    sp.write_probe({"mode": "child", "why": "smoke passed", "dont_ask": True})
    code, res, err = sp.run(capsys)
    assert code == 0, res
    assert sp.recorded()["permission_mode"] == "dontAsk"
    assert [ln for ln in err.splitlines() if ln.startswith("W:")] == [], err
    assert res["permission_mode"] == "dontAsk"
    assert child_state.read(res["state_path"])["permission_mode"] == "dontAsk"


def test_start_rechecks_the_cli_with_no_cached_probe(monkeypatch, tmp_path, capsys) -> None:
    """No probe for this run: the CLI itself answers, and an old one falls back to `auto`."""
    sp = _Start(monkeypatch, tmp_path)
    monkeypatch.setenv("FAKE_PERMISSION_MODES", OLD_CLI_MODES)
    code, res, err = sp.run(capsys)
    assert code == 0, res
    assert sp.recorded()["permission_mode"] == "auto"
    assert res["permission_mode"] == "auto"
    assert len([ln for ln in err.splitlines() if ln.startswith("W:")]) == 1, err


def test_start_falls_back_when_the_cached_probe_has_no_answer(monkeypatch, tmp_path,
                                                              capsys) -> None:
    """A `probe.json` written before this change has no `dont_ask` key: the CLI decides."""
    sp = _Start(monkeypatch, tmp_path)
    sp.write_probe({"mode": "child", "why": "smoke passed"})
    code, res, err = sp.run(capsys)
    assert code == 0, res
    assert sp.recorded()["permission_mode"] == "dontAsk"
    assert res["permission_mode"] == "dontAsk"
