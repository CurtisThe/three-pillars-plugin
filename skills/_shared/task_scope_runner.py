"""task_scope_runner.py — runner resolution, the one runner argv builder and the runner call.

design: local-implement-and-review

Split out of `task_scope.py` by responsibility (file-size cap); `task_scope` re-exports
every public name here, so callers keep using `task_scope.resolve_runner` etc.

Stdlib only. `iteration_lane` (in-repo) is imported lazily and never edited: the
pytest-config probe that runner resolution needs lives here, after its discovery.
"""
from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# `python3`, not `python`: a python3-only host has no `python`, and a missing runner
# would otherwise fail every task (impl-audit-1 #2). A discovered `python -m pytest` is
# rewritten only on such a host; where `python` exists it is the project's declared
# interpreter and is kept (impl-audit-2 #10).
_PYTEST_RUNNER = "python3 -m pytest"
_BARE_PYTHON_RE = re.compile(r"^python(?=\s+-m\s+pytest\b)")
_PYTEST_SHAPED_RE = re.compile(r"(?:python3?\s+-m\s+)?pytest\b")
# Runner resolution only: a file that makes the repo pytest-configured. Never read
# for addopts and never an input to a verdict (`junit_verdict` judges per node).
_RUNNER_CONFIG_MARKERS = (
    ("pytest.ini", None),
    ("pyproject.toml", "[tool.pytest"),
    ("tox.ini", "[pytest]"),
    ("setup.cfg", "[tool:pytest]"),
)


def pytest_config(root) -> bool:
    """True when ``root`` carries a pytest config file (runner resolution only)."""
    for name, marker in _RUNNER_CONFIG_MARKERS:
        try:
            path = Path(root) / name
            if path.is_file() and (marker is None
                                   or marker in path.read_text(encoding="utf-8")):
                return True
        except (OSError, UnicodeDecodeError):
            continue
    return False


def _discover(root) -> str | None:
    shared = str(Path(__file__).resolve().parent)
    if shared not in sys.path:
        sys.path.insert(0, shared)
    import iteration_lane  # noqa: E402 — in-repo, imported lazily

    return iteration_lane.discover_test_command(root)


def resolve_runner(root, override: str | None) -> tuple[str | None, str]:
    """``(runner, source)`` or ``(None, reason)``.

    Order: ``override`` → a pytest-shaped `iteration_lane.discover_test_command` → the
    local pytest-config probe (so a Makefile ``test:`` or ``npm test`` repo with pytest
    config still resolves) → a non-pytest discovery refuses (``runner-not-node-targetable``)
    → ``no-runner``.
    """
    if override and override.strip():
        return override.strip(), "override"
    discovered = _discover(root)
    if discovered and _PYTEST_SHAPED_RE.match(discovered):
        if shutil.which("python") is None:  # the project's `python`, unless there is none
            discovered = _BARE_PYTHON_RE.sub("python3", discovered)
        return discovered, "discovered"
    if pytest_config(root):
        return _PYTEST_RUNNER, "pytest-config"
    if discovered:
        return None, "runner-not-node-targetable"
    return None, "no-runner"


def runner_argv(runner: str, targets) -> list[str]:
    """The one command builder for task checks, red-at-base and every Tier 3.5 run:
    ``shlex.split(runner) + targets``. Nothing is inferred from the repo's config (xdist
    or not): a declared target's verdict is read per node from the ``--junitxml`` report
    each judged run appends (`junit_verdict.report_args`), never from the exit code."""
    return shlex.split(runner) + list(targets)


# --- The one runner call ------------------------------------------------------------

# Exit codes that mean the runner itself could not start (missing / not executable):
# an environment fault, never the task's red test.
RUNNER_BROKEN_RCS = frozenset({126, 127})


def _text(part) -> str:
    """A TimeoutExpired stream may be bytes even under ``text=True``."""
    if isinstance(part, (bytes, bytearray)):
        return part.decode(errors="replace")
    return part or ""


def run_capture(argv, cwd, timeout: int, *, env: dict, tail_chars: int):
    """Run ``argv`` in ``cwd`` → ``(rc, output tail, timed_out)``: the one helper
    ``task_verify check``, red-at-base and the Tier 3.5 re-run share. Never raises on
    a missing or non-executable runner: those map to 127 / 126
    (``RUNNER_BROKEN_RCS``); a timeout → ``(None, tail, True)``."""
    try:
        proc = subprocess.run(list(argv), cwd=str(cwd), capture_output=True, text=True,
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        out = "".join(_text(part) for part in (exc.stdout, exc.stderr))
        return None, out[-tail_chars:], True
    except FileNotFoundError as exc:
        return 127, str(exc), False
    except PermissionError as exc:
        return 126, str(exc), False
    return proc.returncode, (proc.stdout + proc.stderr)[-tail_chars:], False
