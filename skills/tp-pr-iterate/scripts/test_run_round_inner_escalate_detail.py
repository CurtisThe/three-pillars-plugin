"""The INNER escalate sites cap `detail` too, not just the catch-all.

`_safe_detail` was added at the boundary handler and left the sites *inside* `_main`
formatting exceptions by hand (`f"{type(exc).__name__}: {exc}"`). Those are the sites
that actually fire: `run-round-failed` wraps `loop_driver.run_round`, which is where a
real round's work — and any exception it raises — happens. The 4 MB-message case
applies there verbatim: uncapped, a verbose exception becomes a multi-megabyte
`detail` field in the caller's context window, and an exception whose `__str__` raises
turns the mapped escalate into a traceback with no envelope at all.

Every escalate site in `run_round.py` now goes through `_safe_detail`. This module
pins the likeliest one end-to-end; the rest are the same one-line call.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent

_INJECT = """
import loop_driver

class Enormous(Exception):
    def __str__(self):
        return "Z" * 4_000_000

class Unrenderable(Exception):
    def __str__(self):
        raise RuntimeError("__str__ exploded")

def _boom(*a, **k):
    raise {exc}()

loop_driver.run_round = _boom
"""


def _run(tmp_path: Path, exc: str):
    shim = tmp_path / "inner_shim.py"
    shim.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPTS_DIR)!r})\n"
        "import run_round\n"
        + _INJECT.format(exc=exc)
        + "sys.exit(run_round.main())\n",
        encoding="utf-8",
    )
    payload = {
        "state": {"phase": "awaiting-review", "iteration": 0},
        "head_sha": "abc1234",
        "codereview_findings": [],
        "reviewed": None,
        "unresolved_actionable": 0,
        "ci_rollup": [],
        "config": {"review": {"expects_copilot": False},
                   "ci": {"expects_github_checks": False}},
    }
    proc = subprocess.run([sys.executable, str(shim)],
                          input=json.dumps(payload).encode(), capture_output=True)
    try:
        envelope = json.loads(proc.stdout.decode().strip())
    except Exception:
        envelope = None
    return proc.returncode, envelope, proc.stderr.decode(errors="replace")


def test_run_round_failed_caps_a_huge_exception_message(tmp_path):
    """A 4 MB message must not reach the caller whole from the inner site either."""
    rc, envelope, stderr = _run(tmp_path, "Enormous")

    assert rc == 2, f"stderr={stderr[-300:]!r}"
    assert envelope is not None and envelope["event_token"] == "run-round-failed"
    detail = envelope["detail"]
    assert len(detail) < 4096, (
        f"detail is {len(detail)} chars — uncapped, this site hands the caller the "
        "whole 4,000,006-char message"
    )
    assert "truncated from 4000000 chars" in detail, (
        f"the cut must be visible to a reader: {detail[-120:]!r}"
    )


def test_run_round_failed_survives_an_exception_that_cannot_be_rendered(tmp_path):
    """Formatting the exception is itself fallible — inside the `except` that maps it.

    Hand-formatted, an exception whose `__str__` raises replaced a mapped
    `run-round-failed` escalate with a chained traceback: rc from the boundary's
    catch-all, and no `run-round-failed` token for a caller to key on.
    """
    rc, envelope, stderr = _run(tmp_path, "Unrenderable")

    assert rc == 2, f"stderr={stderr[-300:]!r}"
    assert envelope is not None, f"an envelope is still owed; stderr={stderr[-300:]!r}"
    assert envelope["event_token"] == "run-round-failed", (
        "the round failure must keep its own token rather than degrading to the "
        f"catch-all's wrapper-failed: {envelope!r}"
    )
    assert envelope["detail"] == "Unrenderable", "the type name is the floor"
