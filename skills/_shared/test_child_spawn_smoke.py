"""Tests for child_spawn.py — the `smoke` subcommand's one end-to-end proof.

strata-session-isolation task 4.6 (design §B8, detailed-design §CLI `smoke`): `smoke [--model M]`
spawns a real child through `cmd_start` + `cmd_wait` and answers
`{"ok", "why", "claude_version"}` (exit 0 / 3). `ok` needs all four answers: `start` resolved and
`verify_host`-verified the host, `wait` ended the child, the host's own stdout JSON shows no denial
(`is_error` / `permission_denials`), and the smoke file the child wrote holds the token and an
`exit=<code>` line — which is what proves the child's INNER tools worked. A failure names its layer:
`verify: …`, `wait: …`, `denied: …`, `inner tools: …`.

Nothing here starts a live `claude`, router or GPU job: the claude is Task 4.1's fake reached through
`TP_CHILD_SPAWN_CLAUDE` (its `--version` branch answers `claude_version`), `CLAUDE_CONFIG_DIR` is a
tmp dir, and `child_slot.note_policy` / `child_slot.release` / `stopped_agents.append` are
monkeypatched so no router state is touched. `child_spawn.new_token` is monkeypatched to a fixed
16-hex token, and `FAKE_SMOKE_TOKEN` / `FAKE_SMOKE_FILE` tell the fake exactly the file a real child
is told to write under `--cwd`. `--cwd` is a real tmp git repo's linked worktree, so the child state
lands under that repo's `.git/tp-children/`. Every launch is reaped in teardown, on a failing assert
too. Signal only the group the test launched.
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
import child_slot  # noqa: E402
import child_spawn  # noqa: E402
import stopped_agents  # noqa: E402
from attempt_fixture import commit, git  # noqa: E402
from child_spawn_fixture import FAKE_VERSION_DEFAULT, write_fake_claude  # noqa: E402

RUN = "smoke0123"
TOKEN = "ab12" * 4  # 16 hex chars, like `new_token`; built, so no scanner reads it as a key
REAP_TIMEOUT_S = 15


class _Smoke:
    """One `smoke` run against the fake claude, reaped no matter how the test ends."""

    def __init__(self, monkeypatch, tmp_path: Path, mode: str, tag: str = ""):
        self.tmp = tmp_path
        self.repo = tmp_path / ("repo" + tag)
        self.wt = tmp_path / ("wt" + tag)
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        commit(self.repo, {"README.md": "demo\n"}, "base")
        git(self.repo, "worktree", "add", "-q", "-b", "wt" + tag, str(self.wt))
        self.launches: list = []
        # Task 3.5: spelled out, not read from `PROMPT_SUBDIR`, so a drifting constant fails here.
        self.smoke_file = self.wt / ".tp-scratch" / "child-spawn" / f"smoke-{TOKEN}.txt"

        monkeypatch.setattr(child_spawn, "new_token", lambda: TOKEN)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", RUN)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.setenv("TP_CHILD_SPAWN_CLAUDE", str(write_fake_claude(tmp_path / "bin")))
        monkeypatch.setenv("TP_CHILD_MAX_S", "120")
        monkeypatch.setenv("TP_CHILD_RESOLVE_S", "20")
        monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
        monkeypatch.setenv("FAKE_SMOKE_TOKEN", TOKEN)
        monkeypatch.setenv("FAKE_SMOKE_FILE", str(self.smoke_file))

        real_launch = child_proc.launch

        def launch(argv, cwd, out_path, env):
            rec = real_launch(argv, cwd, out_path, env)
            self.launches.append(rec)
            return rec

        monkeypatch.setattr(child_slot, "note_policy", lambda *a, **k: True)
        monkeypatch.setattr(child_slot, "release", lambda *a, **k: {"agent": "skipped"})
        monkeypatch.setattr(stopped_agents, "append", lambda *a, **k: "skipped")
        monkeypatch.setattr(child_proc, "launch", launch)

    def run(self, capsys) -> tuple[int, dict]:
        """One `child_spawn.main(["smoke", …])`: `(exit code, the one JSON line it printed)`."""
        code = child_spawn.main(["smoke", "--cwd", str(self.wt), "--run", RUN])
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert len(lines) == 1, lines
        return code, json.loads(lines[0])

    def cleanup(self) -> None:
        """Signal only the group this test launched, then wait for it to be gone."""
        for info in self.launches:
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


def test_smoke_ok(monkeypatch, tmp_path, capsys) -> None:
    """The whole round-trip: exit 0, `ok`, the faked `claude --version`, and the file read once."""
    sp = _Smoke(monkeypatch, tmp_path, "smoke")
    try:
        code, res = sp.run(capsys)
        assert code == 0, res
        assert res["ok"] is True, res
        assert res["claude_version"] == FAKE_VERSION_DEFAULT, res
        assert not sp.smoke_file.exists(), "smoke must delete the file it read"
    finally:
        sp.cleanup()


def test_smoke_denied(monkeypatch, tmp_path, capsys) -> None:
    """The host's own result JSON refused: exit 3, `ok` false, the why names the denied tool.

    strata-classifier-cost-followups task 1.4: a smoke file that was already sitting at the
    path (dirt from an earlier attempt, or a child that wrote it before its host refused) is
    removed on this exit too — a refused smoke never leaves dirt the next `task_verify open`
    reads as `dirty-tree`.
    """
    sp = _Smoke(monkeypatch, tmp_path, "deny")
    sp.smoke_file.parent.mkdir(parents=True, exist_ok=True)
    sp.smoke_file.write_text("leftover\n", encoding="utf-8")
    try:
        code, res = sp.run(capsys)
        assert code == 3, res
        assert res["ok"] is False, res
        assert res["why"].startswith("denied"), res
        assert "Bash" in res["why"], res
        assert not sp.smoke_file.exists(), "a denied smoke left its smoke file behind"
    finally:
        sp.cleanup()


def test_smoke_wait_deadline_removes_the_smoke_file(monkeypatch, tmp_path, capsys) -> None:
    """`wait` fails `deadline`: the pre-created smoke file is gone on this exit as well."""
    sp = _Smoke(monkeypatch, tmp_path, "sleep")
    monkeypatch.setenv("FAKE_SLEEP_S", "3")
    monkeypatch.setenv("TP_CHILD_MAX_S", "2")  # `deadline_at` passes while the host is still up
    sp.smoke_file.parent.mkdir(parents=True, exist_ok=True)
    sp.smoke_file.write_text("leftover\n", encoding="utf-8")
    try:
        code, res = sp.run(capsys)
        assert code == 3, res
        assert res["ok"] is False, res
        assert res["why"].startswith("wait"), res
        assert "deadline" in res["why"], res
        assert not sp.smoke_file.exists(), "a `wait` failure left its smoke file behind"
    finally:
        sp.cleanup()


def test_smoke_verify_fails(monkeypatch, tmp_path, capsys) -> None:
    """A host that called the wrong agent: `start` fails, so the why names verify."""
    sp = _Smoke(monkeypatch, tmp_path, "mismatch")
    try:
        code, res = sp.run(capsys)
        assert code == 3, res
        assert res["ok"] is False, res
        assert "verify" in res["why"], res
    finally:
        sp.cleanup()


def test_smoke_no_file_or_no_exit_code(monkeypatch, tmp_path, capsys) -> None:
    """Inner tools: no smoke file at all, then a file with the token and no `exit=` line."""
    sp = _Smoke(monkeypatch, tmp_path, "happy")
    try:
        code, res = sp.run(capsys)
        assert code == 3, res
        assert res["ok"] is False, res
        assert res["why"].startswith("inner tools"), res
    finally:
        sp.cleanup()
    sp2 = _Smoke(monkeypatch, tmp_path, "happy", "2")
    sp2.smoke_file.parent.mkdir(parents=True, exist_ok=True)
    sp2.smoke_file.write_text(TOKEN + "\n", encoding="utf-8")
    try:
        code, res = sp2.run(capsys)
        assert code == 3, res
        assert res["ok"] is False, res
        assert res["why"].startswith("inner tools"), res
        assert "exit" in res["why"], res
    finally:
        sp2.cleanup()
