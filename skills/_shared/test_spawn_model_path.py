"""test_spawn_model_path.py — Behavior 7 regression replay: the actual spawn-model path.

design: hybrid-routing-hardening (detailed-design.md §Spawn-model wiring, test spec :410-418)

End to end, through THIS branch's own CLIs (never a transcribed constant): a tmp repo with
`local_implement.model: haiku` and `ANTHROPIC_BASE_URL` unset must never render an actual spawn
whose `model=` is haiku-family. Three ways a first attempt's route can reach `tier_ladder.py
start`, all under the same unrouted env:

  (a) `local_route_check.py check`'s own stdout fed straight to `start --route`;
  (b) that line piped through `local_route_log.py append`, then `start --route-from`;
  (c) the full-design carrier: `check --decisions` piped to `append`, its `route` projection
      fed to `start --route`.

Each reads `model` from `start`'s stdout, renders the single `## 3.` spawn template **parsed
from `local-dispatch.md`** (never hand-copied) and asserts the rendered call says
`model="sonnet"` — never `haiku`. `next` is then driven through FAIL / unavailable / PASS and no
printed `model` is ever haiku-family; the record's `tier_path` never contains `local` (it was
floored to `sonnet` before the first attempt even opened). A routed control (env naming a
fixture router) prints `local` + `haiku`, so the floor only fires when actually unrouted.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from agent_ref import resolve as _ref  # the spawn reference (this install's plugin name)

SHARED = Path(__file__).resolve().parent
CHECK = SHARED / "local_route_check.py"
APPEND = SHARED / "local_route_log.py"
LADDER = SHARED / "tier_ladder.py"
DISPATCH_MD = SHARED / "local-dispatch.md"
FIXTURE_BYTES = (SHARED / "fixtures" / "tp_local_health_v1.json").read_bytes()

TASK_ID = "5.2"


# --- env / repo scaffolding -------------------------------------------------

def _env(base_url: str | None = None) -> dict:
    env = dict(os.environ)
    env.pop("ANTHROPIC_BASE_URL", None)
    if base_url is not None:
        env["ANTHROPIC_BASE_URL"] = base_url
    return env


def _cfg_root(tmp_path: Path) -> Path:
    """A tmp repo whose `local_implement.model` is `haiku` (the config default)."""
    root = tmp_path / "repo"
    (root / ".three-pillars").mkdir(parents=True)
    cfg = {"local_implement": {"enabled": True, "full_design": True, "model": "haiku",
                               "fallback_model": "sonnet", "escalate": True,
                               "max_retries": 2, "max_files": 3}}
    (root / ".three-pillars" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return root


# --- CLI runner --------------------------------------------------------------

def _run(script: Path, *args: str, env: dict, stdin: str | None = None) -> str:
    proc = subprocess.run([sys.executable, str(script), *args], input=stdin,
                          capture_output=True, text=True, timeout=30, env=env)
    assert proc.returncode == 0, f"{script.name} {args}: exit {proc.returncode}; stderr={proc.stderr!r}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"{script.name} {args}: expected one JSON line, got {proc.stdout!r}"
    return lines[0]


# --- the §3 template, parsed from local-dispatch.md, never hand-copied ------

def _first_python_template() -> str:
    """The first ```python fenced block under the `## 3.` heading."""
    text = DISPATCH_MD.read_text(encoding="utf-8")
    head = text.index("## 3.")
    section = text[head:]
    nxt = section.find("\n## 4.")
    if nxt != -1:
        section = section[:nxt]
    start = section.index("```python\n") + len("```python\n")
    end = section.index("```", start)
    return section[start:end]


def _render_and_assert_model(result: dict, expect_model: str) -> None:
    template = _first_python_template()
    rendered = template.format(model=result["model"], id=TASK_ID, tier=result["tier"],
                               rung=result["rung"], n=1, agent_ref=result["agent_ref"])
    assert f'model="{expect_model}"' in rendered, f"rendered spawn: {rendered!r}"
    assert f'subagent_type="{result["agent_ref"]}"' in rendered, f"rendered spawn: {rendered!r}"


# --- driving `next` after the first attempt ---------------------------------

def _drive_next(record: Path, root: Path, env: dict) -> list[dict]:
    """FAIL (retry, same rung) -> unavailable (escalate) -> PASS (done);
    returns each printed `{action, tier, model}`."""
    steps = []
    steps.append(json.loads(_run(
        LADDER, "next", "--record", str(record), "--outcome", "FAIL",
        "--reason", "assertion failed", "--root", str(root), env=env)))
    steps.append(json.loads(_run(
        LADDER, "next", "--record", str(record), "--outcome", "unavailable",
        "--reason", "backend unreachable", "--root", str(root), env=env)))
    steps.append(json.loads(_run(
        LADDER, "next", "--record", str(record), "--outcome", "PASS",
        "--root", str(root), env=env)))
    return steps


