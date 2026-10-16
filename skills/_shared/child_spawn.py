#!/usr/bin/env python3
"""child_spawn.py — the one spawner: it composes the child modules into a CLI.

design: strata-session-isolation (design §B1, §B6, §B8). `main` is the CLI — `probe`, `smoke`,
`start`, `wait`, `stop`, `sweep`; every subcommand answers one JSON line on stdout and returns its
exit code (0 ok, 3 failed, 4 in-process or still running, 2 usage). Stdlib only.

The leaves live in `child_spawn_ops.py` and are re-exported here, so `child_spawn.host_argv`,
`child_spawn.child_env`, `child_spawn.cmd_stop` and `child_spawn.cmd_sweep` stay the public
spellings; the argparse surface lives in `child_spawn_cli.py`. This module keeps what composes them
and calls each leaf through its own namespace, so patching `child_spawn.cmd_sweep` patches what
`cmd_probe` calls.

`probe` (§B8) answers one question per run — can this run spawn a child at all — as
`{"mode": "child"|"in-process", "why": …}` (exit 0 / 4), naming the FIRST unmet prerequisite, cached
in that run's `probe.json`. `start` (§B1) is the one spawn: copy the prompt into the project, note
the child's busy policy, merge the Bash-sandbox block for a sandboxed site (§B2,
`child_sandbox.prepare`), launch the pinned host argv in its own process group with an env that drops
`CLAUDE_CODE_SESSION_ID`, record a `running` state file with `deadline_at`, then wait ≤ `RESOLVE_S`
(env `TP_CHILD_RESOLVE_S`) for one inner subagent transcript and verify the host's one `Agent` call.
A failure is a `{"state": "failed", "why": …}` reply at exit 3, never a traceback. `smoke` (§B8) is
the end-to-end proof: a `tp-runbook` child runs `git status --porcelain` and writes a token plus that
exit code to a file; `ok` needs no denial, a verified host, the token and an `exit=<code>` line.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_ref  # noqa: E402 — `smoke` resolves the runbook agent through it
import child_permissions  # noqa: E402 — `start` reports its config warnings on stderr
import child_proc  # noqa: E402,F401 — the lifecycle subcommands launch and stop through it
import child_sandbox  # noqa: E402 — §B2: `start` merges the sandbox block before the launch
import child_slot  # noqa: E402,F401
import child_state  # noqa: E402
import child_transcript  # noqa: E402 — `wait` reads the inner turn through it
import children_route  # noqa: E402 — `probe` floors a direct run's in-process verdict to Sonnet
import local_implement_config  # noqa: E402 — `smoke`'s default model is the local alias
import model_policy  # noqa: E402
import permission_refusal  # noqa: E402 — `wait` carries a refused call into the reply file
import wait_budget  # noqa: E402 — `wait`'s default budget
from child_spawn_cli import CMDS, _parser  # noqa: E402 — the argparse surface `main` reads
from child_spawn_ops import (  # noqa: E402,F401 — re-exported: the public spellings live here
    CHILD_MAX_S_DEFAULT, CLAUDE_SESSION_ENV, HOST_AGENT, KILL_GRACE_S, PROMPT_SUBDIR, RESOLVE_POLL_S,
    RESOLVE_S, _common_dir, _copy_prompt, _env_s, _fail, _is_stale, _probe_checks, _resolve_inner,
    child_env, child_max_s, claude_bin, cmd_stop, cmd_sweep, host_argv, host_instruction)

__all__ = ["CHILD_MAX_S_DEFAULT", "RESOLVE_S", "HOST_EXIT_S", "WAIT_POLL_S", "child_max_s",
           "claude_bin", "host_instruction", "host_argv", "child_env", "cmd_probe", "cmd_start",
           "cmd_wait", "cmd_stop", "cmd_sweep", "cmd_smoke", "new_token", "claude_version", "emit",
           "main"]

HOST_EXIT_S = 60            # a host lingering past its inner turn, then it is stopped
WAIT_POLL_S = 1.0           # `wait`'s poll interval while the child is still working
SMOKE_WAIT_S = 300          # `smoke`'s whole budget for the child to finish
# §A4: the one line a fallback launch owes — `auto` pays about a classifier check per session.
AUTO_FALLBACK_WARNING = ("W: claude lacks dontAsk — launching in auto instead: about 1 classifier "
                         "check per session, and the deny list is the only fence")


def emit(obj: dict, code: int) -> int:
    """Print one JSON line on stdout and return the exit code."""
    print(json.dumps(obj))
    return code


def cmd_probe(run: str | None = None, root=".", env: dict | None = None) -> dict:
    """`{"mode": "child"|"in-process", "why": …}` — this run's answer, computed once. Never raises.

    `run=None` means this session, `env=None` reads `os.environ` at call time. A cached
    `<run dir>/probe.json` is returned as-is. On a miss the ordered checks run; on an all-pass
    `cmd_sweep(stale=True)` reaps any past-deadline leftover of a crashed run first. Then a cached
    smoke pass for this `claude --version` **and** launch mode (§A4; recorded as `dont_ask`) answers
    `child`, else `smoke` runs: a pass is cached per repo, a failure `in-process (smoke: <why>)`.
    """
    try:
        env = os.environ if env is None else env
        rd = child_state.run_dir(run, root=root)
        cached = child_state.probe_cache(rd)
        if cached is not None:
            return cached
        why = _probe_checks(env)
        if why is None:
            cmd_sweep(stale=True, root=root)
            # §A4: the mode keys the smoke cache, so an `auto` pass never answers a `dontAsk` probe
            version, common = claude_version(env), _common_dir(root)
            dont_ask = child_permissions.dont_ask_supported(env)
            mode = "dontAsk" if dont_ask else "auto"
            if child_state.smoke_cache(common, version, mode=mode) is not None:
                verdict = {"mode": "child", "why": "smoke passed (cached)", "dont_ask": dont_ask}
            else:
                res = cmd_smoke(cwd=root, run=run)
                if res.get("ok"):
                    (Path(common) / child_state.CHILDREN_DIR).mkdir(parents=True, exist_ok=True)
                    child_state.write_smoke(common, version, res, mode=mode)
                    verdict = {"mode": "child", "why": "smoke passed", "dont_ask": dont_ask}
                else:  # cached in this run's probe.json only, so the next run smokes again
                    verdict = {"mode": "in-process", "why": f"smoke: {res.get('why')}"}
        else:
            verdict = {"mode": "in-process", "why": why}
        verdict = children_route.floor_in_process(verdict, env)
        child_state.write_probe(rd, verdict)
        return verdict
    except Exception as exc:  # noqa: BLE001 — a probe that cannot decide degrades, it never crashes a site
        return {"mode": "in-process", "why": f"probe error: {exc}"}


def cmd_start(site: str, agent_ref_: str, model: str, prompt_file: str, cwd: str = ".",
              busy_policy: str | None = None, run: str | None = None) -> dict:
    """Spawn one child session; `{"child_session", "pid", "inner_agent_id", "state_path", "state"}`.

    Never raises: anything that goes wrong is `{"state": "failed", "why": …}` for `main` to exit 3
    on. The order is the design's (§B1): a `uuid4` child session, the prompt copied into the
    project, the busy policy noted for the *child's* key, the repo config read once (its skipped
    rules reported, its `strata_spawn.sandbox` switch deciding the §B2 sandbox merge for this site's
    worktree — before the launch, so the child reads the file it was granted), then the pinned host
    argv in its own process group with an env that drops `CLAUDE_CODE_SESSION_ID`. `deadline_at` is
    plain epoch seconds, so `sweep --stale` reads it and `timeout` bounds the child.

    The state goes `running` immediately after the launch (a crash mid-resolve leaves a sweepable
    file, not an unowned process) and is rewritten with `inner_agent_id` once the inner agent is
    resolved and its host verified. Every later failure goes through `_fail`, so a failed spawn never
    leaves a live group, a held slot or a `running` state behind (task 4.3).
    """
    child = str(uuid.uuid4())
    child8 = child[:8]
    wd = Path(cwd).resolve()  # absolute: the host Reads the prompt copy by this exact path
    state_path = ""
    state: dict | None = None
    try:
        rd = child_state.run_dir(run, root=str(wd))
        state_path = str(rd / f"{child8}.json")
        out_path = rd / f"{child8}.out"  # NOT `.json`: `children` reads every `*.json` as a state
        prompt_copy = _copy_prompt(wd, child8, prompt_file)
        child_slot.note_policy(child, override=busy_policy)
        started_at = time.time()
        # §A4: the mode is this run's probe answer when it has one, else one `claude --help`.
        mode = _launch_mode(rd)
        if mode == "auto":
            print(AUTO_FALLBACK_WARNING, file=sys.stderr)
        # §A2 + §B2: the repo config is read once — a `rules` entry it skips is reported (the flags
        # `host_argv` renders for the same `wd` carry the rest of the policy), and the
        # `strata_spawn.sandbox` switch decides this site's sandbox merge before the launch.
        config = child_permissions.load_config(str(wd))
        for warning in child_permissions.rules(str(wd), config)[2]:
            print(warning, file=sys.stderr)
        sandbox_state, warns = child_sandbox.prepare(wd, site, config, os.environ)
        for warning in warns:
            print(warning, file=sys.stderr)
        # The child's env carries the policy this spawn noted, so the child never re-derives
        # it from a parent env that may no longer say what the run decided (task 5.1).
        launch_env = child_env(os.environ)
        launch_env["TP_LOCAL_MODE"] = child_slot.resolved_policy(busy_policy)
        rec = child_proc.launch(host_argv(agent_ref_, model, str(prompt_copy), child,
                                          cwd=str(wd), mode=mode),
                                str(wd), out_path=str(out_path), env=launch_env)
        if "pid" not in rec:
            return _fail(f"launch: {rec.get('error')}", child, state_path, state)
        state = {"child_session": child, "run": rd.name, "pid": rec["pid"], "pgid": rec["pgid"],
                 "start_ticks": rec["start_ticks"], "cwd": str(wd.absolute()), "site": site,
                 "agent_ref": agent_ref_, "model": model, "prompt_path": str(prompt_copy),
                 "out_path": str(out_path), "started_at": started_at,
                 "deadline_at": started_at + child_max_s(os.environ),
                 "permission_mode": mode, "inner_agent_id": "", "state": "running",
                 "sandbox": "on" if sandbox_state != "off" else "off",  # §B2: switch + decision
                 "sandbox_state": sandbox_state}
        child_state.write(state_path, state)
        inner, why = _resolve_inner(child, agent_ref_, model, rec["pid"], rec["start_ticks"])
        if inner is None:
            return _fail(why, child, state_path, state)
        state["inner_agent_id"] = inner
        child_state.write(state_path, state)
        return {"child_session": child, "pid": rec["pid"], "inner_agent_id": inner,
                "state_path": state_path, "state": "running", "permission_mode": mode}
    except Exception as exc:  # noqa: BLE001 — a spawn that cannot happen is a reply, not a crash
        return _fail(f"start error: {exc}", child, state_path, state)


def _launch_mode(rd) -> str:
    """§A4: this run's probe answer (`dont_ask` key) when it has one, else one `claude --help`."""
    cached = child_state.probe_cache(rd) or {}
    if "dont_ask" in cached:
        return "dontAsk" if cached["dont_ask"] else "auto"
    return "dontAsk" if child_permissions.dont_ask_supported(os.environ) else "auto"


