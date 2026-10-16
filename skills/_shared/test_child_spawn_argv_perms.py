"""Tests for the permission flags a child launch carries.

strata-classifier-cost-followups task 1.3: design §A1/§A2 — `host_argv` renders the
`child_permissions` flags for its `cwd` (the mode, the shipped allow list plus the
worktree-scoped `Edit` rule (task 2.5: the one `Edit(//…)` rule covers every file-editing
tool; a `Write(<path>)` allow rule is never honoured), the shipped deny list) and `cmd_start` hands it its
resolved `wd`, so a per-repo `strata_spawn.permissions` addition reaches the CLI and each
config warning is one `W:` line on stderr. §Constraints also pins the negative: no launch
argv ever carries `bypassPermissions`.

The argv checks build no subprocess. The end-to-end check runs `start` against
`child_spawn_fixture`'s fake claude (`FAKE_CLAUDE_MODE=happy`) with `FAKE_ARGV_OUT`, so the
assertions are on what the fake actually parsed — the same reading the fixture's own tests
use. Nothing here starts a live `claude`, router or GPU job, and the group the test launched
is the only one it signals.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_permissions as cp  # noqa: E402
import child_proc  # noqa: E402
import child_slot  # noqa: E402
import child_spawn  # noqa: E402
import stopped_agents  # noqa: E402
from attempt_fixture import commit, git  # noqa: E402
from child_spawn_fixture import write_fake_claude  # noqa: E402

AGENT_REF = "three-pillars:tp-runbook"
MODEL = "haiku"
SITE = "S1"
RUN = "perm0123"
PROMPT_PATH = "/w/.tp-scratch/child-spawn/ab12cd34.prompt.md"
PROMPT = "Run `git status --porcelain` and report the output.\n"
REAP_TIMEOUT_S = 15


def _values(argv: list[str], name: str) -> list[str]:
    """Every value after `name` up to the next `--flag` — the CLI's variadic form."""
    if name not in argv:
        return []
    got, i = [], argv.index(name) + 1
    while i < len(argv) and not argv[i].startswith("--"):
        got.append(argv[i])
        i += 1
    return got


def _wt_rule(path: Path, tool: str = "Edit") -> str:
    """§A1's worktree-scoped rule for `path`: `//` + the absolute path, minus its leading `/`.

    Task 2.5: `Edit` is the only tool a worktree allow rule is ever written with — an `Edit`
    path rule covers every file-editing tool, and a `Write(<path>)` rule is ignored."""
    return f"{tool}(//{path.resolve().as_posix().lstrip('/')}/**)"


def _write_config(cwd: Path, permissions: dict) -> None:
    """`cwd/.three-pillars/config.json` holding a `strata_spawn.permissions` section."""
    cfg = cwd / ".three-pillars"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.json").write_text(
        json.dumps({"strata_spawn": {"permissions": permissions}}), encoding="utf-8")


def test_mode_auto_keeps_the_same_lists():
    """§A4's fallback mode: `auto` after `--permission-mode`, the lists unchanged."""
    auto = child_spawn.host_argv(AGENT_REF, MODEL, PROMPT_PATH, "u", env={}, cwd="/w", mode="auto")
    dont = child_spawn.host_argv(AGENT_REF, MODEL, PROMPT_PATH, "u", env={}, cwd="/w")
    assert auto[auto.index("--permission-mode") + 1] == "auto"
    for flag in ("--allowedTools", "--disallowedTools"):
        assert _values(auto, flag) == _values(dont, flag)


def test_per_repo_allow_extra_reaches_the_argv(tmp_path):
    """§A2: `allow_extra` in the cwd's config adds the rule to `--allowedTools`."""
    _write_config(tmp_path, {"allow_extra": ["WebFetch"]})
    argv = child_spawn.host_argv(AGENT_REF, MODEL, PROMPT_PATH, "u", env={}, cwd=str(tmp_path))
    allowed = _values(argv, "--allowedTools")
    assert "WebFetch" in allowed
    assert allowed == cp.DEFAULT_ALLOW_TOOLS + [_wt_rule(tmp_path), "WebFetch"]
    assert not [r for r in allowed if r.startswith("Write(")]


