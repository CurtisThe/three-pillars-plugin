"""test_child_spawn_sandbox.py — the `strata_spawn.sandbox` switch and its S1 wiring.

design: strata-classifier-cost-followups (Task 2.2, §B1 switch + §B2 proof gate)

The switch reads `"off"` unless the repo's config says otherwise, and
`TP_CHILD_SANDBOX=on|off` overrides it for one run — that env lever is what lets
the live proof flip a repo on without editing its config. When the switch is on,
`prepare` merges the sandbox block into the site's worktree **before** the launch,
and only for site `S1`, the task worker whose `--cwd` is an attempt worktree; the
other sites run in folders a sandbox grant would be meaningless in. Where bwrap or
socat is missing (or the platform is Windows) the child still runs, unsandboxed,
with one `W:` line naming the deny list as the only fence.

Unit half: explicit config/env dicts and an injected `which`/platform — never the
session's environment. Wiring half: the same real-repo idiom as
`test_child_spawn_start.py` — a tmp repo's linked worktree, the fake claude from
`child_spawn_fixture` through `TP_CHILD_SPAWN_CLAUDE`, `CLAUDE_CONFIG_DIR` under
`tmp_path`, and `core.excludesFile` pinned to the null device because this
machine's global git ignore lists the settings path. Nothing here starts a live
`claude`, router or GPU job.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_proc  # noqa: E402
import child_sandbox  # noqa: E402
import child_spawn  # noqa: E402
import child_state  # noqa: E402
from attempt_fixture import commit, git  # noqa: E402
from child_spawn_fixture import write_fake_claude  # noqa: E402

AGENT_REF = "three-pillars:tp-task-worker"
MODEL = "haiku"
SITE = "S1"
RUN = "sbx01234"
MAX_S = 600
PROMPT = "Run `git status --porcelain` and report the output.\n"
SETTINGS = ".claude/settings.local.json"
REAP_TIMEOUT_S = 15


def _wt(tmp_path: Path, name: str = "att") -> Path:
    """A linked worktree of a one-commit tmp repo, with `core.excludesFile` pinned."""
    repo = tmp_path / "repo"
    if not repo.exists():
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        commit(repo, {"README.md": "demo\n"}, "base")
        git(repo, "config", "core.excludesFile", os.devnull)
    wt = tmp_path / "repo-wt" / name
    git(repo, "worktree", "add", "-q", "-b", f"tp-attempt/demo/{name}", str(wt))
    return wt


def _read(wt: Path) -> dict:
    return json.loads((wt / SETTINGS).read_text(encoding="utf-8"))


# --- the switch ---------------------------------------------------------------

def test_switch_reads_off_by_default() -> None:
    assert child_sandbox.switch({}, env={}) == "off"
    assert child_sandbox.switch({"strata_spawn": {}}, env={}) == "off"
    assert child_sandbox.switch({"strata_spawn": {"sandbox": "off"}}, env={}) == "off"
    assert child_sandbox.switch({"strata_spawn": {"sandbox": "on"}}, env={}) == "on"
    assert child_sandbox.switch({"strata_spawn": {"sandbox": "bogus"}}, env={}) == "off"
    assert child_sandbox.switch({"strata_spawn": "nope"}, env={}) == "off"


def test_switch_warns_once_for_an_unknown_value() -> None:
    assert child_sandbox.switch_warnings({}, env={}) == []
    assert child_sandbox.switch_warnings({"strata_spawn": {"sandbox": "on"}}, env={}) == []
    warns = child_sandbox.switch_warnings({"strata_spawn": {"sandbox": "bogus"}}, env={})
    assert len(warns) == 1
    assert warns[0].startswith("W: ")
    assert "bogus" in warns[0]


def test_env_lever_beats_the_config_for_one_run() -> None:
    # §B2: the live-proof lever — the env value wins over whatever the repo says.
    assert child_sandbox.switch({"strata_spawn": {"sandbox": "off"}},
                                env={"TP_CHILD_SANDBOX": "on"}) == "on"
    assert child_sandbox.switch({"strata_spawn": {"sandbox": "on"}},
                                env={"TP_CHILD_SANDBOX": "off"}) == "off"
    # An unusable env value is ignored, so the config still answers.
    assert child_sandbox.switch({"strata_spawn": {"sandbox": "on"}},
                                env={"TP_CHILD_SANDBOX": "maybe"}) == "on"


# --- the availability check ---------------------------------------------------

def test_available_names_the_first_thing_that_is_missing() -> None:
    both = lambda name: "/usr/bin/" + name  # noqa: E731 — injected lookup, both tools present
    none = lambda name: None  # noqa: E731
    assert child_sandbox.available(which=both, platform="linux") == (True, "")
    assert child_sandbox.available(which=none, platform="linux") == (False, "no bwrap")
    assert child_sandbox.available(which=lambda n: "/usr/bin/bwrap" if n == "bwrap" else None,
                                   platform="linux") == (False, "no socat")
    assert child_sandbox.available(which=both, platform="win32") == (False, "windows")


# --- prepare: the switch, the site, the availability --------------------------

def test_prepare_off_writes_nothing_and_warns_nothing(tmp_path) -> None:
    wt = _wt(tmp_path, "off")
    state, warns = child_sandbox.prepare(wt, "S1", {}, {"TP_CHILD_SANDBOX": "off"})
    assert state == "off"
    assert warns == []
    assert not (wt / SETTINGS).exists()


def test_prepare_on_s1_available_merges_the_block(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(child_sandbox, "available", lambda *a, **k: (True, ""))
    wt = _wt(tmp_path, "on")
    tmpdir = tmp_path / "t"
    tmpdir.mkdir()
    env = {"TP_CHILD_SANDBOX": "on", "TMPDIR": str(tmpdir)}

    state, warns = child_sandbox.prepare(wt, "S1", {"strata_spawn": {"sandbox": "off"}}, env)

    assert state == "sandboxed"
    assert warns == []
    fs = _read(wt)["sandbox"]["filesystem"]
    assert fs["allowWrite"][0] == str(Path(git(wt, "rev-parse", "--git-common-dir")).resolve())
    assert str(tmpdir) in fs["allowWrite"]


def test_prepare_on_s1_unavailable_warns_once_and_writes_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(child_sandbox, "available", lambda *a, **k: (False, "no bwrap"))
    wt = _wt(tmp_path, "unavail")
    state, warns = child_sandbox.prepare(wt, "S1", {"strata_spawn": {"sandbox": "on"}}, {})
    assert state == "unavailable"
    assert warns == ["W: sandbox unavailable (no bwrap); the deny list is the only fence"]
    assert not (wt / SETTINGS).exists()


def test_prepare_skips_sites_whose_cwd_is_not_an_attempt_worktree(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(child_sandbox, "available", lambda *a, **k: (True, ""))
    # tp-allow-fragile: the closed site set design.md §B1 names (S1 is the only sandboxed site).
    for site in ("S3", "smoke"):
        wt = _wt(tmp_path, "skip" + site)
        state, warns = child_sandbox.prepare(wt, site, {"strata_spawn": {"sandbox": "on"}}, {})
        assert state == "skipped"
        assert warns == []
        assert not (wt / SETTINGS).exists()


def test_prepare_reports_a_merge_failure_without_crashing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(child_sandbox, "available", lambda *a, **k: (True, ""))
    wt = _wt(tmp_path, "broken")
    (wt / ".claude").mkdir(parents=True)
    (wt / SETTINGS).write_text("{not json", encoding="utf-8")

    state, warns = child_sandbox.prepare(wt, "S1", {"strata_spawn": {"sandbox": "on"}}, {})

    assert state == "failed"
    assert len(warns) == 1 and warns[0].startswith("W: sandbox merge")
    assert (wt / SETTINGS).read_text(encoding="utf-8") == "{not json"


# --- the cmd_start wiring -----------------------------------------------------

class _Spawn:
    """One `start` against the fake claude, reaped no matter how the test ends."""

    def __init__(self, monkeypatch, tmp_path: Path):
        self.tmp = tmp_path
        self.repo = tmp_path / "repo"
        self.wt = tmp_path / "wt"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        commit(self.repo, {"README.md": "demo\n"}, "base")
        git(self.repo, "config", "core.excludesFile", os.devnull)
        git(self.repo, "worktree", "add", "-q", "-b", "tp-attempt/demo/sbx", str(self.wt))
        self.launches: list = []

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", RUN)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.setenv("TP_CHILD_SPAWN_CLAUDE", str(write_fake_claude(tmp_path / "bin")))
        monkeypatch.setenv("TP_CHILD_MAX_S", str(MAX_S))
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "linger")
        monkeypatch.setenv("FAKE_SLEEP_S", "30")
        monkeypatch.setenv("TP_CHILD_RESOLVE_S", "20")
        monkeypatch.delenv("TP_CHILD_SANDBOX", raising=False)

        real_launch = child_proc.launch

        def launch(argv, cwd, out_path, env):
            rec = real_launch(argv, cwd, out_path, env)
            self.launches.append({"argv": argv, "cwd": cwd, "out_path": out_path,
                                  "env": env, "rec": rec})
            return rec

        monkeypatch.setattr(child_proc, "launch", launch)

    def prompt_file(self) -> Path:
        path = self.tmp / "prompt.md"
        path.write_text(PROMPT, encoding="utf-8")
        return path

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


def _start(monkeypatch, tmp_path, capsys, sandbox: str | None,
           available=(True, "")) -> tuple:
    """Run `start` once for one switch state; `(code, reply, stderr, fixture)`."""
    sp = _Spawn(monkeypatch, tmp_path)
    if sandbox is None:
        monkeypatch.delenv("TP_CHILD_SANDBOX", raising=False)
    else:
        monkeypatch.setenv("TP_CHILD_SANDBOX", sandbox)
    monkeypatch.setattr(child_sandbox, "available", lambda *a, **k: available)
    try:
        code = child_spawn.main(["start", "--site", SITE, "--agent-ref", AGENT_REF,
                                 "--model", MODEL, "--prompt-file", str(sp.prompt_file()),
                                 "--cwd", str(sp.wt), "--run", RUN])
        cap = capsys.readouterr()
        lines = [ln for ln in cap.out.splitlines() if ln.strip()]
        assert len(lines) == 1, lines
        return code, json.loads(lines[0]), cap.err, sp
    finally:
        sp.cleanup()


def test_start_on_merges_the_settings_before_the_launch(monkeypatch, tmp_path, capsys) -> None:
    code, res, err, sp = _start(monkeypatch, tmp_path, capsys, "on")
    assert code == 0, res
    assert res["state"] == "running"
    assert sp.launches, "the child never launched"
    settings = sp.wt / SETTINGS
    assert settings.exists()
    # The grant was in the file the launch read: the block's own shape is there.
    assert _read(sp.wt)["sandbox"]["enabled"] is True
    assert SETTINGS not in git(sp.wt, "status", "--porcelain", "-uall").split()
    state = child_state.read(res["state_path"])
    assert state["sandbox"] == "on"
    assert state["sandbox_state"] == "sandboxed"
    assert "sandbox" not in err


def test_start_off_writes_nothing_and_records_off(monkeypatch, tmp_path, capsys) -> None:
    code, res, err, sp = _start(monkeypatch, tmp_path, capsys, None)
    assert code == 0, res
    assert sp.launches
    assert not (sp.wt / SETTINGS).exists()
    state = child_state.read(res["state_path"])
    assert state["sandbox"] == "off"
    assert state["sandbox_state"] == "off"
    assert "sandbox" not in err


def test_start_unavailable_runs_unsandboxed_with_one_warning(monkeypatch, tmp_path,
                                                             capsys) -> None:
    code, res, err, sp = _start(monkeypatch, tmp_path, capsys, "on",
                                available=(False, "no bwrap"))
    assert code == 0, res
    assert sp.launches
    assert not (sp.wt / SETTINGS).exists()
    warns = [ln for ln in err.splitlines() if "sandbox" in ln]
    assert warns == ["W: sandbox unavailable (no bwrap); the deny list is the only fence"]
    assert child_state.read(res["state_path"])["sandbox_state"] == "unavailable"
