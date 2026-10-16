"""fragility_predicate.py — the merge-gate `fragility_clear` predicate (Behavior 3).

design: fragile-test-prevention (detailed-design-stages.md Part C4, `fragility_predicate.py`
bullet list; detailed-design.md `pred_fragility_clear`).

`pred_fragility_clear` folds three conditions, evaluated in order, into one
`PredicateResult`: lint (`fragility_lint.check_diff`), items
(`fragility_items.open_items`) and runs (`changed_tests_runs.read`). Each condition is a
separate helper so a FAIL names exactly the condition that failed; an internal error or a
lint exit 2 is INDETERMINATE, never a silent PASS (mirrors `pred_review_proof_on_head`'s
NEVER-FAIL-on-error discipline, inverted: this predicate never PASSes on an error either —
it is fail-closed both ways, since D6 only protects against a false FAIL from a transient
error, not against a fragile PR slipping through).

`head_ref` is the commit the lint and the run record bind (`check_diff` lints it, `read`
resolves it); `branch` is the key `open_items` reads (its store is keyed by branch, not oid)
and defaults to `head_ref`. `roster_block` is the gate's caller: on the live path it passes
the PR head oid as `head_ref` and, as `branch`, the local branch that contains that oid,
preferring the checked-out one. At `/tp-merge` the design worktree may be one unpushed
log-flush commit ahead of the PR head, so no branch tip need equal the oid; the lint and the
record still bind the PR head itself, never a branch tip.
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import changed_tests_runs
import fragility_items
import fragility_lint
import task_scope

_RUNS_SCRIPT = Path(changed_tests_runs.__file__).resolve()
_ITEMS_SCRIPT = Path(fragility_items.__file__).resolve()
_NAME = "fragility_clear"
_OPT_OUT = "skipped (opt-out): fragility.merge_predicate=false"
_HERMETIC = "<fragility> inactive (hermetic run — no fragility_fn injected)"


def _lint_check(lint_fn, repo_root, base_ref, head_ref):
    """``(status, detail)``, ``status`` one of ``pass`` / ``fail`` / ``indeterminate``."""
    result = lint_fn(repo_root, base_ref, head_ref)
    if result.exit == 2:
        why = ", ".join(result.could_not_evaluate[:5]) or "the diff"
        return "indeterminate", f"lint could not evaluate: {why}"
    if result.exit == 1:
        blocking = [h for h in result.hits if h.gating and not h.waived] or list(result.hits)
        listed = ", ".join(f"{h.path}:{h.line} {h.rule_id}" for h in blocking[:5])
        return "fail", f"fragile pattern(s) on added lines: {listed}"
    return "pass", ""


def _cmd(script, *args) -> str:
    """A shell-quoted `python3 <abs script> ...` line the operator can paste anywhere."""
    return shlex.join(["python3", str(script), *(str(a) for a in args)])


def _items_check(items_fn, repo_root, branch):
    """``(status, detail)``: any open item fails, listing its id (the waiver key) and the
    runnable waiver command (`fragility_items.py waive` needs `--branch`)."""
    items = items_fn(repo_root, branch)
    if not items:
        return "pass", ""
    ids = ", ".join(item["id"] for item in items)
    waive = _cmd(_ITEMS_SCRIPT, "waive", "--root", Path(repo_root).resolve(), "--branch",
                 branch, "--id", "<id>", "--by", "<you>", "--reason", "<why>")
    return "fail", f"open fragility item(s) on {branch}: {ids} (waive with: {waive})"


def _runs_check(runs_fn, repo_root, base_ref, head_ref, *, strict):
    """``(status, detail)``: a missing or stale record fails, naming the `record` command."""
    rec = runs_fn(repo_root, head_ref)
    if rec is None:
        cmd = _cmd(_RUNS_SCRIPT, "record", "--root", Path(repo_root).resolve(),
                   "--base", base_ref, "--head", head_ref)
        return "fail", f"no current changed-tests run record for this head — run: {cmd}"
    verdict = rec.get("verdict")
    reason = rec.get("reason") or ""
    if verdict == "pass":
        return "pass", ""
    if verdict == "fail":
        return "fail", f"changed-tests run failed: {reason or 'see the run record'}"
    if verdict == "unverified":
        if strict:
            return "fail", f"changed-tests run unverified under fragility.strict: {reason}"
        return "pass", f"changed-tests run unverified: {reason} (fragility.strict is off)"
    return "fail", f"unexpected changed-tests run verdict: {verdict!r}"


def _strict(config) -> bool:
    try:
        block = (config or {}).get("fragility") if isinstance(config, dict) else None
        return isinstance(block, dict) and block.get("strict") is True
    except Exception:
        return False


def pred_fragility_clear(*, repo_root, base_ref, head_ref, config, branch=None, lint_fn=None,
                         items_fn=None, runs_fn=None):
    """Gate predicate: is this PR head clear of fragile-test patterns, open fragility
    items and a failing/missing/stale changed-tests run record?

    PASS needs all three conditions to pass (the runs condition also passes on
    ``unverified`` unless ``fragility.strict`` is true). FAIL names the first failing
    condition, in the fixed order lint → items → runs. A lint exit 2 (could not evaluate
    the diff) or any internal error is INDETERMINATE — this predicate is fail-closed in
    both directions, never a silent PASS on an error.

    ``branch`` is the items-store key (default ``head_ref``). ``lint_fn`` defaults to
    `fragility_lint.check_diff`, ``items_fn`` to `fragility_items.open_items`, ``runs_fn``
    to `changed_tests_runs.read` — each injectable for tests. NEVER raises.
    """
    from deterministic_gate import PredicateResult, GateVerdict  # late, circular-safe

    lint_fn = lint_fn or fragility_lint.check_diff
    items_fn = items_fn or fragility_items.open_items
    runs_fn = runs_fn or changed_tests_runs.read
    try:
        status, detail = _lint_check(lint_fn, repo_root, base_ref, head_ref)
        if status == "indeterminate":
            return PredicateResult(name=_NAME, verdict=GateVerdict.INDETERMINATE, detail=detail)
        if status == "fail":
            return PredicateResult(name=_NAME, verdict=GateVerdict.FAIL, detail=detail)

        status, detail = _items_check(items_fn, repo_root,
                                      head_ref if branch is None else branch)
        if status == "fail":
            return PredicateResult(name=_NAME, verdict=GateVerdict.FAIL, detail=detail)

        status, detail = _runs_check(runs_fn, repo_root, base_ref, head_ref,
                                     strict=_strict(config))
        if status == "fail":
            return PredicateResult(name=_NAME, verdict=GateVerdict.FAIL, detail=detail)

        return PredicateResult(
            name=_NAME, verdict=GateVerdict.PASS,
            detail=detail or "lint, items and changed-tests runs are all clear",
        )
    except Exception:
        return PredicateResult(name=_NAME, verdict=GateVerdict.INDETERMINATE,
                               detail="internal error evaluating fragility_clear")


# --- the gate's live path and roster block (task 8.5) -----------------------------------

def _items_branch(repo_root, oid):
    """``(branch, why)``: the local branch whose history contains the PR head ``oid`` — the
    checked-out one when it does (the design worktree may be ahead of the PR head), else the
    only one that does; ``(None, why)`` when the oid is not local, no branch contains it, or
    several do and none is checked out. Local git only, never a fetch."""
    def git(*args):
        return subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True,
                              text=True, check=False, env=task_scope._git_env())
    hint = "fetch the PR branch, check it out and re-run the gate from that checkout"
    done = git("for-each-ref", f"--contains={oid}", "--format=%(refname)", "refs/heads/")
    if done.returncode != 0:
        return None, f"PR head {oid} is not in the local repo — {hint}"
    names = [n.removeprefix("refs/heads/") for n in done.stdout.splitlines() if n]
    here = git("symbolic-ref", "--quiet", "HEAD").stdout.strip().removeprefix("refs/heads/")
    if here in names:
        return here, ""
    if len(names) == 1:
        return names[0], ""
    if not names:
        return None, f"no local branch contains PR head {oid} — {hint}"
    return None, (f"PR head {oid} is on several local branches ({', '.join(names)}) and none "
                  "is checked out — re-run the gate from the PR branch's checkout")


def pred_fragility_clear_live(*, repo_root, base_ref, head_ref, config):
    """The gate's live `fragility_clear`: ``head_ref`` is the PR head oid; the items branch
    is resolved locally (`_items_branch`). A missing root, base or branch is INDETERMINATE."""
    from deterministic_gate import PredicateResult, GateVerdict  # late, circular-safe

    why = ("could not resolve project root for fragility_clear" if repo_root is None else
           "could not resolve the base ref for fragility_clear" if not base_ref else "")
    branch = None
    if not why:
        try:
            branch, why = _items_branch(repo_root, head_ref)
        except Exception as exc:  # an OSError from git: fail closed, never PASS
            why = f"could not resolve the PR head's branch: {exc}"
    if branch is None:
        return PredicateResult(name=_NAME, verdict=GateVerdict.INDETERMINATE, detail=why)
    return pred_fragility_clear(repo_root=repo_root, base_ref=base_ref, head_ref=head_ref,
                                config=config, branch=branch)


def _merge_predicate(config) -> bool:
    """False only on a literal ``fragility.merge_predicate: false`` (default on)."""
    block = config.get("fragility") if isinstance(config, dict) else None
    return not (isinstance(block, dict) and block.get("merge_predicate") is False)


def roster_block(*, config, r, running_live, repo_root, pr_head, base_ref):
    """``(predicates, entries)`` for `fragility_clear`, the gate's entry after the proof
    predicate — never silently absent. The opt-out (`fragility.merge_predicate: false`) and
    a hermetic run with no ``fragility_fn`` seam (an explicit ``None`` is not injected) are
    one OMITTED entry and no predicate. Otherwise the seam, or on a live run
    `pred_fragility_clear_live`, is called as ``fn(repo_root=, base_ref=, head_ref=pr_head,
    config=)``; its result is the one predicate. A raising seam is INDETERMINATE."""
    from deterministic_gate import PredicateResult, GateVerdict  # late, circular-safe
    from gate_roster import RosterEntry

    if not _merge_predicate(config):
        return [], [RosterEntry.omitted(_NAME, reason=_OPT_OUT)]
    fn = r.get("fragility_fn") if isinstance(r, dict) else None
    if fn is None and not running_live:
        return [], [RosterEntry.omitted(_NAME, reason=_HERMETIC)]
    try:
        result = (fn or pred_fragility_clear_live)(
            repo_root=repo_root, base_ref=base_ref, head_ref=pr_head, config=config)
    except Exception as exc:
        result = PredicateResult(name=_NAME, verdict=GateVerdict.INDETERMINATE,
                                 detail=f"internal error evaluating fragility_clear: {exc}")
    return [result], [RosterEntry.from_result(result)]
