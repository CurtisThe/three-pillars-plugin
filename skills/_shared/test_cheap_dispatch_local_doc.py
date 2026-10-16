"""Doc guard: `cheap-dispatch.md` §Routing, §Local rung, step 4 and §`ab` mode.

design: cheap-tier-local-routing (Task 6.1; detailed-design.md §Data Flow 1-3, §Interfaces
`dispatch_log.py record`, §Notes 2 and 6). Every routed site executes this prose literally, so
the guard pins its literals with each record-line assert scoped to that one line, checks every
command's flags against the script's own `--help` (no flag a CLI refuses), and renders each
record line and runs it through `dispatch_log.main`, asserting on the row a site would write.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import shlex
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import attempt_watchdog  # noqa: E402
import cheap_route  # noqa: E402
import cheap_tier_cli  # noqa: E402
import dispatch_log  # noqa: E402
import local_lease  # noqa: E402

DOC = HERE / "cheap-dispatch.md"
RECORD = "dispatch_log.py record"
COUNTS = ("--local-requests", "--fallback-requests", "--wall-s")
STARTED, ENDED = "--started-at <W.started_at>", "--ended-at <E>"
END_STAMP = "date -u +%Y-%m-%dT%H:%M:%SZ"
AGENT_ID = "--agent-id <agent id>"
PROBE_FLAGS = ("--requested-rung <spec.requested_rung>", "--lease-wait-s <spec.lease_wait_s>")
FLAG_RE = re.compile(r"(?<![\w-])--[a-z][a-z-]*")
OPTIONAL_RE = re.compile(r"\[[^\]]*\]")
PLACEHOLDER_RE = re.compile(r"<([^<>]+)>")
CLIS = {"dispatch_log.py": dispatch_log.main, "attempt_watchdog.py": attempt_watchdog.main,
        "cheap_tier_cli.py": cheap_tier_cli.main, "local_lease.py": local_lease.main}
SCRIPT_RE = re.compile(r"(" + "|".join(re.escape(s) for s in CLIS) + r")(?:\s+([a-z][a-z-]*))?")


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Whitespace collapsed, backticks dropped: a phrase check ignores markdown code spans."""
    return " ".join(text.replace("`", "").split())


def _sections(text: str) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    name = None
    for line in text.splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            out[name] = []
        elif name is not None:
            out[name].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def _step(loop: str, n: int) -> str:
    m = re.search(rf"^{n}\. \*\*.*?(?=^{n + 1}\. \*\*|\Z)", loop, re.S | re.M)
    assert m, f"§The loop has no step {n}"
    return m.group(0)


def _one(lines, pred, what: str) -> str:
    hits = [line for line in lines if pred(line)]
    assert len(hits) == 1, f"{what}: {len(hits)} lines {hits}"
    return hits[0]


def _record(text: str, marker: str) -> str:
    """The one `dispatch_log.py record` line carrying `marker`."""
    return _one(text.splitlines(), lambda l: RECORD in l and marker in l, marker)


def _success(local: str) -> str:
    """§Local rung's `done` line: the record line with the counts and no `--fallback`."""
    return _one(local.splitlines(),
                lambda l: RECORD in l and "--local-requests" in l and "--fallback " not in l,
                "success record line")


def _required(line: str) -> str:
    """`line` without its `[...]` optional spans."""
    return OPTIONAL_RE.sub("", line)


def _local() -> str:
    sections = _sections(_text())
    assert "Local rung" in sections, "no ## Local rung section"
    return sections["Local rung"]


def test_routing_replaces_unrouted():
    text = _text()
    assert "**Unrouted.**" not in text
    routing = _one(text.splitlines(), lambda l: l.startswith("- **Routing.**"), "§Routing")
    flat = _flat(routing)
    assert "The task lever is unrouted too" in flat  # test_cheap_tier_lever_sites.py pins it
    for slot in sorted(cheap_route.ROUTED_SLOTS):
        assert slot in flat, slot
    assert "--probe" in flat and "§Local rung" in flat


