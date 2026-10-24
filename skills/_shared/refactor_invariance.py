"""refactor_invariance.py — would a phase's tests survive a refactor that keeps behaviour?

design: fragile-test-prevention (detailed-design-stages.md Part C3, Behavior 5)

A test that fails after a behaviour-preserving edit of a file it does not name pins the
file's shape (wrapping, section order, layout), not its behaviour. `run` replays each
transform of `REGISTRY` over the phase's changed files in a detached scratch worktree of
HEAD (outside the repo tree, always removed in `finally`) and re-runs the Targets that
were green before the edit: (1) the baseline runs each Targets node alone
(`task_scope.runner_argv`, judged per node from its junit report by
`junit_verdict.run_judged`) — a node not green there is skipped (``red at baseline``)
and never judged; (2) per transform, reset the worktree, apply it to the eligible files,
re-run the baseline-green nodes — a node that passed and now fails is ``over-specified``
under that transform; (3) eligible files are the changed files that are not Targets
files, not test modules, not under ``three-pillars-docs/tp-designs/`` and match the
transform's suffix — a transform with no eligible file (or one that changes nothing) is
skipped.

The result is ``{verdict, baseline, over_specified, skipped, transformed, errors,
reason}``. The verdict is ``over-specified`` when any node was flagged; else
``could-not-evaluate`` when nothing could be judged (no runner, a scratch-worktree
failure, a runner that never started, a transform that raised on a file, a node neither
passing nor failing under a transform); else ``clean``. A reviewer may refute an
over-specified node by citing the spec clause that makes the moved property meaningful.
Stdlib plus the shipped helpers.

CLI: ``--plan P --phase N [--base REF] [--root DIR] [--json]``. Targets come from the
plan (`task_scope.phase_tasks` + `task_targets.parse_targets`); changed files are ``git
diff --name-only <base>..HEAD``. A missing ``--base`` falls back to `default_branch.
default_ref`. Exit 0/1/2 = clean/over-specified/could-not-evaluate.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, NamedTuple

import default_branch
import fragility_ast
import junit_verdict
import md_transforms
import run_scratch
import task_scope
import task_targets

DESIGNS_PREFIX = "three-pillars-docs/tp-designs/"
NO_ELIGIBLE = "no eligible file"
NO_CHANGE = "transform changed nothing"
NO_TARGETS = "no targets"
NO_GREEN = "no node green at baseline"
RED_AT_BASELINE = "red at baseline"

class Transform(NamedTuple):
    """``apply`` maps a file's text to its transformed text; ``suffix`` picks the files."""
    suffix: str
    apply: Callable[[str], str]

def _reflow(text: str) -> str:
    widest = max((len(line) for line in text.split("\n")), default=0)
    return md_transforms.reflow(text, min(widest + 17, 40))

# tp-allow-fragile: PEP 263 fixes this cookie grammar; it runs over source lines, never prose
_CODING = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+")

def _unparse(src: str) -> str:
    """``ast.unparse(ast.parse(src))``, with a leading shebang and a PEP 263 encoding line
    (the first two lines) put back verbatim; other comments and layout are normalised."""
    keep = []
    for i, line in enumerate(src.splitlines(keepends=True)[:2]):
        if (i == 0 and line.startswith("#!")) or _CODING.match(line):
            keep.append(line if line.endswith("\n") else line + "\n")
        elif line.strip() and not line.lstrip().startswith("#"):
            break
    body = ast.unparse(ast.parse(src))
    return "".join(keep) + body + ("\n" if body else "")

REGISTRY = {
    "md-reflow": Transform(".md", _reflow),
    "md-reorder": Transform(".md", md_transforms.reorder_sections),
    "py-unparse": Transform(".py", _unparse),
}

class _Abort(Exception):
    """Nothing further can be judged: the message is the result's ``reason``."""

def _git(cwd, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          check=check, env=task_scope._git_env())

