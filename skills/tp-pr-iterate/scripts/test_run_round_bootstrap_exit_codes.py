"""The state WRITE paths must fail closed — exit 2 + envelope, never exit 1.

`run_round.py` documents "exit 1 is NEVER used" (0 proceed / 2 escalate). Adding
`iterate_state.load_or_bootstrap()` put a *write* on the read path: it mkdirs and
creates a file, and those raise `OSError` subtypes that are NOT `StateReadError`.
Because `main()` has no top-level try and `__main__` is `sys.exit(main())`, an
unmapped one escaped as a traceback — exit 1 with NO envelope on stdout.

Scope: the **CLI exit-code contract** (subprocess level). The unit-level behaviour
of `iterate_state` itself — exclusivity, self-healing, write-back atomicity —
lives in `test_iterate_state_atomic_writes.py`.

Separate file because `test_run_round_cli.py` is at its 500-line cap
(CLAUDE.md §File Size Limits), the same reason `test_pr_iterate_state_contract_doc.py`
was split out.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
RUN_ROUND_PY = SCRIPTS_DIR / "run_round.py"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import iterate_state  # noqa: E402


# ---------- Running run_round.py, optionally with an injected failure ----------
#
# The mode-bit fixtures below are PRIVILEGE-DEPENDENT: under EUID 0 (any root
# Docker/CI container) CAP_DAC_OVERRIDE makes `chmod` a no-op, the bootstrap
# succeeds, and `assert rc == 2` fails. They are skipped for root — and an
# errno-INJECTION flavor is carried alongside so the centerpiece guard still
# EXECUTES as root instead of degrading to an all-skip.
#
# Injection needs a shim: run_round.py runs in a subprocess, so monkeypatch does
# not reach it. The shim imports the module and calls `main()` after patching.


def _write_shim(tmp_path: Path, preamble: str) -> Path:
    shim = tmp_path / "inject_shim.py"
    shim.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPTS_DIR)!r})\n"
        f"{preamble}\n"
        "import run_round\n"
        "sys.exit(run_round.main())\n",
        encoding="utf-8",
    )
    return shim


def _run(payload: dict, *, inject: str = "", tmp_path: Path | None = None):
    """Invoke run_round.py; return (rc, envelope-or-None, stdout, stderr)."""
    entry = _write_shim(tmp_path, inject) if inject else RUN_ROUND_PY
    result = subprocess.run(
        [sys.executable, str(entry)],
        input=json.dumps(payload).encode(),
        capture_output=True,
    )
    stdout = result.stdout.decode()
    try:
        envelope = json.loads(stdout.strip())
    except Exception:
        envelope = None
    return result.returncode, envelope, stdout, result.stderr.decode()


_INJECT_FSYNC_ENOSPC = """
import errno, os
def _no_space(fd):
    raise OSError(errno.ENOSPC, "No space left on device")
os.fsync = _no_space
"""

_INJECT_REPLACE_ENOSPC = """
import errno, os
def _no_space(src, dst):
    raise OSError(errno.ENOSPC, "No space left on device")
