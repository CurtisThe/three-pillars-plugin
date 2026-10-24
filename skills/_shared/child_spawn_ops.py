#!/usr/bin/env python3
"""child_spawn_ops.py — the building blocks `child_spawn.py` composes and re-exports.

design: strata-session-isolation (design §B1, §B6, §B8). Split out of `child_spawn.py` before
Phase 4 (file-size cap): `child_spawn.py` keeps the lifecycle subcommands (`probe`, `smoke`,
`start`, `wait`) and the CLI; this module holds the leaves they call. Import them through
`child_spawn` — every name here is re-exported there, so `child_spawn.host_argv`,
`child_spawn.cmd_stop` and friends are the public spellings.

**Launch argv and env** (task 1.5; permission flags from strata-classifier-cost-followups task 1.3).
`host_argv` builds exactly `timeout -k 30 <CHILD_MAX_S> claude -p <host instruction> --agent
<tp-spawn-host ref> --session-id <uuid> --permission-mode <dontAsk|auto> --allowedTools <rules…>
--disallowedTools <rules…> --permission-prompts none --output-format json` — the mode and both rule
lists come from `child_permissions` for the child's `cwd` (design §A1/§A2), so a child never pays a
classifier call for a call its allow list covers, and never `bypassPermissions`. GNU `timeout`
signals the whole process group, so a
child can never outlive `CHILD_MAX_S` (env `TP_CHILD_MAX_S`, default 1800 s — deliberately above
`attempt_watchdog.DEFAULT_WALL_S`, so the watchdog explains a slow attempt before `timeout` kills it)
even when its dispatcher is gone. The host's one instruction names the inner `subagent_type` and
`model` and the prompt file to Read. `claude_bin` honours `TP_CHILD_SPAWN_CLAUDE` (the
`TP_WORKTREE_*_CMD` pattern) so a test can point at a fake claude. `child_env` drops
`CLAUDE_CODE_SESSION_ID` (the child is a separate session and must never inherit the dispatcher's id —
per-run child state and the router's slot keying both key on it) and the launcher keys of
`launcher_env` (main-thread-direct-backend §S1), so the child's launcher plans its own route
from the child's folder, and pins the parent's launcher profile so the child answers as the
profile the orchestrator runs as.

**`stop`** (task 3.1, design §B6) ends a child using only what its state file recorded —
`child_proc.stop_group` signals that recorded process group after `alive` proves the pid is still the
recorded process (a reused pid shows different start ticks and gets no signal at all),
`stopped_agents.append` records the inner agent so the router's backstop sees the stop,
`child_slot.release` ends the child session's claim on the slot, and the state file is rewritten
`stopped` (or `gone` when nothing was signalled). A stop is a report, not a failure. Nothing here
names a process; only the recorded pgid is ever signalled.

**`sweep`** (task 3.2, design §B6) is the same stop applied to a set of state files: `--run R` (default
`$CLAUDE_CODE_SESSION_ID`) stops every `running` state in that run's dir, and `--stale` walks every
run dir of the repo's child-state base and stops only a `running` state whose recorded `deadline_at`
(epoch seconds) is already past — so it is safe beside concurrent runs.

**`_probe_checks`** (task 3.3, design §B8) names the first unmet spawn prerequisite in a fixed order;
`child_spawn.cmd_probe` acts on it.

**`start`'s helpers** (tasks 4.2-4.3): `_env_s` (a positive env float), `_copy_prompt`, `_resolve_inner`
(poll for the one inner transcript, fail fast on a dead host, then `verify_host`) and `_fail` (stop the
recorded group, release the slot, mark the state `failed`). `child_spawn.cmd_start` composes them.
Stdlib only.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_ref  # noqa: E402
import child_permissions  # noqa: E402 — the §A1/§A2 permission flags the launch carries
import child_proc  # noqa: E402
import child_profile  # noqa: E402 - the profile pin and the dirs a scan polls
import child_slot  # noqa: E402
import child_state  # noqa: E402
import child_transcript  # noqa: E402
import launcher_env  # noqa: E402 — the §S1 launcher keys a child must not inherit
import scratch_root  # noqa: E402 — the scratch base the prompt copy and smoke file live under
import stopped_agents  # noqa: E402
import transcript_tail  # noqa: E402

__all__ = ["CHILD_MAX_S_DEFAULT", "KILL_GRACE_S", "HOST_AGENT", "HOST_MODEL", "CLAUDE_SESSION_ENV", "child_max_s",
           "claude_bin", "host_instruction", "host_argv", "child_env", "cmd_stop", "cmd_sweep",
           "RESOLVE_S", "RESOLVE_POLL_S", "PROMPT_SUBDIR", "CHILD_SESSION_ENV"]

CHILD_MAX_S_DEFAULT = 1800  # the `timeout` cap; > attempt_watchdog.DEFAULT_WALL_S (1200)
KILL_GRACE_S = 30           # `timeout -k`: TERM to the group, then KILL
HOST_AGENT = "tp-spawn-host"
HOST_MODEL = "sonnet"  # matches agents/tp-spawn-host.md
CLAUDE_SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
CHILD_SESSION_ENV = "TP_CHILD_SESSION"  # `start` sets it to "1": the Stop hook never gates a child
BG_WAIT_ENV = "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"  # 0 = no ceiling; timeout -k bounds the child
RESOLVE_S = 120             # `start`'s bound for the inner transcript to appear
RESOLVE_POLL_S = 1.0        # `start`'s poll interval while it waits for the inner transcript
PROMPT_SUBDIR = scratch_root.CHILD_SPAWN_DIR  # `.tp-scratch/child-spawn`: inside the project, excluded


def child_max_s(env: dict) -> int:
    """The hard cap in seconds: `TP_CHILD_MAX_S` when a positive int, else 1800."""
    raw = str(env.get("TP_CHILD_MAX_S", "")).strip()
    try:
        val = int(raw)
    except ValueError:
        return CHILD_MAX_S_DEFAULT
    return val if val > 0 else CHILD_MAX_S_DEFAULT


def claude_bin(env: dict) -> str:
    """The claude binary: `TP_CHILD_SPAWN_CLAUDE` when set (tests), else `claude`."""
    return env.get("TP_CHILD_SPAWN_CLAUDE") or "claude"


def host_instruction(agent_ref_: str, model: str, prompt_path: str) -> str:
    """The host's one job: one `Agent` call for the inner agent, then stop."""
    prompt = f"Read {prompt_path} with the Read tool first, then follow it exactly."
    return (f'Call the Agent tool exactly once with subagent_type={agent_ref_}, model={model}, '
            f'description="tp child task", prompt="{prompt}" — then stop.')


