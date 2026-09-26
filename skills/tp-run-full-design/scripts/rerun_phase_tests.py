"""rerun_phase_tests.py — Tier 3.5 re-run of one plan phase's Tests at the candidate SHA.

design: local-implement-and-review

The worker's ``test_results`` are self-reported; this module re-runs the phase's
declared Targets itself, in a throwaway scratch worktree checked out at the candidate
SHA, and reports a mechanical verdict the Tier 3.5 wrapper (`run_tier_3_5.py`) maps
onto its exit contract.

* **Plan revision** — the plan is read at the SHA (``git show <sha>:<plan_path>``), so
  statuses the worker wrote on the candidate branch are honoured. Absent → skipped.
* **Targets** — each task runs exactly its declared **Targets** (`task_scope.parse_targets`);
  a task without a valid field is non-canonical: ``unverified``, never case f.
* **Runner gate** — `task_scope.resolve_runner`; no runner → skipped, nothing runs and
  no scratch is created. A ``phase_base_sha`` that does not resolve to a commit (after
  one best-effort fetch) → skipped ``base-unresolved``, never a silent ``env-broken``.
* **Scratch** — a *named* throwaway branch ``tp-rerun/<slug>-<sha8>-<nonce>`` (a detached
  HEAD breaks ``git symbolic-ref``, M23) in ``<repo>/.claude/worktrees/tp-rerun-…``
  (the isolation-guard placement), removed, pruned and branch-deleted in ``finally`` on
  every path, including an exception.
* **Verdict** — **one pytest run per declared target** (amendment A31: the task run,
  the confirm and the control), each judged per node from its own ``--junitxml`` report
  (`junit_verdict`, amendments A29–A31), matched by the report's ``file`` under the
  rootdir pytest itself chose, never from the exit code: no or a malformed report, or
  no rootdir it fits → ``unverified``; a declared node absent from the report
  (``node-absent``) or a declared file with no testcase (``file-no-tests``) →
  ``unverified``, never case f (the repo's config may deselect it).
* **Case f** — only from a declared target: an f-candidate (``red``,
  ``collection-error``, or a ``Done`` task's declared file absent at the SHA:
  ``test-file-absent``, design.md Behavior 10 "missing at that SHA") escalates only
  after a *confirm* re-run (a pass → ``unverified (flaky)``) and one per-phase
  *environment control* at ``phase_base_sha`` (``--collect-only``; rc 0/5 confirms f,
  anything else → ``rerun-skipped (env-broken)``): a collection-level environment
  fault never escalates. Each target runs and is judged on its own, the task taking
  the most severe (``per_target`` records each), so no skip, abort or unverified
  target masks a red one. The case-f output carries each failing node's output tail.
* **Budget** — `rerun_budget`: task runs stop at the budget minus a reserve that the
  confirm and control of the reds already seen use; a red the budget still cuts short
  is named in the skip reason, ``timeout (unconfirmed red: <ids>)``, never dropped.
* **Nothing verified** — no confirmed candidate and no declared target passed (no
  report, a candidate ``conftest.py`` broke collection, no runnable task) →
  phase ``unverified (nothing-verified)``: never ``passed``, never case f by itself.

Stdlib only; every in-repo import is a stdlib-only `skills/_shared` sibling.
"""
from __future__ import annotations

import re
import secrets
import subprocess
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent.parent.parent / "_shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import junit_verdict  # noqa: E402 — the per-node report verdict (stdlib only)
import rerun_budget  # noqa: E402 — the phase budget (sibling script, stdlib only)
import task_scope  # noqa: E402 — stdlib-only sibling; called via module attributes
from rerun_budget import PHASE_BUDGET_S, reserve_for  # noqa: E402,F401
from rerun_budget import Deadline as _Deadline, OutOfBudget as _OutOfBudget  # noqa: E402

_SCRATCH_PARENT = Path(".claude") / "worktrees"