@contextlib.contextmanager
def _scratch(root):
    """A detached worktree of HEAD under a fresh temp dir; always removed."""
    parent = tempfile.mkdtemp(prefix="tp-invariance-", dir=run_scratch.outside_tmpdir())
    path = os.path.join(parent, "wt")
    try:
        _git(root, "worktree", "add", "--detach", "--quiet", path, "HEAD")
        yield path
    finally:
        with contextlib.suppress(OSError):
            _git(root, "worktree", "remove", "--force", "--force", path, check=False)
            _git(root, "worktree", "prune", check=False)
        shutil.rmtree(parent, ignore_errors=True)

def _rel(path: str) -> str | None:
    """A repo-relative posix path, or None when it is empty, absolute or climbs out."""
    rel = posixpath.normpath(task_scope.norm_path(str(path))) if str(path).strip() else ""
    return None if rel in ("", ".") or rel.startswith(("/", "../")) or rel == ".." else rel

def _eligible(wt: str, changed, suffix: str, target_files: set) -> list[str]:
    """Step 4: the changed files this transform may rewrite."""
    home = os.path.realpath(wt) + os.sep
    files: list[str] = []
    for raw in changed:
        rel = _rel(raw)
        full = os.path.join(wt, rel or "")
        if (rel is None or rel in files or not rel.endswith(suffix) or rel in target_files
                or rel.startswith(DESIGNS_PREFIX) or not os.path.isfile(full)
                or not os.path.realpath(full).startswith(home)
                or fragility_ast.is_test_file(full)):
            continue
        files.append(rel)
    return files

def _judge(runner: str, wt: str, target: str, timeout: int) -> tuple[str, int | None, str]:
    """One node alone → ``(pass|red|missing|unverified, rc, reason)``."""
    def go(extra, one):
        rc, tail, _timed_out = task_scope.run_capture(
            task_scope.runner_argv(runner, [*one, *extra]), wt, timeout,
            env=task_scope._git_env(), tail_chars=2000)
        return rc, tail
    try:
        (rc, tail), (kind, why) = junit_verdict.run_judged(go, target, wt)
    except ValueError as exc:  # an unparseable runner command
        raise _Abort(f"runner command unusable: {exc}") from exc
    broken = task_scope.runner_broken(rc, tail, why)
    if broken:
        raise _Abort(f"runner could not start: {broken}")
    return kind, rc, why

def _baseline(out: dict, wt: str, targets, runner: str, timeout: int) -> list[str]:
    """Step 2: the baseline-green nodes; the rest are skipped, never judged."""
    green = []
    for target in targets:
        kind, rc, why = _judge(runner, wt, target, timeout)
        out["baseline"][target] = kind
        if kind == "pass":
            green.append(target)
        else:
            reason = RED_AT_BASELINE if kind == "red" else \
                f"not green at baseline ({'timeout' if rc is None else why or kind})"
            out["skipped"].append({"node": target, "reason": reason})
    return green

def _apply(out: dict, wt: str, name: str, transform: Transform, files: list[str]) -> bool:
    """Rewrite the eligible files; False (recorded) when one raised or none changed."""
    changed = False
    for rel in files:
        path = os.path.join(wt, rel)
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                before = fh.read()
            after = transform.apply(before)
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(after)
        except Exception as exc:  # noqa: BLE001 — a plug-in transform may raise anything
            out["errors"].append({"transform": name, "file": rel,
                                  "error": f"{type(exc).__name__}: {exc}"})
            return False
        changed = changed or after != before
    if not changed:
        out["skipped"].append({"transform": name, "reason": NO_CHANGE})
    return changed

