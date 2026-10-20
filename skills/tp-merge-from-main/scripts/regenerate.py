#!/usr/bin/env python3
"""Regenerate-and-verify for declared generated files (config `merge_from_main.generators`).

A generated file's content is derived from source files on both sides, so a text merge of it is
seldom right: ours' committed version and theirs' are usually both stale. The safe acceptance is
regeneration: rebuild the file from OURS' sources and from THEIRS' sources, and accept the result
only when both rebuilds give the same bytes. Because the rebuild starts from committed text, that
equality also means both sides' sources agree on the generated content — the only case where no
information is lost by discarding either side's hand-merged bytes.

Acceptance additionally requires:

* idempotence — regenerating the rebuilt output again must give no byte change (a generator that
  appends a timestamp on every run can never be trusted to have converged);
* no conflict bracket — any surviving `<<<<<<<` line in the output is refused;
* the declared `check` (when present) exits 0 on the accepted output.

`regenerate_file` never raises: any failure — a subprocess exiting non-zero, a subprocess that
raises (an `OSError` from a missing binary, a timeout, `CalledProcessError`, …) or any other
exception — is a `(None, reason)` refusal, and `reason` always names what happened.

`load_generators` reads `config["merge_from_main"]["generators"]` items shaped
`{"path": str, "write": [argv], "check": [argv] (optional)}`; malformed items are skipped and a
config without the key yields `[]`. Stdlib only.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Success marker returned by `_run_checked`; distinct from a `(None, reason)` refusal so a call
# site can `if result is not _OK: return result`.
_OK = object()

# The ceiling every generator run gets when its item declares no `timeout` of its own.
DEFAULT_TIMEOUT = 600


@dataclass(frozen=True)
class Generator:
    """One declared generated file: its repo-relative `path`, the `write` argv that rebuilds it
    from the repo's current sources, and the optional `check` argv that must exit 0 afterwards.
    The optional `timeout` (seconds, else `DEFAULT_TIMEOUT`), `inputs` (the repo-relative source
    files the rebuild reads) and `cwd` (the repo-relative directory the argv runs in) are
    defaulted, so items declared before those keys existed still construct."""
    path: str
    write: list[str]
    check: list[str] | None
    timeout: int | None = None
    inputs: tuple[str, ...] = ()
    cwd: str | None = None


def _argv_ok(value) -> bool:
    """`value` is a non-empty argv: a list of non-empty strings (and only strings)."""
    return (isinstance(value, list) and bool(value)
            and all(isinstance(x, str) and x for x in value))


def _timeout_ok(value) -> bool:
    """`value` is a positive int of seconds. `bool` is refused: `True` reads as a declaration
    nobody meant, and a 1-second generator is never what a config intends."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _inputs_ok(value) -> bool:
    """`value` is the declared source list: a list of non-empty strings (a bare string is a
    malformed list, not a one-element one)."""
    return isinstance(value, list) and all(isinstance(x, str) and x for x in value)


def _cwd_ok(value) -> bool:
    """`value` is a repo-relative directory: non-empty, not absolute, and holding no `..`
    segment, so the run cannot escape the repo it is merging in."""
    return (isinstance(value, str) and bool(value) and not value.startswith(("/", os.sep))
            and ".." not in value.split("/"))


def load_generators(config: dict) -> list[Generator]:
    """The well-formed `Generator` items of `config["merge_from_main"]["generators"]`, in order.
    Malformed items (not a dict, non-string `path`/`write`, non-argv `write`/`check`, a `timeout`
    that is not a positive int, `inputs` that is not a list of non-empty strings, a `cwd` that is
    empty/absolute/holds a `..` segment) are skipped; a config without the key returns `[]`."""
    items = config.get("merge_from_main", {}).get("generators", []) if isinstance(config, dict) else []
    if not isinstance(items, list):
        return []
    gens: list[Generator] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        path, write, check = item.get("path"), item.get("write"), item.get("check", None)
        if not isinstance(path, str) or not path or not _argv_ok(write):
            continue
        if check is not None and not _argv_ok(check):
            continue
        timeout, inputs, cwd = (item.get("timeout", None), item.get("inputs", None),
                               item.get("cwd", None))
        if timeout is not None and not _timeout_ok(timeout):
            continue
        if inputs is not None and not _inputs_ok(inputs):
            continue
        if cwd is not None and not _cwd_ok(cwd):
            continue
        gens.append(Generator(path=path, write=list(write),
                              check=list(check) if check is not None else None,
                              timeout=timeout,
                              inputs=tuple(inputs) if inputs is not None else (),
                              cwd=cwd))
    return gens