def test_no_launch_argv_carries_bypass_permissions():
    """§Constraints: every mode a child may launch in is in `cp.MODES`; never a bypass."""
    for mode in cp.MODES:
        argv = child_spawn.host_argv(AGENT_REF, MODEL, PROMPT_PATH, "u", env={}, cwd="/w",
                                     mode=mode)
        assert argv[argv.index("--permission-mode") + 1] == mode
        assert "bypassPermissions" not in argv


class _Start:
    """One `start` against the fake claude (happy mode), reaped however the test ends."""

    def __init__(self, monkeypatch, tmp_path: Path):
        self.tmp = tmp_path
        self.repo = tmp_path / "repo"
        self.wt = tmp_path / "wt"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        commit(self.repo, {"README.md": "demo\n"}, "base")
        git(self.repo, "worktree", "add", "-q", "-b", "wt", str(self.wt))
        self.launches: list = []

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", RUN)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.setenv("TP_CHILD_SPAWN_CLAUDE", str(write_fake_claude(tmp_path / "bin")))
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "happy")
        monkeypatch.setenv("FAKE_ARGV_OUT", str(tmp_path / "argv.json"))
        monkeypatch.setenv("TP_CHILD_RESOLVE_S", "20")

        real_launch = child_proc.launch

        def launch(argv, cwd, out_path, env):
            rec = real_launch(argv, cwd, out_path, env)
            self.launches.append({"argv": argv, "cwd": cwd, "env": env, "rec": rec})
            return rec

        monkeypatch.setattr(child_slot, "note_policy", lambda *a, **k: True)
        monkeypatch.setattr(child_slot, "release", lambda *a, **k: {"agent": "skipped"})
        monkeypatch.setattr(stopped_agents, "append", lambda *a, **k: "skipped")
        monkeypatch.setattr(child_proc, "launch", launch)

    def prompt_file(self) -> Path:
        path = self.tmp / "prompt.md"
        path.write_text(PROMPT, encoding="utf-8")
        return path

    def run(self, capsys) -> tuple:
        """`(exit code, reply, stderr)` for one `start` in this fixture's worktree."""
        try:
            code = child_spawn.main(["start", "--site", SITE, "--agent-ref", AGENT_REF,
                                     "--model", MODEL, "--prompt-file", str(self.prompt_file()),
                                     "--cwd", str(self.wt), "--run", RUN])
            cap = capsys.readouterr()
            lines = [ln for ln in cap.out.splitlines() if ln.strip()]
            assert len(lines) == 1, lines
            return code, json.loads(lines[0]), cap.err
        finally:
            self.cleanup()

    def recorded(self) -> dict:
        """What the fake claude parsed out of the launch argv."""
        return json.loads(Path(os.environ["FAKE_ARGV_OUT"]).read_text(encoding="utf-8"))

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


def test_start_passes_the_flags_to_the_cli(monkeypatch, tmp_path, capsys) -> None:
    """The flags reach the fake CLI: `dontAsk`, and the worktree rule for the resolved `wd`."""
    sp = _Start(monkeypatch, tmp_path)
    code, res, _ = sp.run(capsys)
    assert code == 0, res
    got = sp.recorded()
    assert got["permission_mode"] == "dontAsk"
    assert _wt_rule(sp.wt) in got["allowed"]
    assert not [r for r in got["allowed"] if r.startswith("Write(")]
    assert got["disallowed"] == cp.DEFAULT_DENY
    assert "bypassPermissions" not in got["argv"]


def test_start_prints_config_warnings_on_stderr(monkeypatch, tmp_path, capsys) -> None:
    """§A2: an invalid config entry is skipped by `rules` and reported as one `W:` line."""
    sp = _Start(monkeypatch, tmp_path)
    _write_config(sp.wt, {"allow_extra": ["WebFetch", 42]})
    code, res, err = sp.run(capsys)
    assert code == 0, res
    warnings = [ln for ln in err.splitlines() if ln.startswith("W:")]
    assert len(warnings) == 1, err
    assert "skipped invalid rule" in warnings[0]
    assert "WebFetch" in sp.recorded()["allowed"]