def _host_result(state: dict) -> dict | None:
    """§A3: the child's last printed result object, as `_smoke_waited` reads it. None if unreadable."""
    try:
        raw = Path(str(state.get("out_path"))).read_text(encoding="utf-8", errors="replace")
        return json.loads([ln for ln in raw.splitlines() if ln[:1] == "{"][-1])
    except (OSError, ValueError, IndexError, TypeError):
        return None


def cmd_wait(state_path, budget_s: float = wait_budget.WAIT_BUDGET_S,
             reply_out: str | None = None) -> dict:
    """Poll one child to `done` / `failed` / `running`; never raises, signals only its own group.

    Checks first, then sleeps `WAIT_POLL_S`, until `budget_s` is spent. Every poll asks two questions —
    is the host process still alive, has the inner turn ended — and the child is `done` when its host
    is gone (or has been stopped) AND its inner turn has ended: the inner agent's last text goes to
    `reply_out` (else the state path with `.json` → `.reply.txt`, never `.json`: `child_state.children`
    reads every `*.json` as a state), the slot is released and the state says `done`. §A3: a refused
    call prepends `permission_refusal.lines(...)` to that text, so the ladder's `--reply-json F`
    reader sees the class without a second file. A host still alive
    `_env_s("TP_CHILD_HOST_EXIT_S", HOST_EXIT_S)` seconds after its turn ended is lingering, so
    `wait` stops the recorded process group and reads the child as `done` anyway (task 4.5). A host
    gone with its inner turn still open is polled until `deadline_at` (`_is_stale`'s reading, so a
    missing/non-numeric one is no deadline), then it is `failed (deadline)`. A state already
    `done`/`failed`/`stopped`/`gone` is reported as-is, so a second `wait` cannot hang.
    """
    try:
        state = child_state.read(state_path)
        if not state:
            return {"state": "failed", "why": f"no state at {state_path}"}
        if state.get("state") != "running":
            out = {"state": str(state.get("state", "failed"))}
            if state.get("reply_path"):
                out["reply_path"] = state["reply_path"]
            if state.get("why"):
                out["why"] = str(state["why"])
            return out
        inner = str(state.get("inner_agent_id", ""))
        pid = int(state.get("pid", 0))
        ticks = int(state.get("start_ticks") or -1)
        until = time.monotonic() + budget_s
        ended_at = 0.0
        while True:
            alive = child_proc.alive(pid, ticks)
            ended = bool(inner) and child_transcript.inner_done(inner)
            if alive and ended:
                ended_at = ended_at or time.monotonic()
                if time.monotonic() - ended_at >= _env_s("TP_CHILD_HOST_EXIT_S", HOST_EXIT_S):
                    if child_proc.stop_group(pid, int(state.get("pgid", 0)), ticks) in ("ok", "gone"):
                        alive = False
            if not alive and ended:
                reply = Path(reply_out) if reply_out \
                    else Path(str(state_path)).with_suffix(".reply.txt")
                reply.parent.mkdir(parents=True, exist_ok=True)
                # §A3: a refused call is carried in the reply the ladder already reads — the
                # structured host result first, the inner transcript's prose only as a fallback.
                rules = permission_refusal.from_result(_host_result(state)) or \
                    permission_refusal.from_records(child_transcript._inner_records(inner))
                text = child_transcript.last_text(inner)
                banner = permission_refusal.lines(rules)
                reply.write_text("\n".join(banner + [text]) if banner else text,
                                 encoding="utf-8")
                child_slot.release(inner, str(state.get("child_session", "")))
                state["state"] = "done"
                state["reply_path"] = str(reply)
                child_state.write(state_path, state)
                return {"state": "done", "reply_path": str(reply)}
            if not alive and not ended and _is_stale(state, time.time()):
                child_slot.release(inner or None, str(state.get("child_session", "")))
                state["state"] = "failed"
                state["why"] = "deadline"
                child_state.write(state_path, state)
                return {"state": "failed", "why": "deadline"}
            if time.monotonic() >= until:
                return {"state": "running"}
            time.sleep(WAIT_POLL_S)
    except Exception as exc:  # noqa: BLE001 — a wait that cannot decide is a reply, not a crash
        return {"state": "failed", "why": f"wait error: {exc}"}