os.replace = _no_space
"""


# ---------- Fixtures for a state path whose bootstrap write CANNOT succeed ----------


def _unwritable_parent(tmp_path: Path):
    parent = tmp_path / "readonly"
    parent.mkdir()
    parent.chmod(0o500)
    return parent / "state.json", ""


def _parent_is_a_regular_file(tmp_path: Path):
    # mkdir(parents=True) raises FileExistsError here, not FileNotFoundError.
    # Privilege-INDEPENDENT: root cannot mkdir under a regular file either.
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("i am a file", encoding="utf-8")
    return blocker / "state.json", ""


def _unreadable_parent_dir(tmp_path: Path):
    """An EXISTING state file inside a non-traversable dir.

    `Path.exists()` itself raises PermissionError here — EACCES is not in pathlib's
    `_IGNORED_ERRNOS` — so even the *probe* has to be guarded, not just the write.
    """
    parent = tmp_path / "notraverse"
    parent.mkdir()
    (parent / "state.json").write_text("{}", encoding="utf-8")
    parent.chmod(0o000)
    return parent / "state.json", ""


def _seed_write_fails_enospc(tmp_path: Path):
    """A genuine out-of-space part-way through the seed write. UID-independent: an
    injected errno is not something CAP_DAC_OVERRIDE can wave away."""
    return tmp_path / "run" / "state.json", _INJECT_FSYNC_ENOSPC


_ROOT_SKIP = pytest.mark.skipif(
    os.geteuid() == 0,
    reason="chmod-synthesised failure is ineffective for root (CAP_DAC_OVERRIDE)",
)

_FLAVORS = [
    pytest.param(_unwritable_parent, id="unwritable-parent", marks=_ROOT_SKIP),
    pytest.param(_parent_is_a_regular_file, id="parent-is-a-regular-file"),
    pytest.param(_unreadable_parent_dir, id="probe-raises-eacces", marks=_ROOT_SKIP),
    pytest.param(_seed_write_fails_enospc, id="seed-write-enospc"),
]


@pytest.fixture
def failing_state_path(request, tmp_path):
    yield request.param(tmp_path)
    # Restore permissions so tmp_path cleanup can run.
    for d in (tmp_path / "readonly", tmp_path / "notraverse"):
        if d.exists():
            d.chmod(0o700)


@pytest.mark.parametrize("failing_state_path", _FLAVORS, indirect=True)
def test_run_round_cli_exit_1_never_used(failing_state_path, tmp_path):
    """A failing bootstrap escalates with a well-formed envelope — never exit 1.

    This is the restored exit-1 guard. It must exercise a FAILING write: a merely
    *absent* state path is not a guard, because `load_or_bootstrap` creates it with
    `mkdir(parents=True)` and the round exits 0, so `rc != 1` holds without any error
    path running (see the contrast test below).

    Mirrors test_state_bootstrap_siblings.py
    ::test_converge_cli_missing_config_exits_2_not_traceback.
    """
    path, inject = failing_state_path
    rc, env, stdout, stderr = _run(
        {"state_path": str(path), "head_sha": "h"}, inject=inject, tmp_path=tmp_path
    )

    assert "Traceback" not in stderr, (
        "a failing bootstrap must be mapped to an envelope, not escape as an "
        f"unhandled exception.\nstderr:\n{stderr}"
    )
    assert rc != 1, f"exit 1 must never be used by run_round.py; stdout={stdout!r}"
    assert rc == 2, f"a failing bootstrap must escalate; got {rc}: {stdout!r}"

    assert env is not None, f"exit 2 must still emit a JSON envelope; stdout={stdout!r}"
    assert env.get("status") == "escalate"
    assert env.get("event_token") == "state-write-failed", (
        "the pre-existing state-write-failed token is reused for a failure to "
        f"establish the state; got {env.get('event_token')!r}"
    )
    assert env.get("state_written") is False
    assert env.get("converged") is False
    assert env.get("detail"), "the envelope must carry the underlying OSError detail"


def test_absent_state_path_is_not_an_exit_1_guard(tmp_path):
    """Why the test above needs a failing write: absence exits 0.

    Pins the trivially-passing shape so it is not reintroduced as "the" exit-1 guard.
    """
    missing = tmp_path / "subdir_that_does_not_exist" / "x.json"
    rc, env, _, _ = _run({"state_path": str(missing), "head_sha": "h"})
    assert rc == 0, f"an absent state path is the bootstrap start condition; got {rc}"
    assert env.get("state_bootstrapped") is True


def test_an_unexpected_exception_escalates_instead_of_tracebacking(tmp_path):
    """The CLI boundary catches EVERYTHING — no per-exception-type hunt.

    A NUL byte in `state_path` is reachable straight from the JSON payload: it is a
    `str`, so the type check passes; `Path.exists()` answers False (pathlib swallows
    the ValueError); then `mkdir` raises `ValueError`, which is neither of the two
    exceptions the state block catches. Unmapped it escaped `sys.exit(main())` as a
    traceback — exit 1, empty stdout — breaking the documented "0 proceed / 2
    escalate, exit 1 is NEVER used" contract.

    Each earlier round found the NEXT unmapped type (OSError, then ValueError, then
    ImportError...). One test suffices now because `main()` catches BaseException:
    the contract is structurally true, not true one errno at a time.
    """
    rc, env, stdout, stderr = _run({"state_path": "run\x00/state.json",
                                    "head_sha": "h"})

    assert "Traceback" not in stderr, f"must not escape unhandled.\nstderr:\n{stderr}"
    assert rc != 1, f"exit 1 must never be used by run_round.py; stdout={stdout!r}"
    assert rc == 2, f"an unexpected exception must escalate; got {rc}: {stdout!r}"
    assert env is not None, f"exit 2 must still emit an envelope; stdout={stdout!r}"
    assert env.get("status") == "escalate"
    assert env.get("state_written") is False
    assert env.get("converged") is False
    assert env.get("detail"), "the envelope must carry the underlying exception detail"


# ---------- The per-round write-back is atomic too (not just the bootstrap) ----------


def _round_payload(state_file: Path) -> dict:
    return {
        "state_path": str(state_file),
        "head_sha": "abc1234",
        "codereview_findings": [],
        "reviewed": None,
        "unresolved_actionable": 0,
        "ci_rollup": [],
        "config": {"review": {"expects_copilot": False},
                   "ci": {"expects_github_checks": False}},
        "pr_url": "https://github.com/o/r/pull/1",
    }


def _existing_state(tmp_path: Path) -> Path:
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(iterate_state.fresh_state(now="2026-09-09T00:00:00+00:00"), indent=2),
        encoding="utf-8",
    )
    return state_file


def test_write_back_failure_escalates_with_an_envelope(tmp_path):
    """The write-back's OSError is mapped to state-write-failed / exit 2.

    Replaces the old chmod-0444 fixture, which no longer synthesises a failure (the
    write-back replaces the file rather than truncating it, so the file's own mode is
    not consulted) and was privilege-dependent besides. An injected errno is neither.
    """
    state_file = _existing_state(tmp_path)
    rc, env, stdout, stderr = _run(
        _round_payload(state_file), inject=_INJECT_REPLACE_ENOSPC, tmp_path=tmp_path
    )

    assert "Traceback" not in stderr, f"must not escape unhandled.\nstderr:\n{stderr}"
    assert rc == 2, f"expected exit 2 on write-back failure; got {rc}: {stdout!r}"
    assert env is not None and env.get("status") == "escalate"
    assert env.get("event_token") == "state-write-failed"


def test_write_back_leaves_the_prior_state_intact_on_failure(tmp_path):
    """Atomicity of the EVERY-round write site, not just the round-0 bootstrap.

    The plain truncating `open(state_path, "w")` this replaced left a truncated file
    when it failed mid-write — and truncated + never-overwrite is the permanent
    `state-read-failed` wedge the bootstrap exists to remove. Staging to a tmp and
    `os.replace`-ing means a failed write-back leaves the previous round's state
    byte-identical and the loop can simply retry.
    """
    state_file = _existing_state(tmp_path)
    before = state_file.read_bytes()

    _run(_round_payload(state_file), inject=_INJECT_REPLACE_ENOSPC, tmp_path=tmp_path)

    assert state_file.read_bytes() == before, (
        "a failed write-back must leave the prior state byte-identical — a truncated "
        "one wedges every later round against the never-overwrite invariant"
    )
    assert not [p for p in tmp_path.iterdir() if ".tmp." in p.name], (
        "the staged tmp file must be cleaned up even when the replace fails"
    )
