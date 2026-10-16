"""test_local_route_scale.py — the Task 2.5 `check` CLI at scale (B13):
8 concurrent `check --decisions` subprocesses (a thread pool, a 10 s per-call
timeout, no timing asserts) that must resolve per env and never write.

design: hybrid-routing-hardening (detailed-design.md §local_route_check →
`probe(url, budget_s)` and `CLI`; detailed-design.md §local_route_log.py →
"Stateless: writes nothing")

Half the children point `ANTHROPIC_BASE_URL` at the test server (routed),
half run with it unset (`unrouted/no-base-url`); each carries its own
decisions.md. Every result matches its own env; every decisions.md stays
byte-identical with its mtime unchanged; the tmp dirs gain no files. A
`check` run from a cwd outside the repo with the var removed parses as a
valid v1 `unrouted/no-base-url`. No inherited `ANTHROPIC_BASE_URL` — the
child envs are built explicitly so the real router is never probed.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import local_route_check  # noqa: E402

CLI = _SHARED / "local_route_check.py"
FIXTURE_BYTES = (_SHARED / "fixtures" / "tp_local_health_v1.json").read_bytes()
EXISTING = "# Decisions log — schema v1\n\nearlier run text\n"
N_CONCURRENT = 8


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(FIXTURE_BYTES)))
        self.end_headers()
        self.wfile.write(FIXTURE_BYTES)

    def log_message(self, *_args):
        pass


def _routed_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _stop(server):
    def _shutdown():
        server.shutdown()
        server.server_close()

    stopper = threading.Thread(target=_shutdown, daemon=True)
    stopper.start()
    stopper.join(2.0)


def _snapshot(path: Path) -> tuple[bytes, int, list[str]]:
    return (path.read_bytes(), path.stat().st_mtime_ns,
            sorted(os.listdir(path.parent)))


def _run_one(workdir: Path, base_url: str | None) -> dict:
    decisions = workdir / "decisions.md"
    before = _snapshot(decisions)
    env = dict(os.environ)
    if base_url is None:
        env.pop("ANTHROPIC_BASE_URL", None)
    else:
        env["ANTHROPIC_BASE_URL"] = base_url
    proc = subprocess.run(
        [sys.executable, "-I", str(CLI), "check",
         "--decisions", str(decisions), "--scope", "phase 1"],
        capture_output=True, text=True, timeout=10, env=env, cwd=workdir,
    )
    after = _snapshot(decisions)
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected one JSON line, got {proc.stdout!r}"
    out = json.loads(lines[0])
    assert out == json.loads(json.dumps(out))  # strictly JSON-serializable
    assert local_route_check.parse_result(out) is not None
    assert before == after, "the check --decisions path touched its decisions.md"
    return {"workdir": workdir, "base_url": base_url, "result": out}


def test_eight_concurrent_checks_resolve_per_env_and_write_nothing(tmp_path):
    server, url = _routed_server()
    try:
        workdirs = [tmp_path / f"work{i}" for i in range(N_CONCURRENT)]
        for i, workdir in enumerate(workdirs):
            workdir.mkdir()
            (workdir / "decisions.md").write_text(EXISTING, encoding="utf-8")
            (workdir / "notes.txt").write_text(f"notes {i}\n", encoding="utf-8")
        base_urls = [url] * (N_CONCURRENT // 2) + [None] * (N_CONCURRENT // 2)
        with concurrent.futures.ThreadPoolExecutor(max_workers=N_CONCURRENT) as pool:
            rows = list(pool.map(lambda pair: _run_one(*pair),
                                 zip(workdirs, base_urls)))
    finally:
        _stop(server)
    for row in rows:
        if row["base_url"] is None:
            assert row["result"]["state"] == "unrouted"
            assert row["result"]["reason"] == "no-base-url"
            assert row["result"]["base_url"] is None
        else:
            assert row["result"]["state"] == "routed"
            assert row["result"]["reason"] == "ok"
            assert row["result"]["base_url"] == row["base_url"]
    # the tmp dirs gain no files, even under the 8-way parallel run
    for workdir in workdirs:
        assert sorted(os.listdir(workdir)) == ["decisions.md", "notes.txt"], \
            f"the check path created files in {workdir}"


def test_check_from_outside_the_repo_with_var_removed(tmp_path):
    # the child runs under -I (isolated, no user site / user site-packages)
    # from a cwd outside the repo with ANTHROPIC_BASE_URL removed
    env = dict(os.environ)
    env.pop("ANTHROPIC_BASE_URL", None)
    proc = subprocess.run(
        [sys.executable, "-I", str(CLI), "check"],
        capture_output=True, text=True, timeout=10, env=env, cwd=tmp_path,
    )
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected one JSON line, got {proc.stdout!r}"
    out = json.loads(lines[0])
    assert out["state"] == "unrouted" and out["reason"] == "no-base-url"
    assert out["base_url"] is None
    assert local_route_check.parse_result(out) is not None
    assert sorted(os.listdir(tmp_path)) == []
