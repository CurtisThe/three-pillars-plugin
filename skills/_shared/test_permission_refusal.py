"""Tests for permission_refusal.py — where a refused call is read, and what it becomes.

design: strata-classifier-cost-followups 1.5 (design §A3). A refusal is read FIRST from the host
result's structured `permission_denials` (the `--output-format json` object `_smoke_waited` parses
out of the child's `out_path`), and only as a fallback from the prose
`Permission to use … has been denied` in free text or in transcript `tool_result` blocks (the exact
`dontAsk` wording is unverified). Each refusal becomes the rule text an operator would add to the
allow list — `Bash(rm -rf build)`, or a bare tool name where there is no command. `lines` /
`parse_lines` are the reply-file round trip: `cmd_wait` prepends them to the ladder's reply file `F`
(the file §2 step 6 hands `tier_ladder.py next --reply-json F`), the worker's JSON line stays last,
and Task 1.6 reads the banner back with `parse_lines`.

Nothing here starts a live `claude`, router or GPU job: the claude is Task 4.1's fake reached through
`TP_CHILD_SPAWN_CLAUDE`, `CLAUDE_CONFIG_DIR` is a tmp dir, and the slot/stop calls are monkeypatched
so no router state is touched. `--cwd` is a real tmp git repo's linked worktree. The fixture reaps the
process group it launched in teardown, on a failing assert too. Signal only the group the test started.
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
import child_state  # noqa: E402
import stopped_agents  # noqa: E402
from attempt_fixture import commit, git  # noqa: E402
from child_spawn_fixture import (  # noqa: E402
    FAKE_REPLY_DEFAULT, FAKE_WORKER_LINE_DEFAULT, write_fake_claude)
from permission_refusal import (  # noqa: E402
    extract, from_records, from_result, lines, parse_lines)

AGENT_REF = "three-pillars:tp-runbook"
MODEL = "haiku"
SITE = "S1"
RUN = "prf01234"
MAX_S = 600
PROMPT = "Report the output of `git status --porcelain`.\n"
REAP_TIMEOUT_S = 15
REFUSED_RULE = "Bash(rm -rf build)"
REFUSED_TEXT = "Permission to use Bash with command rm -rf build has been denied."
BANNER = "permission-refused: "


def _tool_result(content) -> dict:
    """One transcript record: a `tool_result` block answering `tu_inner` with `content`."""
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "tu_inner", "is_error": True,
         "content": content}]}}


def test_from_result_reads_structured_denials() -> None:
    """The host result's `permission_denials` is the first reading: tool name + command."""
    assert from_result({"permission_denials": [{"tool_name": "Bash", "tool_use_id": "tu_inner",
                                                "tool_input": {"command": "rm -rf build"}}]}) \
        == [REFUSED_RULE]
    # a tool with no command is the bare tool name — the rule an operator would add
    assert from_result({"permission_denials": [{"tool_name": "WebFetch",
                                                "tool_input": {"url": "https://x"}}]}) == ["WebFetch"]
    assert from_result({"permission_denials": []}) == []
    assert from_result({}) == []
    assert from_result("not a dict") == []
    assert from_result(None) == []


def test_extract_finds_the_prose_refusal() -> None:
    """The prose fallback: the same rule text out of free text, deduped, silent on nothing."""
    assert extract(REFUSED_TEXT) == [REFUSED_RULE]
    assert extract("Permission to use WebFetch has been denied") == ["WebFetch"]
    assert extract(REFUSED_TEXT + "\nthen it gave up\n" + REFUSED_TEXT) == [REFUSED_RULE]
    assert extract("the task is done\n" + json.dumps({"task_id": "1.5", "claimed": "green"})) == []


def test_from_records_reads_tool_result_blocks() -> None:
    """A transcript's `tool_result` content (string or text blocks) is read; others ignored."""
    assert from_records([_tool_result(REFUSED_TEXT)]) == [REFUSED_RULE]
    assert from_records([_tool_result([{"type": "text", "text": REFUSED_TEXT}])]) == [REFUSED_RULE]
    assert from_records([_tool_result("42 files changed")]) == []
    assert from_records([]) == []
    assert from_records("not a list") == []


def test_lines_and_parse_lines_round_trip() -> None:
    """`lines` is the reply-file form; `parse_lines` reads the leading banner back."""
    assert lines([REFUSED_RULE]) == [BANNER + REFUSED_RULE]
    assert lines([]) == []
    reply = "\n".join([BANNER + REFUSED_RULE,
                       json.dumps({"task_id": "1.5", "sha": "abc", "claimed": "green"})])
    assert parse_lines(reply) == [REFUSED_RULE]
    assert parse_lines("\n".join(lines(parse_lines(reply)) + reply.splitlines()[1:])) \
        == [REFUSED_RULE]
    assert parse_lines(json.dumps({"task_id": "1.5", "claimed": "green"})) == []
    assert parse_lines("") == []
    # only the LEADING block is the worker's banner: the same text mid-reply is not a refusal
    assert parse_lines("\n".join([json.dumps({"x": 1}), BANNER + REFUSED_RULE])) == []