def test_spec_probe_line_and_optional_design():
    text = _text()
    probe = _one(text.splitlines(), lambda l: "cheap_tier_cli.py spec" in l and "--probe" in l,
                 "spec --probe line")
    for needle in ('"$TP_ROOT"/skills/_shared/cheap_tier_cli.py spec --slot <slot> --root . '
                   "--cheap-tier <mode> --probe --design <design>", "timeout 300000"):
        assert needle in probe, needle
    step1 = _flat(_step(_sections(text)["The loop"], 1))
    assert "--design is optional" in step1
    assert "non-owner" in step1


def test_step4_routed_record_flags():
    step4 = _step(_sections(_text())["The loop"], 4)
    flat = _flat(step4)
    for needle in (*PROBE_FLAGS, "--fallback <spec.fallback>", "--measure <spec.measure>",
                   "omit --measure when off", "--probe sites only", "live only here",
                   "Record the attempt per the dispatch doc"):
        assert needle in flat, needle
    mirror = _record(step4, "--fallback <spec.fallback>")
    required = _required(mirror)
    for flag in (*PROBE_FLAGS, AGENT_ID, "--rung <spec.rung>"):
        assert flag in required, flag
    assert "--fallback" not in required and "--measure" not in required  # both conditional
    assert not any(c in mirror for c in COUNTS)
    assert "[--ab-pair <id> --agent-id <id>]" in step4  # today's line, kept for non-probe sites


def test_local_rung_spawn_arm_and_poll():
    local = _local()
    flat = _flat(local)
    for needle in ("run_in_background=True", ".tp-scratch/cheap-watch/", "orphan-mark",
                   "local_lease.py release", "TaskStop", "local-dispatch.md §3"):
        assert needle in flat, needle
    arm = _one(local.splitlines(), lambda l: "attempt_watchdog.py arm" in l, "arm line")
    tail = arm[arm.index("attempt_watchdog.py arm"):].split("`")[0]
    got = dict(re.findall(r"(--[a-z-]+) (<[^>]+>|\S+)", tail))
    assert got.keys() == {"--state", "--attempt", "--rung", "--agent-id", "--phase"}, got
    assert (got["--state"], got["--rung"], got["--agent-id"], got["--phase"]) == (
        "<W>", "<spec.rung>", "<agent id>", "cheap")
    poll = _one(local.splitlines(), lambda l: "attempt_watchdog.py poll" in l, "poll line")
    assert "timeout 300000" in poll
    assert re.search(r"while it prints state `?running`?", poll), "no re-poll loop"


def test_end_stamp_and_start_time():
    local = _local()
    stamp = _one(local.splitlines(), lambda l: END_STAMP in l, "end-stamp line")
    assert "<E>" in stamp and "running" in stamp and "poll" in stamp
    assert "started_at" in _flat(local)


@pytest.mark.parametrize("marker", ["--fallback runaway", "--fallback watchdog-error"])
def test_stop_branch_order(marker):
    """§Notes 6: the watchdog-error branch runs the runaway branch's stop step before release."""
    item = _one(_local().splitlines(),
                lambda l: re.match(r"\d+\. ", l) and marker in l and RECORD not in l, marker)
    for step in ("TaskStop", "orphan-mark"):
        assert step in item and item.index(step) < item.index("release"), (step, item)


def test_record_lines_per_branch():
    local = _local()
    success, runaway = _success(local), _record(local, "--fallback runaway")
    watchdog = _record(local, "--fallback watchdog-error")
    spawn = _record(local, "--fallback background-spawn-failed")
    for line in (success, runaway):
        required = _required(line)
        for flag in (*COUNTS, STARTED, ENDED, AGENT_ID, *PROBE_FLAGS):
            assert flag in required, (flag, line)
    for line in (watchdog, spawn):  # no poll served/elapsed_s: none of the counts
        assert not any(c in line for c in COUNTS), line
        for flag in PROBE_FLAGS:
            assert flag in _required(line), (flag, line)
    assert AGENT_ID in _required(watchdog)
    for line in (success, runaway, watchdog, spawn):
        assert "$(" not in line and "${" not in line  # §Rules: literal commands


def test_ab_mode_runs_local_rung():
    assert "runs §Local rung" in _flat(_sections(_text())["`ab` mode"])


