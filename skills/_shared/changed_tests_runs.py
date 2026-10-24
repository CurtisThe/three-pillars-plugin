"""changed_tests_runs.py — the head-bound "changed tests passed 3 consecutive runs" record.

design: fragile-test-prevention (detailed-design-stages.md Part C4; the `ci_local_stamp` pattern)

`record(root, base, head)` runs the test files that `base...head` adds or modifies, `runs`
times in a row, and writes one record bound to ``head``. It never runs in the caller's
checkout, which is often not at ``head`` (at ``two-stable`` the local log-flush commit leaves
the design worktree one unpushed commit ahead of the PR head, and a tracked edit may be in
flight): it runs in a temp ``git clone --shared`` detached at ``head`` outside the repo tree
(the `certify_scratch.pole_tree` pattern), removed in `finally`. A clone, not a linked worktree:
a linked one shares the caller's worktree registrations, so a changed test that reads them
(a worktree-isolation check, say) refuses while any tp/* worktree is live.
The tests see exactly ``head``'s tree, so a stale or dirty caller can never produce a pass for
``head``. A ``head`` that does not resolve or cannot be checked out writes nothing and returns
``{written: False, reason}``.

The verdict, in order: a non-pytest or absent runner (`task_scope.resolve_runner`, rooted at
the temp clone) is ``unverified`` with the runner's reason; else each run judges every
changed test file per node (`junit_verdict.run_judged`) and the first non-pass stops the loop
with ``fail``, except a file whose tests all skip (``unverified``/``skipped``: an opt-in tier),
which does not stop the loop. A timeout always stays ``fail``, even when its report shows every
test skipped, and so does a skip whose reason, read from the junit report's ``<skipped>``
elements and never from the output tail, says pytest could not import a module (a missing
dependency is an environment fault, not an opt-in tier: ``<file>: missing-dependency:
<module>``; a warning or a user-written reason that quotes the phrase stays a skip). A runner
that cannot start is ``unverified``. With no failure and at least one skipped file the verdict is
``unverified`` (``skipped (opt-in?): <files>``) and each run that held a skipped file reads
``unverified`` in ``runs``, never ``pass``; the predicate then applies ``fragility.strict``. No
changed test is ``pass`` with ``targets: []``. ``conftest.py`` is a changed test file but no run
target (it holds no tests).

The record is ``{schema, head, base, targets, runs, verdict, reason, at}`` in
``<git-dir>/three-pillars/fragility/runs.json``, the latest head only, written atomically.
`read(root, head)` returns it only for that head, else None. Like the ci-local stamp, the
record defends against drift, not forgery: anyone who can write the git dir can write a record.

CLI: ``record --base B --head H [--root D] [--runs N]`` prints the result as JSON and exits
0/1/2 = pass/fail/(unverified or not written); ``read --head H [--root D]`` prints the record
and exits 0, else prints ``null`` and exits 1. Stdlib plus the shipped helpers.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import fragility_ast
import junit_verdict
import run_scratch
import task_scope

SCHEMA = 1
RUNS = 3
TMP_PREFIX = "tp-runs-"
HEAD_UNAVAILABLE = "head not available"
BASE_UNAVAILABLE = "base not available"
CHANGED_UNAVAILABLE = "changed files not available"
# pytest's own `importorskip` reason, at the start of a `<skipped message>` (a skip raised in a
# test) or after `Skipped: ` in the body of a collection-time skip (`junit_verdict.skip_reasons`).
_IMPORT_SKIP = re.compile(r"(?:^|Skipped: )could not import '([^']+)'", re.MULTILINE)


class _Refused(Exception):
    """`record` cannot start: the message is the reason, and nothing is written."""


def _git(root, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          check=True, env=task_scope._git_env())


def _why(exc: Exception) -> str:
    lines = (getattr(exc, "stderr", None) or str(exc)).strip().splitlines()
    return lines[-1] if lines else type(exc).__name__


def _resolve(root, rev) -> str | None:
    """The commit oid ``rev`` names in ``root``, else None."""
    if not isinstance(rev, str) or not rev or rev.startswith("-"):
        return None
    try:
        return _git(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"
                    ).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def record_path(root) -> Path:
    """Where the record lives: under the git dir, never in the working tree."""
    git_dir = Path(_git(root, "rev-parse", "--git-dir").stdout.strip())
    if not git_dir.is_absolute():
        git_dir = (Path(root) / git_dir).resolve()
    return git_dir / "three-pillars" / "fragility" / "runs.json"


def changed_test_files(root, base, head, *, tree=None) -> list[str]:
    """Sorted repo-relative paths that ``base...head`` adds or modifies and the runner's own
    globs (`fragility_ast.is_test_file`, read from ``tree``, default ``root``) call tests."""
    out = _git(root, "diff", "--name-only", "--no-renames", "--diff-filter=AM", "-z",
               f"{base}...{head}", "--").stdout
    where = Path(tree or root)
    return sorted(p for p in out.split("\0") if p and fragility_ast.is_test_file(where / p))


@contextlib.contextmanager
def _detached(root, sha):
    """A ``--shared`` clone detached at ``sha`` under a fresh temp dir; always removed. Its
    objects come from ``root``'s store through alternates, so nothing is copied and nothing
    is registered in ``root``."""
    parent = tempfile.mkdtemp(prefix=TMP_PREFIX, dir=run_scratch.outside_tmpdir())
    path = os.path.join(parent, "wt")
    try:
        try:
            src = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"
                       ).stdout.strip()
            _git(parent, "clone", "--quiet", "--shared", "--no-checkout", src, path)
            _git(path, "remote", "remove", "origin")
            _git(path, "checkout", "--quiet", "--detach", sha)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise _Refused(f"{HEAD_UNAVAILABLE}: {_why(exc)}") from exc
        yield path
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def _judge(runner: str, wt: str, target: str, timeout: int):
    """One test file alone → ``(pass|red|missing|unverified, rc, reason, runner fault)``. An
    all-skipped file whose report says a module could not be imported reads
    ``missing-dependency: <module>`` (module docstring)."""
    def go(extra, one):
        rc, tail, _timed_out = task_scope.run_capture(
            task_scope.runner_argv(runner, [*one, *extra]), wt, timeout,
            env=task_scope._git_env(), tail_chars=2000)
        return rc, tail
    skips: list[str] = []
    (rc, tail), (kind, why) = junit_verdict.run_judged(go, target, wt, skipped_out=skips)
    fault = task_scope.runner_broken(rc, tail, why)
    missing = None
    if (kind, why) == ("unverified", "skipped"):
        missing = next((m for m in map(_IMPORT_SKIP.search, skips) if m), None)
    return kind, rc, f"missing-dependency: {missing.group(1)}" if missing else why, fault


def _execute(wt: str, runner: str, files, runs: int, timeout: int):
    """``runs`` passes over ``files`` → ``(per-run verdicts, verdict, reason)``."""
    results: list[str] = []
    skipped: list[str] = []
    for _ in range(runs):
        skipped_here = False
        for target in files:
            try:
                kind, rc, why, fault = _judge(runner, wt, target, timeout)
            except ValueError as exc:  # an unparseable runner command
                return results, "unverified", f"runner command unusable: {exc}"
            if fault:
                return results, "unverified", f"runner could not start: {fault}"
            # An opt-in tier, not a failure. A timeout (rc None) stays `fail` even when the junit
            # report, written before the exit hung, shows every node skipped.
            if kind == "unverified" and why == "skipped" and rc is not None:
                skipped_here = True
                if target not in skipped:
                    skipped.append(target)
                continue
            if kind != "pass":
                results.append("fail")
                return results, "fail", f"{target}: {'timeout' if rc is None else why or kind}"
        results.append("unverified" if skipped_here else "pass")
    if skipped:
        return results, "unverified", f"skipped (opt-in?): {', '.join(skipped)}"
    return results, "pass", ""


def _measure(root, wt: str, base: str, head: str, runs: int, timeout: int) -> dict:
    rec = {"schema": SCHEMA, "head": head, "base": base, "targets": [], "runs": [],
           "verdict": "pass", "reason": "",
           "at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds")}
    runner, why = task_scope.resolve_runner(wt, None)
    if not runner:
        return {**rec, "verdict": "unverified", "reason": why}
    try:
        changed = changed_test_files(root, base, head, tree=wt)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise _Refused(f"{CHANGED_UNAVAILABLE}: {_why(exc)}") from exc
    rec["targets"] = [p for p in changed if Path(p).name != "conftest.py"]
    if rec["targets"]:
        rec["runs"], rec["verdict"], rec["reason"] = _execute(
            wt, runner, rec["targets"], runs, timeout)
    return rec


def _write(root, rec: dict) -> None:
    """Atomic: a temp file beside the record, then `os.replace`."""
    path = record_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".runs-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def record(root, base, head, *, runs: int = RUNS, timeout: int = 600) -> dict:
    """Run the changed tests ``runs`` times at ``head`` (module docstring) → the record plus
    ``written: True``, or ``{written: False, reason}`` when nothing could be recorded."""
    if runs < 1:
        raise ValueError("runs must be at least 1")
    sha, base_sha = _resolve(root, head), _resolve(root, base)
    if sha is None:
        return {"written": False, "reason": f"{HEAD_UNAVAILABLE}: {head!r} is not a commit here"}
    if base_sha is None:
        return {"written": False, "reason": f"{BASE_UNAVAILABLE}: {base!r} is not a commit here"}
    try:
        with _detached(root, sha) as wt:
            rec = _measure(root, wt, base_sha, sha, runs, timeout)
    except _Refused as exc:
        return {"written": False, "reason": str(exc)}
    _write(root, rec)
    return {**rec, "written": True}


def read(root, head) -> dict | None:
    """The record, only when it is bound to ``head`` (an oid or any ref naming that commit);
    None when missing, unreadable, or for another head (the predicate reads "stale or missing")."""
    try:
        rec = json.loads(record_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None
    if not isinstance(rec, dict) or rec.get("schema") != SCHEMA:
        return None
    return rec if rec.get("head") == (_resolve(root, head) or head) else None


_EXIT = {"pass": 0, "fail": 1}


def main(argv: list[str] | None = None) -> int:
    """Exit codes in the module docstring."""
    ap = argparse.ArgumentParser(prog="changed_tests_runs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--base", required=True)
    rec.add_argument("--runs", type=int, default=RUNS)
    rd = sub.add_parser("read")
    for p in (rec, rd):
        p.add_argument("--head", required=True)
        p.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    if args.cmd == "read":
        found = read(args.root, args.head)
        print(json.dumps(found, indent=2))
        return 0 if found else 1
    try:
        out = record(args.root, args.base, args.head, runs=args.runs)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"changed_tests_runs: {_why(exc)}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return _EXIT.get(out.get("verdict"), 2) if out["written"] else 2


if __name__ == "__main__":
    sys.exit(main())