def host_argv(agent_ref_: str, model: str, prompt_path: str, session_id: str,
              env: dict | None = None, *, cwd: str = ".", mode: str = "dontAsk") -> list[str]:
    """The exact launch argv (design §B1 + §A1); `env=None` reads `os.environ`.

    `agent_ref_` is the *inner* agent's reference; the `--agent` flag carries the host's,
    resolved here by `agent_ref.resolve` and never guessed (an `AgentRefError` propagates —
    a rejected spawn is a loud halt, not a silent name). The permission flags come from
    `child_permissions` for `cwd` (the child's working dir, so its `Edit`/`Write` rules are
    scoped to it) and `mode` — `dontAsk` unless the caller says `auto` (§A4's fallback); a mode
    outside `child_permissions.MODES` raises rather than launching unfenced.
    """
    env = os.environ if env is None else env
    return [
        "timeout", "-k", str(KILL_GRACE_S), str(child_max_s(env)), claude_bin(env),
        "-p", host_instruction(agent_ref_, model, prompt_path),
        "--agent", agent_ref.resolve(HOST_AGENT),
        "--model", HOST_MODEL,
        "--session-id", session_id,
        *child_permissions.argv_flags(mode, *child_permissions.rules(
            cwd, child_permissions.load_config(cwd))[:2]),
        "--permission-prompts", "none",
        "--output-format", "json",
    ]


def child_env(env: dict) -> dict:
    """A copy of `env` without `CLAUDE_CODE_SESSION_ID` or the launcher's keys, ceiling off.

    `claude -p` stops its background tasks `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS` after its last
    turn (600 s by default), and the inner agent runs as one, so a longer task died mid-run. The
    child's lifetime is bounded by `host_argv`'s `timeout -k` instead. `launcher_env`'s scrub runs
    first: a parent's forced backend, role and owned vars are the parent's route, and the child's
    launcher plans its own from the child's folder (§S1). `child_profile.pin` then re-reads the
    unscrubbed `env` for the profile its config dir names, because the launcher owns that key.
    Never mutates its input.
    """
    out = {k: v for k, v in launcher_env.strip_launcher_keys(env).items()
           if k != CLAUDE_SESSION_ENV}
    out[BG_WAIT_ENV] = "0"
    return child_profile.pin(env, out)