def _help_flags(script: str, sub: str | None) -> set[str]:
    argv = [sub, "--help"] if sub and script != "local_lease.py" else ["--help"]
    out = io.StringIO()
    with contextlib.redirect_stdout(out), pytest.raises(SystemExit):
        CLIS[script](argv)
    return set(FLAG_RE.findall(out.getvalue()))


def _commands(text: str) -> list[str]:
    """Every code span and fenced line that names one of `CLIS`."""
    spans = re.findall(r"`([^`\n]+)`", text)
    fenced = [l for block in re.findall(r"```\w*\n(.*?)```", text, re.S)
              for l in block.splitlines()]
    return [c for c in spans + fenced if SCRIPT_RE.search(c)]


def test_every_flag_is_one_the_cli_accepts():
    seen = set()
    for cmd in _commands(_text()):
        hits = list(SCRIPT_RE.finditer(cmd))
        for i, m in enumerate(hits):
            end = hits[i + 1].start() if i + 1 < len(hits) else len(cmd)
            flags = set(FLAG_RE.findall(cmd[m.end():end]))
            unknown = flags - _help_flags(m.group(1), m.group(2))
            assert not unknown, (m.group(0), unknown, cmd)
            seen.add(m.group(1))
    assert seen == set(CLIS), seen


BASE = {"d": "", "slot": "handoff", "spec.agent": "tp-drafter", "action": "accept",
        "spec.rung": "local-medium", "pass|fail": "pass", "true|false": "false",
        "agent id": "agent-abcdef1234", "spec.requested_rung": "local-medium",
        "spec.lease_wait_s": "0.0", "P.served.local_requests": "3",
        "P.served.fallback_requests": "0", "P.elapsed_s": "90.0",
        "W.started_at": "1790000000.0", "E": "2026-09-21T10:01:30Z", "spec.on_fail": "drop",
        "spec.mirror_rung": "sonnet-medium"}
CASES = {  # marker -> (placeholder overrides, expected row fields)
    "success": ({}, {"served_rung": "local", "fallback": None, "wall_s": 90.0,
                     "ended_at": "2026-09-21T10:01:30Z", "agent8": "abcdef12"}),
    "--fallback runaway": ({}, {"served_rung": "local", "fallback": "runaway", "wall_s": 90.0}),
    "--fallback watchdog-error": ({}, {"fallback": "watchdog-error", "wall_s": None,
                                       "agent8": "abcdef12"}),
    "--fallback background-spawn-failed": ({}, {"served_rung": "sonnet-mirror",
                                                "fallback": "background-spawn-failed",
                                                "rung": "sonnet-medium", "wall_s": None}),
    "--fallback <spec.fallback>": ({"spec.rung": "sonnet-medium", "spec.fallback": "local-busy"},
                                   {"served_rung": "sonnet-mirror", "fallback": "local-busy"}),
}


def _render(line: str, values: dict) -> list[str]:
    """`line` as argv after the script: an optional span stays only when all its placeholders
    have values; a placeholder outside one with no value is a KeyError (an unknown name)."""
    def opt(m):
        body = m.group(0)[1:-1]
        names = PLACEHOLDER_RE.findall(body)
        return body if names and all(n in values for n in names) else ""
    cmd = PLACEHOLDER_RE.sub(lambda m: shlex.quote(values[m.group(1)]),
                             OPTIONAL_RE.sub(opt, line.strip()))
    argv = shlex.split(cmd)
    return argv[next(i for i, a in enumerate(argv) if a.endswith("dispatch_log.py")) + 1:]


@pytest.mark.parametrize("marker", list(CASES))
def test_record_line_writes_the_row(marker, tmp_path, monkeypatch, capsys):
    text = _text()
    line = _success(_local()) if marker == "success" else _record(text, marker)
    overrides, want = CASES[marker]
    (tmp_path / "d").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    values = {**BASE, "d": str(tmp_path / "d"), **overrides}
    assert dispatch_log.main(_render(line, values)) == 0
    row = json.loads(capsys.readouterr().out)
    assert row["requested_rung"] == "local-medium" and row["lease_wait_s"] == 0.0
    for key, value in want.items():
        assert row.get(key) == value, (key, row)