def _has_conflict_brackets(text: str) -> bool:
    """Any line in `text` starting `<<<<<<<` (a surviving conflict marker of any width)."""
    return any(line.startswith("<<<<<<<") for line in text.splitlines())


def input_conflict(gen: Generator, conflicted) -> str | None:
    """`input <path> is still conflicted` for the first (sorted) of `gen.inputs` that is also in
    `conflicted`, else None. A declared input still holding conflict markers means the rebuild
    would start from broken sources, so the whole regeneration must defer."""
    conflicted_set = set(conflicted or ())
    for src in sorted(gen.inputs or ()):
        if src in conflicted_set:
            return f"input {src} is still conflicted"
    return None


def _run_checked(run, argv, cwd, label, timeout):
    """Run `argv` in `cwd` with `timeout` and its output captured; `_OK` when it exits 0, else a
    `(None, reason)` refusal naming the `label` and the exit code. A `TimeoutExpired` becomes
    `<label> command timed out after <timeout>s`, a `FileNotFoundError` names the missing
    binary; any other exception is left to the caller's `except`."""
    try:
        result = run(argv, cwd=cwd, timeout=timeout, capture_output=True)
    except subprocess.TimeoutExpired:
        return None, f"{label} command timed out after {timeout}s"
    except FileNotFoundError:
        return None, f"{argv[0]} not found"
    if getattr(result, "returncode", 0) != 0:
        return None, f"{label} command exited {result.returncode}"
    return _OK


def regenerate_file(repo, gen: Generator, ours_text: str, theirs_text: str,
                    run=subprocess.run, conflicted=()) -> tuple[str | None, str]:
    """Rebuild `gen.path` from `ours_text` and from `theirs_text` and accept the result only when
    no declared input is still conflicted, the two rebuilds give the same bytes, the run is
    idempotent, no conflict bracket survives, and the declared `check` (when any) exits 0. Each run
    happens in `repo/gen.cwd` with `timeout=gen.timeout or DEFAULT_TIMEOUT` and captured output.
    On acceptance the rebuilt text is left on disk at `repo/path` and the return is `(text, "")`;
    every failure - including a conflicted input, a timeout or a missing binary - is a
    `(None, reason)` naming it, checked BEFORE anything is written. Never raises."""
    conflict = input_conflict(gen, conflicted)
    if conflict:
        return None, conflict
    if gen.cwd and not (Path(repo) / gen.cwd).is_dir():
        return None, f"cwd {gen.cwd} does not exist"
    target = Path(repo) / gen.path
    cwd = Path(repo) / (gen.cwd or "")
    timeout = gen.timeout or DEFAULT_TIMEOUT
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(ours_text, encoding="utf-8")
        result = _run_checked(run, gen.write, cwd, "write", timeout)
        if result is not _OK:
            return result
        r1 = target.read_text(encoding="utf-8")
        target.write_text(theirs_text, encoding="utf-8")
        result = _run_checked(run, gen.write, cwd, "write", timeout)
        if result is not _OK:
            return result
        r2 = target.read_text(encoding="utf-8")
        if r1 != r2:
            return None, ("regenerated output differs between ours' and theirs' versions "
                          "(both sides' sources changed the generated content)")
        if _has_conflict_brackets(r1):
            return None, "regenerated output still holds a conflict bracket line"
        target.write_text(r1, encoding="utf-8")
        result = _run_checked(run, gen.write, cwd, "write", timeout)
        if result is not _OK:
            return result
        r3 = target.read_text(encoding="utf-8")
        if r3 != r1:
            return None, "generator is not idempotent (a second run changed the output)"
        if gen.check is not None:
            result = _run_checked(run, gen.check, cwd, "check", timeout)
            if result is not _OK:
                return result
        return r1, ""
    except Exception as exc:  # any failure is a refusal, never an exception out
        return None, f"generator failure: {type(exc).__name__}: {exc}"