def new_token() -> str:
    """The smoke file's 16-hex token — a module global so a test can hand back a fixed one."""
    return secrets.token_hex(8)


def claude_version(env: dict | None = None) -> str:
    """`claude --version` stripped; error / non-zero / empty → `"unknown"`. Never raises."""
    try:
        done = subprocess.run([claude_bin(env or os.environ), "--version"],
                              capture_output=True, text=True, timeout=30)
        return (done.stdout.strip() or "unknown") if done.returncode == 0 else "unknown"
    except Exception:  # noqa: BLE001 — a version nobody can read is still an answer, not a crash
        return "unknown"


def cmd_smoke(model: str | None = None, cwd=".", run: str | None = None) -> dict:
    """`{"ok", "why", "claude_version"}` — one real child round-trip proves §B8; never raises. Its
    why names the layer: `verify:` (start's resolve + `verify_host`), `wait:`, `denied:` (the host's
    own result JSON), `inner tools:` (the smoke file `new_token` names — read, then deleted)."""
    try:
        model = model or model_policy.agent_spec(
            "tp-runbook", None, local_implement_config.DEFAULTS)["model"]
        version, wd, token = claude_version(), Path(cwd).resolve(), new_token()
        smoke = wd / PROMPT_SUBDIR / f"smoke-{token}.txt"
        fd, prompt = tempfile.mkstemp(suffix=".md")
        os.close(fd)
        try:
            Path(prompt).write_text(f"Run `git status --porcelain` with the Bash tool, then write "
                                    f"{smoke} — line 1 `{token}`, line 2 `exit=<its exit code>` — "
                                    "then reply `done`.\n", encoding="utf-8")
            res = cmd_start("smoke", agent_ref.resolve("tp-runbook"), model, prompt,
                            cwd=str(wd), run=run)
            why = (f"verify: {res.get('why')}" if res.get("state") == "failed" else
                   _smoke_waited(res["state_path"], smoke, token))
            return {"ok": not why, "why": why or "smoke passed", "claude_version": version}
        finally:
            os.unlink(prompt)
    except Exception as exc:  # noqa: BLE001 — a smoke that cannot run is a reply, not a crash
        return {"ok": False, "why": f"smoke error: {exc}", "claude_version": "unknown"}


