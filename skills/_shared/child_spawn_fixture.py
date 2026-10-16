#!/usr/bin/env python3
"""child_spawn_fixture.py — the fake `claude` the child-spawn CLI tests launch instead of a real one.

design: strata-session-isolation (task 4.1; detailed-design §Test Strategy, "child_spawn CLI
(integration, fake claude)"). Not a test module (no `test_` prefix, never collected): the shared
fixture beside `attempt_fixture.py` that tasks 4.2-4.7 point at with `TP_CHILD_SPAWN_CLAUDE`.

`write_fake_claude(dir)` writes an executable `python3` script (shebang `sys.executable`, 0o755)
and returns its path. The script parses `--session-id`, `-p` and the permission flags the way CLI
2.1.296 does — `--allowedTools`/`--disallowedTools` take variadic values up to the next `--flag`,
and an unknown `--permission-mode` exits 1 with the CLI-shaped error before any write — and ignores
every other flag, then writes the child's host transcript and (in every mode but `no-inner`) one
inner subagent transcript at exactly the paths `child_transcript` / `attempt_scan.locate` read:
`$CLAUDE_CONFIG_DIR/projects/-fake/<session>.jsonl` and
`.../<session>/subagents/agent-<inner_id>.jsonl`. It prints one `--output-format json`-shaped result
object on stdout and branches on `FAKE_CLAUDE_MODE`: happy | mismatch | no-inner | sleep | linger |
smoke | deny | refuse. `refuse` (strata-classifier-cost-followups 1.5) is `deny`'s host result for
`Bash` / `rm -rf build` plus an inner transcript whose `tool_result` carries the refusal prose and
whose ended turn's last text is the worker's JSON line `FAKE_WORKER_LINE_DEFAULT`. The host's `Agent` call takes its `subagent_type`/`model` from `FAKE_AGENT_REF` /
`FAKE_MODEL`, else parses them out of the instruction `child_spawn.host_instruction` renders, so a
later test needs no env at all. `--help` (like `--version`) needs no config dir and prints the
`--permission-mode` choices: `FAKE_PERMISSION_MODES` narrows them to simulate an older CLI without
`dontAsk`, and `FAKE_ARGV_OUT=<file>` records the parsed permission argv as JSON for the spawn
tests. Every sleep is a `time.sleep` in the script itself — no grandchild
process — so stopping its process group ends it, and nothing here starts a live `claude`, router or
GPU job. With `CLAUDE_CONFIG_DIR` unset or empty the script exits 2 instead of writing under the
real `~/.claude`. Stdlib only.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = ["FAKE_REPLY_DEFAULT", "FAKE_WORKER_LINE_DEFAULT", "FAKE_VERSION_DEFAULT", "FAKE_PROJECT",
           "FAKE_WRONG_REF", "fake_inner_id", "write_fake_claude"]

FAKE_REPLY_DEFAULT = "fake inner reply"
# `refuse` mode's inner turn ends on the JSON line a `tp-task-worker` replies with (task 1.5)
FAKE_WORKER_LINE_DEFAULT = '{"task_id": "1.5", "sha": "deadbeef", "claimed": "green"}'
FAKE_VERSION_DEFAULT = "9.9.9-fake"
FAKE_PROJECT = "-fake"
FAKE_WRONG_REF = "three-pillars:wrong-agent"


def fake_inner_id(session_id: str, env: dict | None = None) -> str:
    """The inner agent id the fake script uses for `session_id`.

    `FAKE_INNER_ID` when set (pass the child's own `env` — the script reads its environment, not
    this process's), else derived from the session id. Tests compare `child_transcript.inner_ids`
    against this, so the two spellings must stay one expression.
    """
    env = os.environ if env is None else env
    return env.get("FAKE_INNER_ID") or "fake" + str(session_id).replace("-", "")[:12]


def write_fake_claude(dir) -> Path:
    """Write the executable fake `claude` into `dir` as `claude`; return its path."""
    out = Path(dir) / "claude"
    out.parent.mkdir(parents=True, exist_ok=True)  # a caller may hand a dir it has not made yet
    out.write_text(_SCRIPT.replace("@PROJECT@", FAKE_PROJECT).replace("@WRONG_REF@", FAKE_WRONG_REF)
                   .replace("@VERSION@", FAKE_VERSION_DEFAULT).replace("@REPLY@", FAKE_REPLY_DEFAULT)
                   .replace("@WORKER@", FAKE_WORKER_LINE_DEFAULT).replace("@SHEBANG@", sys.executable),
                   encoding="utf-8")
    out.chmod(0o755)
    return out


_SCRIPT = r'''#!@SHEBANG@
"""Fake `claude` for the child-spawn CLI tests (strata-session-isolation task 4.1).

Written by `child_spawn_fixture.write_fake_claude` — edit that fixture, not a copy of this.
"""
import datetime
import json
import os
import re
import sys
import time
from pathlib import Path

PROJECT = "@PROJECT@"
WRONG_REF = "@WRONG_REF@"
VERSION = "@VERSION@"
REPLY = "@REPLY@"
WORKER = '@WORKER@'
REFUSED_TOOL = "Bash"
REFUSED_COMMAND = "rm -rf build"
REFUSED_TEXT = "Permission to use Bash with command rm -rf build has been denied."
SLEEP_MODES = ("no-inner", "sleep", "linger")
MODES_DEFAULT = "acceptEdits,auto,bypassPermissions,manual,dontAsk,plan"


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def flag(argv, name):
    """The value after `name`, or "" when the flag is absent (every unknown flag is ignored)."""
    return argv[argv.index(name) + 1] if name in argv else ""


def values(argv, name):
    """Every value after `name` up to the next item starting with `--` — the CLI's variadic form."""
    if name not in argv:
        return []
    got, i = [], argv.index(name) + 1
    while i < len(argv) and not argv[i].startswith("--"):
        got.append(argv[i])
        i += 1
    return got


def modes():
    """The `--permission-mode` choices: `FAKE_PERMISSION_MODES` (an older CLI) else the real set."""
    raw = (os.environ.get("FAKE_PERMISSION_MODES") or "").strip() or MODES_DEFAULT
    return [mode for mode in (part.strip() for part in raw.split(",")) if mode]


def print_help():
    """A `--help` shaped like the real CLI's, naming the modes this fake accepts."""
    print("Usage: claude [options] [prompt]\n\nOptions:\n"
          "  --permission-mode <mode>     Permission mode for the session "
          "(choices: %s)\n"
          "  --allowedTools <rules...>    Tools the session may call without asking\n"
          "  --disallowedTools <rules...>  Tools the session must never call"
          % ", ".join(modes()))
    return 0


def check_mode(argv):
    """0 when `--permission-mode` is absent or a known choice; else the CLI's error and exit 1."""
    mode = flag(argv, "--permission-mode")
    if not mode or mode in modes():
        return 0
    print("fake claude: error: argument '%s' is invalid. Allowed choices are %s."
          % (mode, ", ".join(modes())), file=sys.stderr)
    return 1


def record_argv(argv):
    """`FAKE_ARGV_OUT` holds the parsed permission argv as JSON — what actually reached the CLI."""
    path = (os.environ.get("FAKE_ARGV_OUT") or "").strip()
    if not path:
        return
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"permission_mode": flag(argv, "--permission-mode"),
                               "allowed": values(argv, "--allowedTools"),
                               "disallowed": values(argv, "--disallowedTools"),
                               "argv": list(argv)}), encoding="utf-8")