def _evaluate(out: dict, wt: str, targets, changed, runner: str, transforms, timeout: int):
    target_files = {_rel(t.partition("::")[0]) for t in targets}
    plan = {}
    for name, transform in transforms.items():
        files = _eligible(wt, changed, transform.suffix, target_files)
        if files:
            plan[name] = out["transformed"][name] = files
        else:
            out["skipped"].append({"transform": name, "reason": NO_ELIGIBLE})
    if not plan:
        return
    green = _baseline(out, wt, targets, runner, timeout)
    if not green:
        out["skipped"].extend({"transform": name, "reason": NO_GREEN} for name in plan)
        return
    for name, files in plan.items():
        _git(wt, "reset", "--hard", "--quiet", "HEAD")
        _git(wt, "clean", "-fdxq")
        if not _apply(out, wt, name, transforms[name], files):
            continue
        for target in green:
            kind, rc, why = _judge(runner, wt, target, timeout)
            if kind == "red":
                out["over_specified"].append({"node": target, "transform": name})
            elif kind != "pass":  # neither green nor red under the edit: undecided
                out["errors"].append({"transform": name, "node": target, "error":
                                      f"{'timeout' if rc is None else kind}: {why}"})

def _finish(out: dict) -> dict:
    if out["over_specified"]:
        out["verdict"] = "over-specified"
    elif out["errors"] or out["reason"]:
        out["verdict"] = "could-not-evaluate"
        if not out["reason"]:
            out["reason"] = "; ".join(
                f"{e['transform']} on {e.get('file') or e.get('node')}: {e['error']}"
                for e in out["errors"])
    return out

def run(root, targets, changed_files, *, runner, transforms=REGISTRY, timeout: int = 600):
    """The Part C3 invariance check over ``targets`` (pytest nodes, relative to ``root``)
    and the phase's ``changed_files`` (module docstring); ``runner`` is the test command
    (``task_scope.resolve_runner``), None when there is none."""
    out = {"verdict": "clean", "baseline": {}, "over_specified": [], "skipped": [],
           "transformed": {}, "errors": [], "reason": ""}
    targets = list(dict.fromkeys(targets))
    if not runner or not runner.strip():
        out["reason"] = "no runner"
        return _finish(out)
    if not targets:
        out["skipped"].append({"reason": NO_TARGETS})
        return out
    try:
        with _scratch(root) as wt:
            _evaluate(out, wt, targets, changed_files, runner.strip(), transforms, timeout)
    except _Abort as exc:
        out["reason"] = str(exc)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        out["reason"] = f"scratch worktree failed: {str(detail).strip()[-300:]}"
    return _finish(out)

_EXIT = {"clean": 0, "over-specified": 1, "could-not-evaluate": 2}

def _phase_targets(plan_path: str, phase: int) -> list[str]:
    """Every task's pytest specs in ``phase``, deduplicated (`task_scope.phase_tasks` +
    `task_targets.parse_targets`; non-runnable tasks contribute none)."""
    text = Path(plan_path).read_text(encoding="utf-8")
    specs = [spec for task in task_scope.phase_tasks(text, phase)
             for spec in task_targets.parse_targets(task["fields"].get("Targets"))["specs"]]
    return sorted(dict.fromkeys(specs))

def _cli_error(msg: str) -> int:
    print(f"refactor_invariance: {msg}", file=sys.stderr)
    return 2

def main(argv: list[str] | None = None) -> int:
    """Exit 0/1/2 = clean/over-specified/could-not-evaluate (module docstring)."""
    ap = argparse.ArgumentParser(prog="refactor_invariance")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--phase", type=int, required=True)
    ap.add_argument("--base", help="default: the repo's resolved default branch")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    base = args.base or default_branch.default_ref(args.root)
    if not base:
        return _cli_error("no --base given and the default branch could not be resolved")
    try:
        targets = _phase_targets(args.plan, args.phase)
    except OSError as exc:
        return _cli_error(str(exc))
    try:
        diff = _git(args.root, "diff", "--name-only", f"{base}..HEAD")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or str(exc)).strip().splitlines()
        return _cli_error(f"bad base {base!r}: {detail[0] if detail else exc}")
    changed = [line for line in diff.stdout.splitlines() if line]
    runner, _why = task_scope.resolve_runner(args.root, None)
    result = run(args.root, targets, changed, runner=runner)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['verdict']}: {result['reason'] or len(result['over_specified'])}")
    return _EXIT[result["verdict"]]

if __name__ == "__main__":
    sys.exit(main())