class _Spawn:
    """One `start` against the fake claude, reaped no matter how the test ends."""

    def __init__(self, monkeypatch, tmp_path: Path, mode: str):
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
        monkeypatch.setenv("TP_CHILD_MAX_S", str(MAX_S))
        monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
        monkeypatch.setenv("FAKE_SLEEP_S", "0")
        monkeypatch.setenv("TP_CHILD_RESOLVE_S", "20")

        real_launch = child_proc.launch

        def launch(argv, cwd, out_path, env):
            rec = real_launch(argv, cwd, out_path, env)
            self.launches.append(rec)
            return rec

        monkeypatch.setattr(child_slot, "note_policy", lambda *a, **k: True)
        monkeypatch.setattr(child_slot, "release", lambda *a, **k: {"agent": "skipped"})
        monkeypatch.setattr(stopped_agents, "append", lambda *a, **k: "skipped")
        monkeypatch.setattr(child_proc, "launch", launch)

    def prompt_file(self) -> Path:
        path = self.tmp / "prompt.md"
        path.write_text(PROMPT, encoding="utf-8")
        return path

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


def _start_and_wait(sp: _Spawn, capsys, reply: Path, unreadable: bool = False) -> str:
    """Spawn one child, `cmd_wait` it out with a reply file; return that file's text."""
    code = child_spawn.main(["start", "--site", SITE, "--agent-ref", AGENT_REF, "--model", MODEL,
                             "--prompt-file", str(sp.prompt_file()), "--cwd", str(sp.wt),
                             "--run", RUN])
    started_out = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert code == 0 and len(started_out) == 1, started_out
    started = json.loads(started_out[0])
    if unreadable:  # the prose fallback: a host result nobody can read
        Path(child_state.read(started["state_path"])["out_path"]).unlink()
    assert child_spawn.cmd_wait(started["state_path"], budget_s=20,
                                reply_out=str(reply))["state"] == "done"
    return reply.read_text(encoding="utf-8")


def test_refuse_mode_banner_above_the_worker_line(monkeypatch, tmp_path, capsys) -> None:
    """`refuse`: the reply file's first line is the banner, its last the worker's own reply."""
    sp = _Spawn(monkeypatch, tmp_path, "refuse")
    try:
        reply = tmp_path / "out" / "reply.txt"
        text = _start_and_wait(sp, capsys, reply)
        assert text.splitlines()[0] == BANNER + REFUSED_RULE, text
        assert text.splitlines()[-1] == FAKE_WORKER_LINE_DEFAULT, text
        assert parse_lines(text) == [REFUSED_RULE]
    finally:
        sp.cleanup()


def test_refuse_mode_prose_fallback_same_file(monkeypatch, tmp_path, capsys) -> None:
    """With the host result unreadable, the inner transcript's prose gives the same reply file."""
    sp = _Spawn(monkeypatch, tmp_path, "refuse")
    try:
        reply = tmp_path / "out" / "reply.txt"
        text = _start_and_wait(sp, capsys, reply, unreadable=True)
        assert text.splitlines()[0] == BANNER + REFUSED_RULE, text
        assert text.splitlines()[-1] == FAKE_WORKER_LINE_DEFAULT, text
        assert parse_lines(text) == [REFUSED_RULE]
    finally:
        sp.cleanup()


def test_happy_mode_adds_no_banner(monkeypatch, tmp_path, capsys) -> None:
    """A child with no refusal: the reply file is exactly the inner reply, as it was before."""
    sp = _Spawn(monkeypatch, tmp_path, "happy")
    try:
        reply = tmp_path / "out" / "reply.txt"
        text = _start_and_wait(sp, capsys, reply)
        assert text == FAKE_REPLY_DEFAULT, text
        assert parse_lines(text) == []
    finally:
        sp.cleanup()


def test_dispatch_doc_hands_wait_the_reply_file() -> None:
    """§3 step 4's child-spawn `wait` names `--reply-out <F>`, so the banner lands in `F`."""
    doc = (HERE / "local-dispatch.md").read_text(encoding="utf-8")
    step4 = doc[doc.index("4. **Wait by polling**"):doc.index("5. On `runaway`")]
    assert "child_spawn.py wait --state <state_path> --reply-out <F>" in step4
