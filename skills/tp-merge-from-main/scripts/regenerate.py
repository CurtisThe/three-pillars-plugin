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

import subprocess
from dataclasses import dataclass
from pathlib import Path

# Success marker returned by `_run_checked`; distinct from a `(None, reason)` refusal so a call
# site can `if result is not _OK: return result`.
_OK = object()


@dataclass(frozen=True)
class Generator:
    """One declared generated file: its repo-relative `path`, the `write` argv that rebuilds it
    from the repo's current sources, and the optional `check` argv that must exit 0 afterwards."""
    path: str
    write: list[str]
    check: list[str] | None


def _argv_ok(value) -> bool:
    """`value` is a non-empty argv: a list of non-empty strings (and only strings)."""
    return (isinstance(value, list) and bool(value)
            and all(isinstance(x, str) and x for x in value))


def load_generators(config: dict) -> list[Generator]:
    """The well-formed `Generator` items of `config["merge_from_main"]["generators"]`, in order.
    Malformed items (not a dict, non-string `path`/`write`, non-argv `write`/`check`) are skipped;
    a config without the key returns `[]`."""
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
        gens.append(Generator(path=path, write=list(write),
                              check=list(check) if check is not None else None))
    return gens


def _has_conflict_brackets(text: str) -> bool:
    """Any line in `text` starting `<<<<<<<` (a surviving conflict marker of any width)."""
    return any(line.startswith("<<<<<<<") for line in text.splitlines())


def _run_checked(run, argv, cwd, label):
    """Run `argv` with `cwd`; `_OK` when it exits 0, else a `(None, reason)` refusal naming the
    `label` and the exit code. An exception from `run` is left to the caller's `except`."""
    result = run(argv, cwd=cwd)
    if getattr(result, "returncode", 0) != 0:
        return None, f"{label} command exited {result.returncode}"
    return _OK


def regenerate_file(repo, gen: Generator, ours_text: str, theirs_text: str,
                    run=subprocess.run) -> tuple[str | None, str]:
    """Rebuild `gen.path` from `ours_text` and from `theirs_text` and accept the result only when
    the two rebuilds give the same bytes, the run is idempotent, no conflict bracket survives, and
    the declared `check` (when any) exits 0. On acceptance the rebuilt text is left on disk at
    `repo/path` and the return is `(text, "")`; every failure is `(None, reason)` naming it. Never
    raises."""
    target = Path(repo) / gen.path
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(ours_text, encoding="utf-8")
        result = _run_checked(run, gen.write, repo, "write")
        if result is not _OK:
            return result
        r1 = target.read_text(encoding="utf-8")
        target.write_text(theirs_text, encoding="utf-8")
        result = _run_checked(run, gen.write, repo, "write")
        if result is not _OK:
            return result
        r2 = target.read_text(encoding="utf-8")
        if r1 != r2:
            return None, ("regenerated output differs between ours' and theirs' versions "
                          "(both sides' sources changed the generated content)")
        if _has_conflict_brackets(r1):
            return None, "regenerated output still holds a conflict bracket line"
        target.write_text(r1, encoding="utf-8")
        result = _run_checked(run, gen.write, repo, "write")
        if result is not _OK:
            return result
        r3 = target.read_text(encoding="utf-8")
        if r3 != r1:
            return None, "generator is not idempotent (a second run changed the output)"
        if gen.check is not None:
            result = _run_checked(run, gen.check, repo, "check")
            if result is not _OK:
                return result
        return r1, ""
    except Exception as exc:  # any failure is a refusal, never an exception out
        return None, f"generator failure: {type(exc).__name__}: {exc}"