def _git(repo, *args: str, check: bool = True, timeout=None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=check, env=task_scope._git_env(), timeout=timeout)


def _fetch(repo: Path, rev: str, deadline: _Deadline) -> None:
    """Best-effort ``git fetch origin <rev>``, bounded by the budget; never raises."""
    rerun_budget.bounded(lambda t: _git(repo, "fetch", "-q", "origin", rev, check=False,
                                        timeout=t), deadline)


def _result(status: str, reason: str = "", **extra) -> dict:
    out = {"status": status, "reason": reason, "case": None, "nodes": [],
           "escaped_files": [], "unparsed_files": [], "output_tail": "", "rc": None,
           "control": None}
    out.update(extra)
    return out


def _toplevel(repo: Path) -> Path:
    top = _git(repo, "rev-parse", "--show-toplevel", check=False)
    return Path(top.stdout.strip()) if top.returncode == 0 and top.stdout.strip() else repo


def _rel(path: str, repo: Path) -> str:
    """An absolute path inside ``repo`` → repo-relative (git and `classify_path` need it)."""
    p = Path(str(path or ""))
    if not p.is_absolute():
        return str(path or "")
    try:
        return p.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return str(path)


def _slug(design_dir_rel: str) -> str:
    name = Path(str(design_dir_rel or "").rstrip("/")).name or "design"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name)


def _resolve_commit(repo: Path, rev: str, deadline: _Deadline) -> str:
    """``rev^{commit}`` → its full sha (one bounded best-effort fetch first), else ""."""
    spec = f"{rev}^{{commit}}"
    if _git(repo, "rev-parse", "-q", "--verify", spec, check=False).returncode != 0:
        _fetch(repo, rev, deadline)
    res = _git(repo, "rev-parse", "-q", "--verify", spec, check=False)
    return res.stdout.strip() if res.returncode == 0 else ""


def _add_scratch(repo: Path, sha: str, slug: str) -> tuple[Path, str]:
    """Create the named-branch scratch worktree at ``sha`` → ``(path, branch)``."""
    tag = f"{slug}-{sha[:8]}-{secrets.token_hex(3)}"
    path = repo / _SCRATCH_PARENT / f"tp-rerun-{tag}"
    branch = f"tp-rerun/{tag}"
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-q", "-b", branch, str(path), sha)
    return path, branch


def _remove_scratch(repo: Path, path: Path, branch: str) -> None:
    """Best-effort teardown: remove the worktree, prune, delete the branch."""
    _git(repo, "worktree", "remove", "--force", "--force", str(path), check=False)
    _git(repo, "worktree", "prune", check=False)
    _git(repo, "branch", "-D", branch, check=False)