def cmd_stop(state_path) -> dict:
    """Stop the child its state file recorded; `{"result": "ok"|"gone"|"error: …"}`. Never raises.

    Only the recorded group is ever signalled, and only once `child_proc.stop_group`'s own
    `alive` check has proved the pid still carries the recorded start ticks — a reused pid
    returns `gone` with no signal sent. The inner agent then goes to the stopped-agents file
    (keyed by the child session's first 8 chars, the same id8 the router's slot keying uses)
    and `child_slot.release` ends the child session's claim on the slot, even with no inner agent
    yet; both run on `gone` too, because a child whose pid is gone still holds its slot. The state file is rewritten
    `stopped` / `gone` to match the outcome — but not on an `error:` from the signal path,
    where the child may still be running and a later `sweep` must find it `running`.
    """
    try:
        state = child_state.read(state_path)
        child = str(state.get("child_session", ""))
        if not state or not child:
            return {"result": f"error: no state at {state_path}"}
        result = child_proc.stop_group(int(state.get("pid", 0)), int(state.get("pgid", 0)),
                                       int(state.get("start_ticks") or -1))
        inner = str(state.get("inner_agent_id", ""))
        if inner:
            stopped_agents.append(inner, attempt_id=child[:8])
        child_slot.release(inner or None, child)  # a host that never spawned still holds its slot
        if result == "ok":
            state["state"] = "stopped"
            child_state.write(state_path, state)
        elif result == "gone":
            state["state"] = "gone"
            child_state.write(state_path, state)
        return {"result": result}
    except Exception as exc:  # noqa: BLE001 — a stop reports, it never crashes the caller
        return {"result": f"error: {exc}"}


def _common_dir(root) -> Path:
    """The base the child-state dirs hang off: `child_state`'s git common dir, else `$TMPDIR`.

    Read-only on purpose — `run_dir` would create the per-run directory, and a `--stale` sweep of
    a machine with no children must leave nothing behind. Same fallback as `run_dir`, so a sweep
    looks in exactly the place a `start` wrote.
    """
    return child_state._git_common_dir(root) or Path(tempfile.gettempdir())