def _assert_no_haiku_and_no_local(steps: list[dict], record: Path) -> None:
    for step in steps:
        model = step.get("model")
        if model is not None:
            assert "haiku" not in model.lower(), f"haiku-family model escaped: {step!r}"
    tier_path = json.loads(record.read_text(encoding="utf-8"))["tier_path"]
    assert not [t for t in tier_path if t.split("-")[0] == "local"], (
        f"local rung reappeared after a floor: {tier_path!r}")


# --- (a) check's own stdout, fed straight to start --route ------------------

def test_check_stdout_fed_to_start_route(tmp_path):
    root = _cfg_root(tmp_path)
    env = _env(None)
    check_line = _run(CHECK, "check", env=env)
    rec = tmp_path / "a.json"
    out = json.loads(_run(
        LADDER, "start", "--task", TASK_ID, "--tier", "local", "--record", str(rec),
        "--route", check_line, "--root", str(root), env=env))
    assert out == {"tier": "sonnet", "rung": "sonnet-medium",
                   "agent": "tp-task-worker-sonnet-medium", "agent_ref": _ref("tp-task-worker-sonnet-medium"), "model": "sonnet",
                   "reason": "unrouted/no-base-url",
                   "plan_tier": "local", "display": "local->sonnet: unrouted/no-base-url"}
    _render_and_assert_model(out, "sonnet")
    _assert_no_haiku_and_no_local(_drive_next(rec, root, env), rec)


# --- (b) check piped through append, then start --route-from ----------------

def test_check_piped_through_append_then_route_from(tmp_path):
    root = _cfg_root(tmp_path)
    env = _env(None)
    decisions = tmp_path / "decisions.md"
    check_line = _run(CHECK, "check", "--decisions", str(decisions), "--scope", "run-start",
                      env=env)
    append_out = json.loads(_run(APPEND, "append", "--decisions", str(decisions),
                                 stdin=check_line, env=env))
    assert append_out["appended"] is True and append_out["error"] is None
    rec = tmp_path / "b.json"
    out = json.loads(_run(
        LADDER, "start", "--task", TASK_ID, "--tier", "local", "--record", str(rec),
        "--route-from", str(decisions), "--root", str(root), env=env))
    assert out["reason"] == "unrouted/no-base-url"
    assert out["model"] == "sonnet"
    _render_and_assert_model(out, "sonnet")
    _assert_no_haiku_and_no_local(_drive_next(rec, root, env), rec)


# --- (c) the full-design carrier: check --decisions | append -> its `route` -> start --route

def test_full_design_carrier_route_projection(tmp_path):
    root = _cfg_root(tmp_path)
    env = _env(None)
    decisions = tmp_path / "decisions.md"
    check_line = _run(CHECK, "check", "--decisions", str(decisions), "--scope", "phase 1",
                      env=env)
    append_out = json.loads(_run(APPEND, "append", "--decisions", str(decisions),
                                 stdin=check_line, env=env))
    route = append_out["route"]
    assert route is not None and set(route) == {"schema", "state", "reason", "base_url",
                                                 "checked_at"}
    rec = tmp_path / "c.json"
    out = json.loads(_run(
        LADDER, "start", "--task", TASK_ID, "--tier", "local", "--record", str(rec),
        "--route", json.dumps(route), "--root", str(root), env=env))
    assert out["reason"] == "unrouted/no-base-url"
    assert out["model"] == "sonnet"
    _render_and_assert_model(out, "sonnet")
    _assert_no_haiku_and_no_local(_drive_next(rec, root, env), rec)


# --- routed control: the floor never fires when actually routed -------------

class _Quiet(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def _fixture_handler():
    class _Handler(_Quiet):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(FIXTURE_BYTES)))
            self.end_headers()
            self.wfile.write(FIXTURE_BYTES)

    return _Handler


def test_routed_control_prints_local_and_haiku(tmp_path):
    root = _cfg_root(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _fixture_handler())
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        env = _env(url)
        decisions = tmp_path / "decisions.md"
        check_line = _run(CHECK, "check", "--decisions", str(decisions), "--scope", "run-start",
                          env=env)
        append_out = json.loads(_run(APPEND, "append", "--decisions", str(decisions),
                                     stdin=check_line, env=env))
        assert append_out["appended"] is True
        rec = tmp_path / "routed.json"
        out = json.loads(_run(
            LADDER, "start", "--task", TASK_ID, "--tier", "local", "--record", str(rec),
            "--route-from", str(decisions), "--root", str(root), env=env))
        assert out["tier"] == "local"
        assert out["model"] == "haiku"
        assert out["reason"] == "routed/ok"
        _render_and_assert_model(out, "haiku")
    finally:
        stopper = threading.Thread(target=lambda: (server.shutdown(), server.server_close()),
                                   daemon=True)
        stopper.start()
        stopper.join(2.0)
