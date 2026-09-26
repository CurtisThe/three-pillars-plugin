"""task_verify_gate.py — bind ``land`` to a PASS ``check`` of the exact commit it lands.

design: local-implement-and-review (impl-audit-1 #3)

``check`` records ``{verdict, checked_sha, rung}`` in the attempt's owner record (the
on-disk JSON ``task_attempts`` keeps under the git common dir). ``land`` refuses unless
the latest recorded verdict is ``PASS`` and the attempt's HEAD is still the commit that
was checked, so a land after a FAIL, an env-error or a post-check commit never lands
unverified code, whatever the prose dispatcher made of the exit codes.

``pre_exists_eligible`` bounds ``check``'s zero-commit PASS (impl-audit-2 #0). Split out
of ``task_verify.py`` to keep it under the file-size cap. Stdlib only.
"""
from __future__ import annotations

import json
import os

import task_attempts


def _on_disk(attempt: dict) -> dict | None:
    try:
        with open(task_attempts.record_path(attempt), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError, KeyError):
        return None


def head_of(attempt: dict) -> str:
    """The attempt's HEAD sha, or "" when the attempt dir is gone."""
    adir = str(attempt.get("attempt_dir") or "")
    if not adir or not os.path.isdir(adir):
        return ""
    res = task_attempts._git(adir, "rev-parse", "HEAD", check=False)
    return res.stdout.strip() if res.returncode == 0 else ""


def checked(attempt: dict, rung: str, verdict_fn) -> dict:
    """Run ``verdict_fn`` (``check``'s steps 1-6) and record its verdict against the HEAD
    sampled *before* it ran, the commit those steps verified (impl-audit-2 #6). A HEAD
    that moved during the check turns a PASS into FAIL ``moved-during-check``."""
    start = head_of(attempt)
    res = verdict_fn()
    if res.get("verdict") == "PASS" and head_of(attempt) != start:
        res.update(verdict="FAIL", exit=1, reason="moved-during-check", pre_exists=False)
    record_verdict(attempt, res, rung, checked_sha=start)
    return res


def record_verdict(attempt: dict, res: dict, rung: str, *,
                   checked_sha: str | None = None) -> None:
    """Write ``check``'s verdict into the owner record (and ``attempt``). A record that
    is gone (a discarded attempt) is never recreated."""
    sha = head_of(attempt) if checked_sha is None else checked_sha
    verdict = {"verdict": res.get("verdict"), "checked_sha": sha, "rung": rung}
    attempt["check"] = verdict
    rec = _on_disk(attempt)
    if rec is not None:
        task_attempts._write_record({**rec, "check": verdict})


def land_refusal(attempt: dict, sha: str) -> str | None:
    """Why ``land`` must refuse ``sha`` (the attempt's HEAD), or None to proceed."""
    rec = _on_disk(attempt) or {}
    check = rec.get("check") or attempt.get("check")
    if not check:
        return "not-checked"
    if check.get("verdict") != "PASS":
        return f"not-passed: {check.get('verdict')}"
    if not sha or check.get("checked_sha") != sha:
        return "moved-after-check"
    return None


def pre_exists_eligible(row: dict, rung: str, runnable: bool) -> bool:
    """A zero-commit attempt may PASS ``pre_exists`` only on the ``opus`` rung, for a
    runnable ``pytest-node`` Targets field naming at least one node (each must then exist
    and pass at base). A cheap rung, a file target or no runnable Targets → ``no commit``."""
    test = row.get("test") or {}
    return (rung == "opus" and runnable and test.get("kind") == "pytest-node"
            and bool(test.get("specs")))
