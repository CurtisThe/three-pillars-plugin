"""task_scope_runner.py — runner resolution, the one runner argv builder and the runner call.

design: local-implement-and-review

Split out of `task_scope.py` by responsibility (file-size cap); `task_scope` re-exports
every public name here, so callers keep using `task_scope.resolve_runner` etc.

Stdlib only. `iteration_lane` and `repo_config_load` (in-repo) are imported lazily: the
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
# The status a repo whose `/tp-test-setup` recorded `test.runner: "other"` gets from
# Targets verification: its Targets are not node-targetable by the pytest argv builder.
NON_PYTEST_RUNNER = "unverified (non-pytest runner)"


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


def recorded_runner(root) -> str | None:
    """The recorded `test.runner` (`pytest` / `other`) from the repo config, else None."""
    shared = str(Path(__file__).resolve().parent)
    if shared not in sys.path:
        sys.path.insert(0, shared)
    import repo_config_load  # noqa: E402 — in-repo, imported lazily

    test = repo_config_load.load_repo_config(root).config.get("test")
    runner = test.get("runner") if isinstance(test, dict) else None
    return runner if isinstance(runner, str) else None


def _discover(root) -> str | None:
    shared = str(Path(__file__).resolve().parent)
    if shared not in sys.path:
        sys.path.insert(0, shared)
    import iteration_lane  # noqa: E402 — in-repo, imported lazily

    return iteration_lane.discover_test_command(root)


# The argv-safe command language (PR #170 r4 ruling): words of bare characters or quoted
# strings, split on ASCII space/tab. An allowlist, so a shell shape nobody listed fails
# closed instead of reaching pytest as literal arguments.
_QUOTED_CONTENT = r"""[^'"\\$`\n]*"""
_ARGV_WORD_RE = re.compile(rf"[A-Za-z0-9_./:=,@+%-]+|'{_QUOTED_CONTENT}'|\"{_QUOTED_CONTENT}\"")
_QUOTED_BANNED = frozenset("'\"\\$`\n")
_SEPARATORS = " \t"
NEEDS_SHELL = "runner-needs-shell"


def shell_token(command: str) -> str | None:
    """The first character outside the argv-safe language, else None.

    Accepted: words separated by ASCII space or tab, each wholly bare
    ``[A-Za-z0-9_./:=,@+%-]+`` or wholly one single- or double-quoted string whose content
    has no backslash, ``$``, backtick, quote or newline; the first word has no ``=`` (sh
    would read ``NAME=`` as an assignment). In that language no character is special to sh
    beyond word splitting and quote removal, so ``shlex.split`` (what `runner_argv` execs)
    equals sh word-splitting — the whole shell-shape class is closed by construction, not
    by a list of the shapes found so far. An unterminated quote is returned as itself."""
    i = 0
    while i < len(command):
        if command[i] in _SEPARATORS:
            i += 1
            continue
        word = _ARGV_WORD_RE.match(command, i)
        if word is None:
            quote = command[i]
            if quote not in "'\"":
                return quote
            return next((c for c in command[i + 1:] if c in _QUOTED_BANNED), quote)
        if "=" in word.group() and not command[:i].strip(_SEPARATORS):
            return "="
        i = word.end()
        if i < len(command) and command[i] not in _SEPARATORS:
            return command[i]
    return None


def _needs_shell(token: str, command: str) -> str:
    return f"{NEEDS_SHELL}: {token!r} in {command!r}"


def resolve_runner(root, override: str | None) -> tuple[str | None, str]:
    """``(runner, source)`` or ``(None, reason)``.

    Order: ``override`` (refused like a recorded command when it leaves the argv-safe
    language) → a recorded ``test.runner: "other"`` refuses with the status
    ``NON_PYTEST_RUNNER`` (the operator's declaration wins over every probe) → a
    pytest-shaped `iteration_lane.discover_test_command` — refused by name
    (``runner-needs-shell: '<char>' in <command>``) when it leaves the argv-safe language
    (`shell_token`) → the local pytest-config probe (so a Makefile ``test:`` or
    ``npm test`` repo with pytest config still resolves) → a non-pytest discovery refuses
    (``runner-not-node-targetable``) → ``no-runner``.
    """
    if override and override.strip():
        token = shell_token(override.strip())
        if token:  # the operator's command execs without a shell too
            return None, _needs_shell(token, override.strip())
        return override.strip(), "override"
    if recorded_runner(root) == "other":
        return None, NON_PYTEST_RUNNER
    discovered = _discover(root)
    if discovered and _PYTEST_SHAPED_RE.match(discovered):
        token = shell_token(discovered)
        if token:  # fail closed: never a silent substitute for the recorded command
            return None, _needs_shell(token, discovered)
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
# The interpreter's own `-m` failure (`/usr/bin/python3: No module named pytest`), never a
# test's quoted `ModuleNotFoundError: No module named 'x'` (a conftest's: the task's fault).
_MISSING_MODULE = re.compile(r"(?m)^\S*python[0-9.]*: (?:No module named ([\w.]+)|Error while "
                             r"finding module specification for '([\w.]+)')")


def runner_broken(rc, output, why=None) -> str | None:
    """Why the runner never started (an environment fault, never the task's), else None:
    rc 126/127, or a failed run with no junit report (``why == "no-report"``) where the
    interpreter itself says ``<python>: No module named <m>`` (``python3 -m pytest``
    without pytest). A test's or conftest's own ImportError is the task's, never matched."""
    if rc in RUNNER_BROKEN_RCS:
        return f"rc {rc}"
    hit = _MISSING_MODULE.search(output or "") if rc and why == "no-report" else None
    return f"No module named {hit.group(1) or hit.group(2)}" if hit else None


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