def ref_model(argv):
    """The Agent call's subagent_type/model: `FAKE_*` env, else parsed from the `-p` instruction."""
    got = re.search(r"subagent_type=([^,\s]+), model=([^,\s]+),", flag(argv, "-p"))
    return (os.environ.get("FAKE_AGENT_REF") or (got and got.group(1)) or "",
            os.environ.get("FAKE_MODEL") or (got and got.group(2)) or "")


def inner_id(session):
    return os.environ.get("FAKE_INNER_ID") or "fake" + session.replace("-", "")[:12]


def rec(kind, msg_id, content, stop_reason=None):
    return {"type": kind, "timestamp": now(), "requestId": msg_id,
            "message": {"id": msg_id, "role": kind, "model": "fake-model",
                        "stop_reason": stop_reason, "content": content}}


def host_records(ref, model, prompt):
    """One assistant record: exactly one `Agent` call — the shape `verify_host` proves."""
    call = {"type": "tool_use", "id": "tu_host", "name": "Agent",
            "input": {"subagent_type": ref, "model": model, "prompt": prompt}}
    return [rec("assistant", "host_1", [call], "end_turn")]


def inner_records(reply):
    """Ended turn (stop_reason end_turn, no tool_use) → `inner_done` true, `last_text` == reply."""
    return [rec("user", "inner_in", [{"type": "text", "text": "follow the prompt"}]),
            rec("assistant", "inner_1", [{"type": "text", "text": reply}], "end_turn")]