def _smoke_waited(state_path, smoke: Path, token: str) -> str:
    """`wait`, then the two answers a `done` child owes: "" = pass, else the why. Never raises.

    task 1.4: one `finally` removes the smoke file on **every** exit (pass, `denied:`, `wait:`) —
    dirt at `smoke-<token>.txt` is what the next `task_verify.py open` reads as `dirty-tree`.
    """
    try:
        w = cmd_wait(state_path, budget_s=SMOKE_WAIT_S)
        if w.get("state") != "done":
            cmd_stop(state_path)
            return f"wait: {w.get('why') or w.get('state')}"
        try:  # the host's result JSON is the last object line it printed (a deny is not a pass)
            out = Path(str(child_state.read(state_path).get("out_path")))
            raw = out.read_text(encoding="utf-8", errors="replace")
            obj = json.loads([ln for ln in raw.splitlines() if ln[:1] == "{"][-1])
        except (OSError, ValueError, IndexError):
            return "denied: unreadable host output"
        den = obj.get("permission_denials") if isinstance(obj, dict) else None
        if den is None:
            return "denied: unreadable host output"
        if obj.get("is_error") or den:
            return f"denied: {(den[0].get('tool_name') if den else '') or 'host'}"
        try:
            got = [ln.strip() for ln in smoke.read_text(encoding="utf-8").splitlines()]
        except OSError:
            return "inner tools: no smoke file"
        if token not in got:
            return "inner tools: no token"
        return "" if any(ln[:5] == "exit=" and ln[5:].isdigit() for ln in got) \
            else "inner tools: no exit code"
    finally:
        smoke.unlink(missing_ok=True)


