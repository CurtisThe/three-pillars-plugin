"""argv_runner — run an argv list (never a shell) with a timeout.

design: audit-pass-does-not-bind (Task 1.1); lifted from
`skills/tp-pr-iterate/scripts/reproduce.py` (`_run` / `_tail`).

`run_argv` returns a `RunResult`: `rc` is the exit code, or `None` when the run
itself failed (timeout, OSError) -- a caller treats that as inconclusive, never
as a pass. `tail` is the last `OUTPUT_CAP` chars of stdout+stderr (evidence);
`output` keeps the full text (parsers need it). `env` is forwarded to the runner
only when set, so fakes without an `env` parameter keep working.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

OUTPUT_CAP = 500


@dataclass(frozen=True)
class RunResult:
    rc: int | None
    stdout: str
    tail: str
    output: str = ""


def _join(*parts) -> str:
    return "\n".join(str(p) for p in parts if p)


def tail(*parts) -> str:
    """The non-empty parts joined by newlines, capped to the last OUTPUT_CAP chars."""
    return _join(*parts)[-OUTPUT_CAP:]


def _result(rc, stdout, *parts) -> RunResult:
    output = _join(*parts)
    return RunResult(rc, stdout, output[-OUTPUT_CAP:], output)


def run_argv(argv, *, cwd, timeout, env=None, runner=subprocess.run) -> RunResult:
    """Run `argv` (a list) in `cwd`; see the module docstring for the result."""
    if not isinstance(argv, list):
        raise TypeError(f"argv must be a list, not {type(argv).__name__}")
    kwargs = {"cwd": str(cwd), "capture_output": True, "text": True, "timeout": timeout}
    if env is not None:
        kwargs["env"] = env
    try:
        proc = runner(argv, **kwargs)
    except subprocess.TimeoutExpired as exc:
        return _result(None, "", f"timeout after {timeout}s", exc.stdout, exc.stderr)
    except OSError as exc:
        return _result(None, "", f"could not run: {exc}")
    return _result(proc.returncode, str(proc.stdout or ""), proc.stdout, proc.stderr)
