"""Tests for task_eligibility.py's route flags — the display-only `effective` key.

design: hybrid-routing-hardening (Task 3.5)

``--route JSON`` / ``--route-from PATH`` (mutually exclusive) label each row's
``effective`` tier through ``tier_ladder.route_label`` / ``route_floor`` / ``display``.
``tier`` and every other key stay unchanged; without either flag ``effective`` is never
added, so today's output is byte-identical. Every subprocess passes an explicit env
(``ANTHROPIC_BASE_URL`` popped) so results never depend on this session's own ambient
base URL.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_route_check  # noqa: E402 — in-repo, stdlib-only sibling
import local_route_log  # noqa: E402 — in-repo, stdlib-only sibling
import task_eligibility as te  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "task_eligibility.py"

RED = "Calling `f()` returns 2, not 1."

ROUTED = {"schema": "tp-local-route/v1", "state": "routed", "reason": "ok",
          "base_url": "http://127.0.0.1:3457", "checked_at": "2026-09-27T00:00:00Z"}
UNROUTED = {"schema": "tp-local-route/v1", "state": "unrouted", "reason": "no-base-url",
            "base_url": None, "checked_at": "2026-09-27T00:00:00Z"}


def _task(tid, title, *, files, targets, red=RED):
    lines = [f"### Task {tid}: {title}", f"**File**: {files}",
             f"**Targets**: {targets}", "**Test**: prose only, never parsed.",
             f"**Red**: {red}", "**Green**: implement it.", "**Done when**: node passes."]
    return "\n".join(lines) + "\n"


def _plan(*tasks, phase=1):
    return f"# P\n\n## Phase {phase}: Things\n\n" + "\n".join(tasks) + "\n"


def _env(**extra):
    """An explicit env with ``ANTHROPIC_BASE_URL`` popped, so results never depend on
    this session's own ambient base URL — extra keys (e.g. a routed URL) may be added."""
    env = dict(os.environ)
    env.pop("ANTHROPIC_BASE_URL", None)
    env.update(extra)
    return env


def _repo(tmp_path):
    """A minimal repo with one local-tier task, mirroring test_task_eligibility.py's
    ``_cli_repo`` fixture pattern."""
    root = tmp_path / "repo"
    for rel in ("pkg/a.py", "pkg/test_a.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("\n", encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    plan = root / "three-pillars-docs" / "tp-designs" / "d" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(_plan(
        _task("1.1", "local", files="`pkg/a.py`", targets="`pkg/test_a.py::test_x`"),
    ), encoding="utf-8")
    return root, plan


def _run(root, plan, *extra, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), str(plan), "--phase", "1",
                           "--root", str(root), *extra],
                          capture_output=True, text=True, cwd=str(root),
                          env=env if env is not None else _env())


def _by_id(rows):
    return {r["task_id"]: r for r in rows}


def test_route_unrouted_floors_effective(tmp_path):
    root, plan = _repo(tmp_path)
    proc = _run(root, plan, "--route", json.dumps(UNROUTED))
    assert proc.returncode == 0, proc.stderr
    rows = _by_id(json.loads(proc.stdout))
    assert rows["1.1"]["tier"] == "local"
    assert rows["1.1"]["effective"] == "local->sonnet: unrouted/no-base-url"


def test_route_routed_effective_stays_local(tmp_path):
    root, plan = _repo(tmp_path)
    proc = _run(root, plan, "--route", json.dumps(ROUTED))
    assert proc.returncode == 0, proc.stderr
    rows = _by_id(json.loads(proc.stdout))
    assert rows["1.1"]["tier"] == "local"
    assert rows["1.1"]["effective"] == "local"


def _decisions_with_routed_entry(tmp_path):
    base_url = local_route_check.redact_url("http://127.0.0.1:3457")
    result = {**ROUTED, "base_url": base_url, "ollama": None, "detail": ""}
    entry = local_route_log.render_entry(result, "run-start", "none")
    path = tmp_path / "decisions.md"
    path.write_text("# Decisions log — schema v1\n\n" + entry + "\n", encoding="utf-8")
    return path


def test_route_from_stale_when_env_unset(tmp_path):
    root, plan = _repo(tmp_path)
    decisions = _decisions_with_routed_entry(tmp_path)
    proc = _run(root, plan, "--route-from", str(decisions))
    assert proc.returncode == 0, proc.stderr
    rows = _by_id(json.loads(proc.stdout))
    assert rows["1.1"]["effective"] == "local->sonnet: stale-route"


def test_route_from_unreadable_path_is_missing_route(tmp_path):
    root, plan = _repo(tmp_path)
    missing = tmp_path / "does-not-exist.md"
    proc = _run(root, plan, "--route-from", str(missing))
    assert proc.returncode == 0, proc.stderr
    rows = _by_id(json.loads(proc.stdout))
    assert rows["1.1"]["effective"] == "local->sonnet: missing-route"


def test_no_flag_is_byte_identical(tmp_path):
    root, plan = _repo(tmp_path)
    proc = _run(root, plan)
    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert all("effective" not in r for r in rows)
    import task_scope  # noqa: PLC0415 — mirrors main()'s own resolution, local to this test
    runner, _reason = task_scope.resolve_runner(root, None)
    expected_rows = te.classify_phase(
        plan.read_text(encoding="utf-8"), 1, max_files=te.configured_max_files(root),
        runner_ok=runner is not None, exists=lambda p: (root / p).exists())
    expected = json.dumps(expected_rows, indent=2, sort_keys=True) + "\n"
    assert proc.stdout == expected


def test_route_and_route_from_together_is_usage_error(tmp_path):
    root, plan = _repo(tmp_path)
    decisions = tmp_path / "decisions.md"
    decisions.write_text("nothing routing-shaped here\n", encoding="utf-8")
    proc = _run(root, plan, "--route", json.dumps(ROUTED), "--route-from", str(decisions))
    assert proc.returncode == 2
