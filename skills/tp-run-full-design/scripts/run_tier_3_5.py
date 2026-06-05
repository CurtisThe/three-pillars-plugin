"""Tier 3.5 CLI wrapper — compose parse → write → cleanup → SHA-check.

Invoked by the tp-run-full-design orchestrator as
``python3 skills/tp-run-full-design/scripts/run_tier_3_5.py`` with a JSON
object on stdin. Emits a single-line JSON envelope on stdout and exits:

    0 — ok          (worker delivered a valid candidate, ls-remote SHA matches)
    1 — retry       (case c — schema-validation-error)
    2 — escalate    (case a — worker-noop, case b — no-candidate-block,
                     case e — sha-mismatch, or case=None for a
                     wrapper-internal failure with event_token
                     "stdin-invalid" / "invalid-worktree-path" /
                     "artifact-write-failed" / "cleanup-failed" /
                     "sha-check-failed" — exit 1 is RESERVED for case c
                     retry, so any uncaught helper exception or
                     contract-violating input must be mapped to
                     escalate.)

Per detailed-design §Interfaces, the wrapper's single source of truth for
``candidate_id`` is ``parsed["candidate_id"]`` extracted from the worker
response. The stdin top-level ``candidate_id`` is advisory routing
context only — never used for path construction or assertion. There is
no case (d): locked-worktree cleanup is an internal helper concern that
self-logs via ``[tp-run-full-design/tier-3.5] worktree-cleanup-locked``.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from parse_candidate_response import (  # noqa: E402
    NoCandidateBlockError,
    SchemaValidationError,
    UnknownSchemaVersionError,
    parse_candidate_response,
)
from write_candidate_artifacts import write_candidate_artifacts  # noqa: E402
from cleanup_worker_worktree import cleanup_worker_worktree  # noqa: E402


def _emit(envelope: dict, code: int) -> int:
    """Print the envelope as a single line and return the exit code."""
    sys.stdout.write(json.dumps(envelope) + "\n")
    return code


def _envelope(status: str, case: str | None, event_token: str, detail: str | None = None) -> dict:
    return {"status": status, "case": case, "event_token": event_token, "detail": detail}


def main() -> int:
    # Stdin parsing and required-key access can raise JSONDecodeError,
    # KeyError, or TypeError. Without a guard these exit 1 (Python
    # default), colliding with the case-(c) retry contract. Map to
    # escalate with event_token "stdin-invalid".
    try:
        payload = json.load(sys.stdin)
        # `worker_response` defaults to "" when the key is missing, but a
        # literal `null` in stdin lands as None (the `.get` default only
        # fires on missing keys) — coerce. A non-string value would crash
        # the parser later; reject with a typed error.
        worker_response = payload.get("worker_response", "")
        if worker_response is None:
            worker_response = ""
        if not isinstance(worker_response, str):
            raise TypeError(
                f"worker_response must be a string (got {type(worker_response).__name__})"
            )
        # `agent_meta` is REQUIRED per the contract — a missing key is a
        # stdin contract violation, NOT a worker failure (case a). Same
        # for non-dict values: case (a) is reserved for the orchestrator
        # explicitly signaling "worker didn't run" via a null/empty
        # worktreePath INSIDE agent_meta.
        if "agent_meta" not in payload:
            raise KeyError("agent_meta")
        agent_meta = payload["agent_meta"]
        if not isinstance(agent_meta, dict):
            raise TypeError(
                f"agent_meta must be an object (got {type(agent_meta).__name__})"
            )
        design_dir = Path(payload["design_dir"])
        slug = payload["slug"]
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        return _emit(
            _envelope(
                "escalate", None, "stdin-invalid",
                f"{type(exc).__name__}: {exc}",
            ),
            2,
        )

    # Case (a) requires `worktreePath` to be EXPLICITLY present in
    # agent_meta with a null or empty value (the orchestrator's signal
    # that the worker never produced a worktree). A missing key is a
    # stdin contract violation — the orchestrator failed to wire the
    # field — and gets event_token=stdin-invalid, not worker-noop.
    if "worktreePath" not in agent_meta:
        return _emit(
            _envelope(
                "escalate", None, "stdin-invalid",
                "agent_meta is missing required key 'worktreePath'",
            ),
            2,
        )
    worktree_value = agent_meta["worktreePath"]
    if worktree_value is None or worktree_value == "":
        return _emit(
            _envelope(
                "escalate", "a", "worker-noop",
                "agent_meta.worktreePath is null — worker never ran.",
            ),
            2,
        )
    # Non-string or non-absolute path is a contract violation that could
    # let `cleanup_worker_worktree` run `git worktree remove` against
    # the repo itself — escalate.
    if not isinstance(worktree_value, str) or not Path(worktree_value).is_absolute():
        return _emit(
            _envelope(
                "escalate", None, "invalid-worktree-path",
                f"agent_meta.worktreePath must be an absolute string path; "
                f"got {type(worktree_value).__name__} {worktree_value!r}",
            ),
            2,
        )

    # Cases (b) and (c) surface from the parser.
    try:
        parsed = parse_candidate_response(worker_response)
    except NoCandidateBlockError as exc:
        return _emit(
            _envelope("escalate", "b", "no-candidate-block", str(exc)),
            2,
        )
    except UnknownSchemaVersionError as exc:
        return _emit(
            _envelope("escalate", "b", "no-candidate-block", str(exc)),
            2,
        )
    except SchemaValidationError as exc:
        return _emit(
            _envelope("retry", "c", "schema-validation-error", str(exc)),
            1,
        )

    # Write the four candidate artifact files. Path is keyed off the
    # WORKER'S reported candidate_id, not the stdin top-level field.
    # Unhandled exceptions here would exit 1 (Python default), colliding
    # with the case-(c) retry contract. Map to escalate / exit 2.
    candidate_id = parsed["candidate_id"]
    if candidate_id in {".", ".."} or "/" in candidate_id or "\\" in candidate_id:
        return _emit(
            _envelope(
                "retry",
                "c",
                "schema-validation-error",
                f"candidate_id must be a simple path segment (got {candidate_id!r})",
            ),
            1,
        )
    try:
        write_candidate_artifacts(parsed=parsed, dir=design_dir, agent_meta=agent_meta)
    except Exception as exc:
        return _emit(
            _envelope(
                "escalate", None, "artifact-write-failed",
                f"{type(exc).__name__}: {exc}",
            ),
            2,
        )

    # Clean up the worker worktree. Locked worktrees self-log via the
    # helper; the wrapper never surfaces them as a case. A non-lock
    # failure (worktree gone, permission denied) must escalate, not retry.
    worktree_path = Path(agent_meta["worktreePath"])
    decisions_log = design_dir / "decisions.md"
    try:
        cleanup_worker_worktree(worktree_path=worktree_path, decisions_log=decisions_log)
    except Exception as exc:
        return _emit(
            _envelope(
                "escalate", None, "cleanup-failed",
                f"{type(exc).__name__}: {exc}",
            ),
            2,
        )

    # Case (e): SHA cross-check via git ls-remote. Subprocess, decode, and
    # parse failures all escalate — they are environmental, not case-(c)
    # retryable, and must not exit 1.
    parsed_candidate_id = parsed["candidate_id"]
    branch_ref = f"candidate/{slug}/{parsed_candidate_id}"
    try:
        result = subprocess.run(
            ["git", "ls-remote", "origin", branch_ref],
            capture_output=True,
            check=False,
        )
        # Non-zero returncode (auth, network, unknown remote) does not
        # raise but means we have no trustworthy SHA. Treat as
        # sha-check-failed, not sha-mismatch — operational failures
        # must not be misattributed to the worker.
        if result.returncode != 0:
            stderr = (
                result.stderr.decode()
                if isinstance(result.stderr, (bytes, bytearray))
                else (result.stderr or "")
            )
            return _emit(
                _envelope(
                    "escalate", None, "sha-check-failed",
                    f"git ls-remote origin {branch_ref} exited {result.returncode}: "
                    f"{stderr.strip()}",
                ),
                2,
            )
        remote_stdout = result.stdout.decode() if isinstance(result.stdout, (bytes, bytearray)) else (result.stdout or "")
        remote_sha = remote_stdout.split("\t", 1)[0].strip() if remote_stdout else ""
        parsed_sha = parsed["sha"]
    except Exception as exc:
        return _emit(
            _envelope(
                "escalate", None, "sha-check-failed",
                f"git ls-remote origin {branch_ref} raised {type(exc).__name__}: {exc}",
            ),
            2,
        )
    if remote_sha != parsed_sha:
        token = f"sha-mismatch {slug}:{parsed_sha}:{remote_sha}"
        detail = (
            f"git ls-remote origin {branch_ref} returned {remote_sha!r}; "
            f"worker reported {parsed_sha!r}"
        )
        return _emit(
            _envelope("escalate", "e", token, detail),
            2,
        )

    return _emit(_envelope("ok", None, "ok", None), 0)


if __name__ == "__main__":
    sys.exit(main())
