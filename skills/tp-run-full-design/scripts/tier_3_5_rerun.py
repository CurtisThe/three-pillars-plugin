"""tier_3_5_rerun.py — the Tier 3.5 wrapper's side of the phase-test re-run.

design: local-implement-and-review

Split out of `run_tier_3_5.py` by responsibility (file-size cap). The wrapper owns the
call (`rerun_phase_tests.rerun_phase`, through the module attribute); this module owns
the stdin ``rerun`` contract, the ``test-results.json`` rewrite, and the informational
lines the wrapper self-logs to ``decisions.md``:

* ``rerun-skipped <reason>`` — the re-run did not run (no plan, no runner, env-broken…);
* ``rerun-phase-unverified <reason>`` — it ran but verified nothing (``nothing-verified``):
  recorded as ``status: unverified``, never a pass, never case f by itself;
* ``rerun-unverified <n> (<task:reason>, …)`` — nodes that ran but proved nothing;
* ``files-escape-logged <paths>`` — changed files no task lists (case g, log-only in v1).

A ``failed`` re-run is not self-logged here: the wrapper escalates it as case f
(``rerun-failed``, exit 2) and the orchestrator appends that line.
"""
from __future__ import annotations

import json
from pathlib import Path

from write_candidate_artifacts import _atomic_write

LOG_PREFIX = "[tp-run-full-design/tier-3.5]"
_UNVERIFIED = {"unverified", "rerun-skipped"}
# Phase statuses that are neither a pass nor case f: self-logged, exit 0.
_PHASE_TOKENS = {"skipped": "rerun-skipped", "unverified": "rerun-phase-unverified"}
_DETAIL_CHARS = 4000


def validate_rerun(payload: dict) -> dict:
    """The required stdin ``rerun`` object → ``{plan_path, phase, phase_base_sha,
    test_cmd}``. Raises KeyError / TypeError / ValueError (→ ``stdin-invalid``)."""
    if "rerun" not in payload:
        raise KeyError("rerun")
    rerun = payload["rerun"]
    if not isinstance(rerun, dict):
        raise TypeError(f"rerun must be an object (got {type(rerun).__name__})")
    for key in ("plan_path", "phase_base_sha"):
        if not isinstance(rerun.get(key), str) or not rerun[key].strip():
            raise ValueError(f"rerun.{key} must be a non-empty string")
    phase = rerun.get("phase")
    # Plans may start at `## Phase 0`; the plan grammar and phase_tasks accept it.
    if isinstance(phase, bool) or not isinstance(phase, int) or phase < 0:
        raise ValueError(f"rerun.phase must be a non-negative integer (got {phase!r})")
    test_cmd = rerun.get("test_cmd")
    if test_cmd is not None and not isinstance(test_cmd, str):
        raise TypeError("rerun.test_cmd must be a string when present")
    return {"plan_path": rerun["plan_path"].strip(), "phase": phase,
            "phase_base_sha": rerun["phase_base_sha"].strip(), "test_cmd": test_cmd}


def _counts(result: dict) -> dict:
    nodes = result.get("nodes") or []
    return {"passed": sum(n["status"] == "pass" for n in nodes),
            "failed": sum(n["status"] == "failed" for n in nodes),
            "unverified": sum(n["status"] in _UNVERIFIED for n in nodes)}


def _raw(result: dict) -> str:
    lines = [f"{n['task_id']} {n['spec']}: {n['status']}"
             + (f" ({n['reason']})" if n.get("reason") else "")
             for n in result.get("nodes") or []]
    if result.get("status") in _PHASE_TOKENS:
        token = _PHASE_TOKENS[result["status"]]
        lines.insert(0, f"{token} {result.get('reason', '')}".rstrip())
    tail = result.get("output_tail") or ""
    return "\n".join(lines) + (f"\n\n{tail}" if tail else "")


def log_lines(result: dict) -> list[str]:
    """The informational lines to self-log (never the case-f escalation line)."""
    lines = []
    if result.get("status") in _PHASE_TOKENS:
        token = _PHASE_TOKENS[result["status"]]
        lines.append(f"{LOG_PREFIX} {token} {result.get('reason') or 'unknown'}")
    unverified = [n for n in result.get("nodes") or [] if n["status"] in _UNVERIFIED]
    if unverified:
        detail = ", ".join(f"{n['task_id']}:{n.get('reason') or n['status']}"
                           for n in unverified)
        lines.append(f"{LOG_PREFIX} rerun-unverified {len(unverified)} ({detail})")
    if result.get("escaped_files"):
        lines.append(f"{LOG_PREFIX} files-escape-logged {' '.join(result['escaped_files'])}")
    return lines


def failure_detail(result: dict) -> str:
    """Case-f ``detail``: the failing nodes, then their output tails."""
    failing = [f"{n['task_id']}:{n['spec']} ({n.get('reason', '')})"
               for n in result.get("nodes") or [] if n["status"] == "failed"]
    text = f"rerun-failed {'; '.join(failing)}\n{result.get('output_tail') or ''}"
    return text[:_DETAIL_CHARS]


def apply_rerun(result: dict, self_reported: dict, cand_dir: Path,
                decisions_log: Path) -> str | None:
    """Rewrite ``test-results.json`` from the re-run and self-log the informational
    lines. Returns the case-f detail when the re-run failed, else None."""
    payload = {"source": "tier-3.5-rerun", "status": result.get("status"),
               **_counts(result), "raw": _raw(result), "self_reported": self_reported}
    _atomic_write(Path(cand_dir) / "test-results.json", json.dumps(payload, indent=2) + "\n")
    lines = log_lines(result)
    if lines:
        try:
            with open(decisions_log, "a", encoding="utf-8") as fh:
                fh.write("".join(f"{line}\n" for line in lines))
        except OSError:
            pass  # informational only; never turns an ok phase into a failure
    return failure_detail(result) if result.get("status") == "failed" else None