def _is_stale(state: dict, now: float) -> bool:
    """True when `state` is a `running` child whose `deadline_at` (epoch seconds) is already past.

    A missing or non-numeric `deadline_at` is never stale: a state written before Phase 4 (or a
    hand-edited one) gets no deadline, and guessing one could stop a child that is still working.
    """
    if state.get("state") != "running":
        return False
    try:
        deadline = float(state.get("deadline_at"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return now > deadline


def cmd_sweep(run: str | None = None, stale: bool = False, root=".") -> dict:
    """Stop a set of children; `{"stopped": [...], "gone": [...]}` of child sessions. Never raises.

    `run=None` means this session (`$CLAUDE_CODE_SESSION_ID`), the same default `child_state` uses.
    Without `stale` the scope is one run's own directory — every `running` state in it, because a
    run that is ending has no use for a live child of its own. With `stale` the scope is every run
    directory of this repo, and the filter is `deadline_at`: a child still inside its deadline
    belongs to a run that is live on this machine right now, so it is left alone. Both paths stop
    through `cmd_stop`, so a stop is the one verified act it always is (pid + start ticks) and a
    dead recorded pid simply comes back `gone` and marks its state `gone`.

    An `error: …` reply goes in neither list: that child may still be running and its state is
    still `running`, so the next sweep finds it. An unreadable state file reads as `{}` and is
    skipped, which is what keeps a corrupt file from ending a sweep early.
    """
    stopped: list[str] = []
    gone: list[str] = []
    try:
        if stale:
            now = time.time()
            paths = [p for run_dir in child_state.all_run_dirs(_common_dir(root))
                     for p in child_state.children(run_dir)
                     if _is_stale(child_state.read(p), now)]
        else:
            paths = [p for p in child_state.children(child_state.run_dir(run, root=root))
                     if child_state.read(p).get("state") == "running"]
        for path in paths:
            child = str(child_state.read(path).get("child_session", ""))
            if not child:
                continue
            result = cmd_stop(path)["result"]
            if result == "ok":
                stopped.append(child)
            elif result == "gone":
                gone.append(child)
    except Exception:  # noqa: BLE001 — a sweep reports what it reached, it never crashes a site
        pass
    return {"stopped": stopped, "gone": gone}


def _probe_checks(env: dict) -> str | None:
    """The first unmet prerequisite in design order, or None when every one holds (§B8).

    The order is the cheap-to-expensive one: an opt-out, then two `PATH` lookups, then `/proc`,
    then the router install. One reason is reported, because a site acts on one.
    """
    if env.get("TP_CHILD_SPAWN") == "0":
        return "off (TP_CHILD_SPAWN=0)"
    if not shutil.which(claude_bin(env)):
        return "no claude CLI"
    if not shutil.which("timeout"):
        return "no timeout"
    if not child_proc.has_proc():
        return "no /proc"
    if not child_slot.can_release_session():
        return "router lacks release_session"
    return None


def _env_s(name: str, default: float) -> float:
    """A positive float from `os.environ[name]`, else `default` (unset, garbage, 0 or negative)."""
    try:
        val = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return val if val > 0 else default


def _copy_prompt(cwd: Path, child8: str, prompt_file: str) -> Path:
    """Copy the site's prompt into the project — the host `Read`s it by exactly this path."""
    scratch_root.ensure_excluded(cwd)  # first writer into `.tp-scratch/`: keep the tree clean
    dest = cwd / PROMPT_SUBDIR / f"{child8}.prompt.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(prompt_file, dest)
    return dest


def _resolve_inner(child: str, agent_ref_: str, model: str, pid: int | None = None,
                   ticks: int | None = None) -> tuple[str | None, str]:
    """The child's one inner agent id once its host is verified, else `(None, why)`.

    Polls every `RESOLVE_POLL_S` (first check immediately) for at most `_env_s
    ("TP_CHILD_RESOLVE_S", RESOLVE_S)` seconds — the fake claude of the tests writes its
    transcripts in milliseconds, a real host takes seconds, and a child that never gets there is a
    spawn failure the site acts on rather than a hang. Zero ids keeps polling; more than one is a
    host that did more than its one job, which no waiting fixes. A dead host ends the poll early
    (one last look first, so a host that wrote its transcripts and exited still resolves) rather
    than making a launch that died at once wait out the whole bound. Then `verify_host` over the
    host's own transcript proves the one `Agent` call carried the requested `subagent_type` and
    `model`.
    """
    bound = _env_s("TP_CHILD_RESOLVE_S", RESOLVE_S)
    until = time.monotonic() + bound
    ids: list[str] = []
    gone = False
    while True:
        ids = child_transcript.inner_ids(child)
        if ids:
            break
        gone = pid is not None and ticks is not None and not child_proc.alive(pid, ticks)
        if gone:
            ids = child_transcript.inner_ids(child)
            break
        if time.monotonic() >= until:
            break
        time.sleep(RESOLVE_POLL_S)
    if not ids:
        return None, ("host exited before an inner transcript appeared" if gone
                      else f"no inner transcript within {bound:g}s") + child_profile.polled_note()
    if len(ids) > 1:
        return None, f"{len(ids)} inner transcripts, expected 1"
    host = child_transcript.host_path(child)
    records = transcript_tail.read_records(host) if host is not None else []
    ok, why = child_transcript.verify_host(records, agent_ref_, model)
    return (ids[0], "") if ok else (None, f"host mismatch: {why}")


def _fail(why: str, child: str, state_path: str, state: dict | None) -> dict:
    """One spawn failure's whole cleanup: stop the recorded group, release the slot, mark `failed`.

    Nothing here raises — a cleanup that cannot happen must not turn a reported failure into a
    traceback, and it never signals anything beyond the group the state recorded. `release` runs
    even with no inner agent (a host that died before spawning still holds its session's slot).
    The state file is written even when the launch itself errored before one existed, so a site and
    a later `sweep` find `failed` plus its `why` rather than nothing at all.
    """
    try:
        if state and "pid" in state:
            child_proc.stop_group(int(state["pid"]), int(state.get("pgid", 0)),
                                  int(state.get("start_ticks") or -1))
    except Exception:  # noqa: BLE001 — the stop is cleanup, never the report
        pass
    try:
        child_slot.release(str((state or {}).get("inner_agent_id", "")) or None, child)
    except Exception:  # noqa: BLE001 — a release failure is the router's to explain
        pass
    record = state if state is not None else {"child_session": child}
    record.update({"state": "failed", "why": why})
    try:
        if state_path:
            child_state.write(state_path, record)
    except Exception:  # noqa: BLE001 — an unwritable state dir loses the file, not the reply
        pass
    return {"state": "failed", "why": why, "child_session": child, "state_path": state_path}