def inner_records_refused():
    """`refuse`: a refused `Bash` call answered by the refusal prose, then the worker's JSON line."""
    call = {"type": "tool_use", "id": "tu_inner", "name": REFUSED_TOOL,
            "input": {"command": REFUSED_COMMAND}}
    refused = {"type": "tool_result", "tool_use_id": "tu_inner", "is_error": True,
               "content": REFUSED_TEXT}
    return [rec("user", "inner_in", [{"type": "text", "text": "follow the prompt"}]),
            rec("assistant", "inner_1", [{"type": "text", "text": "trying"}, call], "tool_use"),
            rec("user", "inner_2", [refused]),
            rec("assistant", "inner_3", [{"type": "text", "text": WORKER}], "end_turn")]


def inner_records_open():
    """Turn still open: the last assistant record ends in a `tool_use`, no end_turn."""
    block = {"type": "tool_use", "id": "tu_inner", "name": "Bash",
             "input": {"command": "pytest -q"}}
    return [rec("user", "inner_in", [{"type": "text", "text": "follow the prompt"}]),
            rec("assistant", "inner_1", [{"type": "text", "text": "working"}, block], "tool_use")]


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def write_smoke():
    """`FAKE_SMOKE_FILE` holds `FAKE_SMOKE_TOKEN` then `exit=0` — the smoke contract's proof."""
    path = os.environ.get("FAKE_SMOKE_FILE", "").strip()
    if path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(os.environ.get("FAKE_SMOKE_TOKEN", "") + "\nexit=0\n", encoding="utf-8")


def result(session, mode):
    """One `--output-format json`-shaped result; `deny`/`refuse` report a refusal instead."""
    denied = mode in ("deny", "refuse")
    command = REFUSED_COMMAND if mode == "refuse" else "git status --porcelain"
    return {"type": "result", "subtype": "success", "is_error": denied,
            "result": os.environ.get("FAKE_REPLY") or REPLY, "session_id": session,
            "permission_denials": [{"tool_name": REFUSED_TOOL, "tool_use_id": "tu_inner",
                                    "tool_input": {"command": command}}]
            if denied else []}


def sleep_s(mode):
    """`FAKE_SLEEP_S`, defaulting to 30 for `sleep`/`linger` and 0 for `no-inner`."""
    raw = os.environ.get("FAKE_SLEEP_S", "")
    try:
        return float(raw)
    except ValueError:
        return 0.0 if mode == "no-inner" else 30.0


def main(argv):
    if "--version" in argv:  # task 4.6 reads this; needs no config dir
        print(os.environ.get("FAKE_CLAUDE_VERSION") or VERSION)
        return 0
    if "--help" in argv or "-h" in argv:  # task 1.4 probes this for `dontAsk`
        return print_help()
    if check_mode(argv):  # an unknown mode fails like the real CLI: before any write
        return 1
    cfg = (os.environ.get("CLAUDE_CONFIG_DIR") or "").strip()
    if not cfg:
        print("fake claude: CLAUDE_CONFIG_DIR must be set — never write the real ~/.claude",
              file=sys.stderr)
        return 2
    record_argv(argv)  # task 1.3 asserts what reached the CLI
    session = flag(argv, "--session-id")
    mode = os.environ.get("FAKE_CLAUDE_MODE", "happy")
    ref, model = ref_model(argv)
    base = Path(cfg) / "projects" / PROJECT
    called = WRONG_REF if mode == "mismatch" else ref
    write_jsonl(base / (session + ".jsonl"), host_records(called, model, flag(argv, "-p")))
    if mode != "no-inner":
        inner = base / session / "subagents" / ("agent-" + inner_id(session) + ".jsonl")
        reply = os.environ.get("FAKE_REPLY") or REPLY
        if mode == "sleep":
            rows = inner_records_open()
        elif mode == "refuse":
            rows = inner_records_refused()
        else:
            rows = inner_records(reply)
        write_jsonl(inner, rows)
    if mode == "smoke":
        write_smoke()
    print(json.dumps(result(session, mode)))
    sys.stdout.flush()
    if mode in SLEEP_MODES:
        time.sleep(sleep_s(mode))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''