def rerun_phase(repo, sha: str, plan_path: str, phase: int, phase_base_sha: str, *,
                design_dir_rel: str, test_cmd: str | None = None,
                timeout: int = 900, budget: int = PHASE_BUDGET_S,
                reserve: float | None = None) -> dict:
    """Re-run plan phase ``phase``'s runnable Tests at ``sha``.

    Returns ``{status: passed|failed|skipped|unverified, reason, case: None|"f", nodes,
    escaped_files, unparsed_files, output_tail, rc, control}``. Every run is clipped to
    the phase-wide ``budget`` (seconds, started before any fetch); task runs stop at
    ``budget - reserve`` so the candidates seen are still confirmed and controlled.
    """
    deadline = _Deadline(timeout, budget)
    repo = _toplevel(Path(repo))
    plan_path, design_dir_rel = _rel(plan_path, repo), _rel(design_dir_rel, repo)
    if _git(repo, "cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode != 0:
        _fetch(repo, sha, deadline)
    shown = _git(repo, "show", f"{sha}:{plan_path}", check=False)
    if shown.returncode != 0:
        return _result("skipped", "plan-absent")
    plan_text = shown.stdout
    runner, why = task_scope.resolve_runner(repo, test_cmd)
    if runner is None:
        return _result("skipped", why)
    phase_base_sha = _resolve_commit(repo, phase_base_sha, deadline)
    if not phase_base_sha:  # the control and merge-base need it: never "env-broken"
        return _result("skipped", "base-unresolved")
    scratch, branch = _add_scratch(repo, sha, _slug(design_dir_rel))
    nodes: list[dict] = []
    files: dict = {"nodes": nodes}
    try:
        tasks = task_scope.phase_tasks(plan_text, phase)
        tracked = set(_git(repo, "ls-tree", "-r", "--name-only", sha).stdout.splitlines())
        cut = _run_tasks(tasks, runner, tracked, scratch,
                         deadline.until(reserve_for(budget, reserve)), nodes)
        escaped, unparsed = _classify_changes(repo, sha, phase_base_sha, tasks, nodes,
                                              design_dir_rel)
        files.update(escaped_files=escaped, unparsed_files=unparsed)
        confirmed = _confirm(nodes, runner, scratch, deadline)
        if not confirmed:
            if cut:
                return _result("skipped", "timeout", **files)
            if not any(e["status"] == "pass" for e in nodes):  # fail closed
                return _result("unverified", "nothing-verified", **files)
            return _result("passed", **files)
        control = _control(scratch, phase_base_sha, runner, nodes, deadline)
        if control["rc"] not in (0, 5):
            for entry in confirmed:
                entry["status"], entry["reason"] = "rerun-skipped", "env-broken"
            return _result("skipped", "env-broken", control=control, **files)
        for entry in confirmed:
            entry["status"] = "failed"
        tail = "\n".join(f"== {e['task_id']} {e['spec']} ({e['reason']}) ==\n"
                         f"{e['output_tail']}" for e in confirmed)
        return _result("failed", case="f", control=control, rc=confirmed[0].get("rc"),
                       output_tail=tail[-2 * _TAIL_CHARS:], **files)
    except _OutOfBudget:
        return _result("skipped", _unconfirmed(nodes), **files)
    finally:
        _remove_scratch(repo, scratch, branch)


def _run_tasks(tasks, runner, tracked, scratch, stage: _Deadline, nodes: list) -> bool:
    """Run each task until the task stage's share of the budget ends → True if cut."""
    for block in tasks:
        try:
            nodes.append(_run_task(block, runner, tracked, scratch, stage))
        except _OutOfBudget:
            return True
    return False


def _unconfirmed(nodes: list[dict]) -> str:
    """The skip reason when the budget ran out: the reds not yet proven are named."""
    red = [e for e in nodes if e["status"] == "candidate"]
    for entry in red:
        entry["status"], entry["reason"] = "rerun-skipped", "unconfirmed-red"
    ids = ", ".join(dict.fromkeys(str(e["task_id"]) for e in red))
    return f"timeout (unconfirmed red: {ids})" if red else "timeout"


# --- Changed files (case g, log-only in v1) ---------------------------------------

# Case g gates nothing in v1 (design.md Behavior 10, operator ruling 2026-09-24):
# escapes are recorded and self-logged as `files-escape-logged`. Flipping this is a
# later change, justified by a clean corpus report (`unparsed_files == 0`).
FILES_ESCAPE_GATES = False


def _classify_changes(repo: Path, sha: str, base_sha: str, tasks: list[dict],
                      nodes: list[dict], design_dir_rel: str) -> tuple[list[str], list[str]]:
    """Files changed since ``merge-base <phase_base_sha> <sha>`` that no task lists →
    ``(escaped_files, unparsed_files)``. The merge-base keeps a base ref that moved
    after dispatch from reading as candidate changes. Allowed: every File entry, every
    declared target file, and the design dir (the worker commits plan.md status and
    decisions)."""
    listed: set[str] = set()
    unparsed: list[str] = []
    for block in tasks:
        paths, bad = task_scope.parse_files((block.get("fields") or {}).get("File", ""))
        listed.update(paths)
        unparsed.extend(u for u in bad if u not in unparsed)
    listed.update(_target_files(nodes))  # every declared target file that ran
    base = _git(repo, "merge-base", base_sha, sha, check=False)
    if base.returncode != 0:
        return [], unparsed
    diff = _git(repo, "diff", "--name-only", "--no-renames", f"{base.stdout.strip()}..{sha}")
    escaped = [p for p in diff.stdout.splitlines()
               if task_scope.classify_path(p, listed, design_dir_rel) == "unlisted"]
    return sorted(escaped), unparsed


def _target_files(nodes: list[dict]) -> list[str]:
    """Every target file the phase's runs targeted, in order."""
    return list(dict.fromkeys(t.partition("::")[0] for e in nodes
                              for t in e.get("targets") or []))


# --- Confirm pass and environment control -----------------------------------------

def _confirm(nodes: list[dict], runner: str, scratch: Path, timeout: int) -> list[dict]:
    """Re-run each f-candidate once, one run per target (`_judged`).

    Still a candidate → confirmed (returned); a pass → ``unverified (flaky)``; any
    other outcome → ``unverified`` with the confirm's reason.
    """
    confirmed = []
    for entry in nodes:
        if entry["status"] != "candidate":
            continue
        if entry["reason"] == "test-file-absent":  # a tree fact: re-running proves nothing
            confirmed.append(entry)
            continue
        status, reason, _rc, output, _seen = _judged(runner, entry["targets"], scratch,
                                                     timeout)
        if status == "candidate":
            entry["output_tail"] = output or entry["output_tail"]
            confirmed.append(entry)
        else:
            entry["status"] = "unverified"
            entry["reason"] = "flaky" if status == "pass" else reason
    return confirmed


def _control(scratch: Path, base_sha: str, runner: str, nodes: list[dict],
             timeout: int) -> dict:
    """One environment control per phase: reset the *scratch* branch to
    ``phase_base_sha`` and ``--collect-only -q`` each of the phase's test files that
    exist there (else their existing parent dirs, else the default collection), one run
    per target: the first rc outside 0/5 (a timeout: None) decides, else the last."""
    reset = _git(scratch, "reset", "-q", "--hard", base_sha, check=False)
    if reset.returncode != 0:
        return {"rc": None, "targets": [], "output_tail": reset.stderr[-_TAIL_CHARS:]}
    _git(scratch, "clean", "-fdq", check=False)
    files = _target_files(nodes)
    targets = [f for f in files if (scratch / f).is_file()]
    if not targets:
        parents = (str(Path(f).parent) for f in files if str(Path(f).parent) != ".")
        targets = [d for d in dict.fromkeys(parents) if (scratch / d).is_dir()]
    rc, output = None, ""
    for one in [[t] for t in targets] or [[]]:  # one run per target (A31)
        argv = task_scope.runner_argv(runner, ["--collect-only", "-q", *one])
        rc, output, timed_out = _run(argv, scratch, timeout)
        rc = None if timed_out else rc
        if rc not in (0, 5):
            break
    return {"rc": rc, "targets": targets, "output_tail": output}


# --- Per-task classification ------------------------------------------------------

_TAIL_CHARS = 2000


_SEVERITY = {"candidate": 0, "unverified": 1, "pass": 2}


def _judged(runner: str, targets: list[str], scratch: Path, timeout):
    """**One run per declared target** (amendment A31), each judged by its own report
    (`_judge_one`) → ``(status, reason, rc, output, seen)`` of the first most severe
    target, ``seen`` being ``[target, status, reason]`` per target run. A candidate stops
    the loop (nothing outranks it); no skip or abort of one target masks another. Each
    run is clipped to ``timeout`` (the phase `_Deadline`): running out raises
    ``_OutOfBudget`` as before."""
    found, seen = ("unverified", "no-targets", None, ""), []
    for target in targets:
        one = _judge_one(runner, target, scratch, timeout)
        seen.append([target, one[0], one[1]])
        if len(seen) == 1 or _SEVERITY[one[0]] < _SEVERITY[found[0]]:
            found = one
        if found[0] == "candidate":
            break
    return (*found, seen)


def _judge_one(runner: str, target: str, scratch: Path, timeout):
    """One declared target's own run, judged per node by its ``--junitxml`` report
    (`junit_verdict`) → ``(status, reason, rc, output)``: ``pass``; an f-``candidate``
    for ``red``/``collection-error``/``file-missing``; else ``unverified``
    (``timeout``, ``runner-error`` for rc 126/127, ``no-report``, a malformed report,
    ``rootdir-unknown``/``-ambiguous``, ``skipped``, ``node-absent``, ``file-no-tests``,
    ``foreign-failure``). The exit code judges no target."""
    (rc, output, timed_out), (kind, reason) = junit_verdict.run_judged(
        lambda extra, one: _run(task_scope.runner_argv(runner, [*one, *extra]), scratch,
                                timeout), target, scratch)
    if timed_out:
        return "unverified", "timeout", rc, output
    if rc in task_scope.RUNNER_BROKEN_RCS:
        return "unverified", "runner-error", rc, output
    status = {"pass": "pass", "red": "candidate", "missing": "candidate"}.get(kind,
                                                                              "unverified")
    return status, reason, rc, output


def _run(argv: list[str], cwd: Path, timeout) -> tuple[int | None, str, bool]:
    """``task_scope.run_capture`` (shared with ``task_verify check``) → ``(rc, output
    tail, timed_out)``; a missing / non-executable runner is 127 / 126, never raised.
    A ``_Deadline`` timeout is clipped; a run the budget cut short → ``_OutOfBudget``."""
    clipped = timeout.clip() if isinstance(timeout, _Deadline) else timeout
    out = task_scope.run_capture(argv, cwd, clipped, env=task_scope._git_env(),
                                 tail_chars=_TAIL_CHARS)
    if out[2] and isinstance(timeout, _Deadline) and timeout.left() <= 0:
        raise _OutOfBudget()
    return out


def _entry(block: dict, spec: str, status: str, reason: str, **extra) -> dict:
    return {"task_id": block.get("id", ""), "spec": spec, "status": status,
            "reason": reason, **extra}


def _run_task(block: dict, runner: str, tracked: set, scratch: Path, timeout: int) -> dict:
    """One task's declared **Targets** at the SHA. No valid Targets (missing, malformed or
    ``none``) → ``unverified``, never case f; a declared file absent at the SHA is an
    f-candidate for a ``Done`` task and ``unverified`` otherwise."""
    fields = block.get("fields") or {}
    declared = (fields.get("Targets") or "").strip()
    if task_scope.rerun_excluded(block):
        return _entry(block, declared, "excluded", task_scope.task_status(block))
    parsed = task_scope.parse_targets(fields.get("Targets"))
    if parsed["kind"] == "not-runnable":
        return _entry(block, declared, "unverified", parsed["reason"])
    missing = [p for p in parsed["files"] if p not in tracked]
    if missing and task_scope.task_status(block) == "Done":  # "green but never committed"
        return _entry(block, " ".join(missing), "candidate", "test-file-absent", rc=None,
                      targets=missing, output_tail="\n".join(
                          f"{p}: not in the tree at the SHA" for p in missing))
    targets = [s for s in parsed["specs"] if s.partition("::")[0] not in missing]
    if not targets:
        return _entry(block, " ".join(missing), "unverified", "test-file-absent")
    status, reason, rc, output, seen = _judged(runner, targets, scratch, timeout)
    if status == "pass" and missing:  # a red present file still counts; a green run
        status, reason = "unverified", "test-file-absent"  # leaves the absent one unverified
    return _entry(block, " ".join(targets), status, reason, rc=rc, targets=targets,
                  per_target=seen, output_tail=output)