def main(argv=None) -> int:
    """One JSON line + an exit code. Usage errors exit 2 with no non-JSON stdout."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # argparse writes usage to stderr and exits 2/0
        return 2 if exc.code else 0
    if args.cmd not in CMDS:
        return emit({"error": "usage: child_spawn.py " + "|".join(CMDS)}, 2)
    if args.cmd == "probe":  # 0 = spawn a child, 4 = run in-process (the why is the report)
        res = cmd_probe(args.run, args.root)
        return emit(res, 0 if res.get("mode") == "child" else 4)
    if args.cmd == "start":  # 3 = the spawn failed; the why is the site's degrade path
        res = cmd_start(args.site, args.agent_ref, args.model, args.prompt_file,
                        args.cwd, args.busy_policy, args.run)
        return emit(res, 3 if res.get("state") == "failed" else 0)
    if args.cmd == "smoke":  # 3 = the round-trip failed; the why says which layer
        res = cmd_smoke(args.model, args.cwd, args.run)
        return emit(res, 0 if res.get("ok") else 3)
    if args.cmd == "wait":  # 4 = still running when the budget ran out (the child keeps working), 3 = failed
        res = cmd_wait(args.state, args.budget_s, args.reply_out)
        return emit(res, 0 if res.get("state") == "done" else 4 if res.get("state") == "running" else 3)
    if args.cmd == "stop":  # always exit 0: a stop reports, it does not fail the caller
        return emit(cmd_stop(args.state), 0)
    if args.cmd == "sweep":  # likewise a sweep: what it stopped is the report
        return emit(cmd_sweep(args.run, args.stale, args.root), 0)
    return emit({"error": "not implemented", "cmd": args.cmd}, 2)


if __name__ == "__main__":
    sys.exit(main())
