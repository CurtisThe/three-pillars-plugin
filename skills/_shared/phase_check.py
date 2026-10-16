"""phase_check.py — one phase check per phase: deterministic hits, then two agents.

design: review-convergence (Phase 8, §`SH/phase_check.py`)

``prepare`` runs the deterministic half over a commit range (fragility lint, refactor
invariance, the Targets freeze, the trust-boundary surfaces), writes the two agent
prompts into a scratch dir out of the work tree, and records an ``open`` entry in the
committed carry file. ``put`` is the only reply path: strict JSON, one object, into the
scratch dir. ``close`` ends the phase: every checker finding the worker did not fix becomes
a carry item (``disputed`` with its reason, otherwise ``unfixed``), and ``known_items``
hands that list to the impl audit. The CLI is the same four verbs.

The carry makes the check once-per-phase: a ``closed`` entry skips whatever head is
passed; an ``open`` entry (a session restarted between ``prepare`` and ``close``)
resumes with the prompts read back byte-identically, so the orchestrator re-dispatches
the same work instead of re-running the checks. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
for _p in (_SHARED, str(Path(_SHARED).parents[0] / "tp-pr-iterate" / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agent_caps  # noqa: E402 — BUDGET_LINE: the finder's last line
import angles  # noqa: E402 — REVIEW_BAR: one source, never copied
import fragility_lint  # noqa: E402
import refactor_invariance  # noqa: E402
import strict_json_reply  # noqa: E402
import task_scope  # noqa: E402
import targets_frozen  # noqa: E402
import trust_boundary  # noqa: E402
import weight_class  # noqa: E402

CARRY = "phase-check-carry.json"  # design dir; committed between phases
SLOTS = ("finder", "checker")
FINDER_CLASS = "review_finder"
CHECKER_AGENT = "tp-phase-checker"
JDI_WARN = ("phase-check: just-do-it design has no jdi entry in phase-"
            "check-carry.json")


def _git(repo, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          text=True, env=task_scope._git_env())
    if done.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def scratch_dir(repo, slug, phase) -> Path:
    """The out-of-tree scratch dir for one phase check (in the git common dir)."""
    out = _git(repo, "rev-parse", "--git-common-dir")
    common = Path(out)
    if not common.is_absolute():
        common = Path(repo) / common
    return common / "three-pillars" / "phase-check" / str(slug) / str(phase)


def _read_carry(design_dir: Path) -> dict:
    path = design_dir / CARRY
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_carry(design_dir: Path, carry: dict) -> None:
    (design_dir / CARRY).write_text(json.dumps(carry, indent=2) + "\n",
                                    encoding="utf-8")


def _default_invariance(repo, plan_path, phase, base, head) -> dict:
    """The real invariance run: plan targets, the range's changed files, the repo runner."""
    changed = [line for line in _git(repo, "diff", "--name-only",
                                    f"{base}..{head}").splitlines() if line]
    runner, _why = task_scope.resolve_runner(repo, None)
    return refactor_invariance.run(repo, refactor_invariance._phase_targets(plan_path, phase),
                                   changed, runner=runner)


def _criteria(plan_path: Path | None, phase: int) -> str:
    """The ``## Phase N`` block's prose (up to its first task row), or the no-plan note."""
    if plan_path is None or not Path(plan_path).exists():
        return "no plan.md for this design — no acceptance criteria available (no plan)."
    lines = Path(plan_path).read_text(encoding="utf-8").splitlines()
    head_at = next((i for i, line in enumerate(lines)
                    if line.startswith("## ") and f"Phase {phase}" in line), None)
    if head_at is None:
        return f"no plan.md `## Phase {phase}` block — no acceptance criteria available."
    body = []
    for line in lines[head_at + 1:]:
        if line.startswith("## ") or line.startswith("### "):
            break
        body.append(line)
    return "\n".join(body).strip() or "(the phase block has no prose)"


def _design_scope(design_dir: Path) -> str:
    """The ``## Scope`` section of design.md — the criteria when there is no plan."""
    path = Path(design_dir) / "design.md"
    if not path.exists():
        return "no design.md Scope section"
    lines = path.read_text(encoding="utf-8").splitlines()
    head_at = next((i for i, line in enumerate(lines) if line.strip() == "## Scope"),
                   None)
    if head_at is None:
        return "no design.md Scope section"
    body = []
    for line in lines[head_at + 1:]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body).strip() or "no design.md Scope section"


def _prompt(kind: str, slug: str, phase, base: str, head: str, scratch: Path,
            criteria: str, det: dict, surfaces: list) -> str:
    """One agent prompt: range, criteria, hits, the review bar (+ surfaces / delivery)."""
    parts = [f"# Phase check {kind} — {slug} phase {phase}",
             "", f"Diff range: `{base}..{head}`",
             "", "## Acceptance criteria", "", criteria,
             "", "## Deterministic hits", "", "```json",
             json.dumps(det, indent=2), "```",
             "", "## Review bar", "", f"Review bar: {angles.REVIEW_BAR}"]
    if kind == "checker":
        parts += ["", f"The finder's reply is at `{scratch}/finder.reply.json`.",
                  "", "## Surfaces", "",
                  json.dumps(surfaces, indent=2),
                  "", "Deliver your reply ONLY with:", "",
                  f"    python3 {_SHARED}/phase_check.py put "
                  f"--scratch {scratch} --slot checker"]
        if surfaces:
            parts += ["", f"Security lens: {trust_boundary.SECURITY_BAR}"]
    else:
        parts += ["", "Report each finding as soon as you confirm it.", "",
                  agent_caps.BUDGET_LINE]
    return "\n".join(parts) + "\n"


def prepare(design_dir, phase, *, base, head, repo=".", plan_path=None, jdi=False,
            local=False, run_git=None, invariance=None) -> dict:
    """The deterministic half of the phase check plus the two agent prompts."""
    design_dir = Path(design_dir)
    repo = Path(repo)
    phase_key = str(phase)
    carry = _read_carry(design_dir)
    entry = (carry.get("phases") or {}).get(phase_key) or {}
    if entry.get("status") == "closed":
        return {"status": "skip", "reason": "already-checked"}

    scratch = scratch_dir(repo, design_dir.name, phase)
    if entry.get("status") == "open":
        fp = (scratch / "finder.prompt.md").read_text(encoding="utf-8")
        cp = (scratch / "checker.prompt.md").read_text(encoding="utf-8")
        return {"status": "resume", "scratch": str(scratch),
                "finder": {"cheap_class": FINDER_CLASS, "prompt": fp},
                "checker": {"agent": CHECKER_AGENT, "prompt": cp}}

    plan = Path(plan_path) if plan_path else (design_dir / "plan.md")
    plan = plan if plan.exists() else None
    jdi = jdi or phase_key == "jdi"
    phase_int = None if jdi else int(phase)

    lint = fragility_lint.check_diff(repo, base, head)
    if jdi or plan is None:
        inv = {"skipped": "jdi" if jdi else "no plan"}
    else:
        run_inv = invariance or _default_invariance
        inv = run_inv(repo, plan, phase_int, base, head)
    if jdi or plan is None or local:
        targets: list = []
    else:
        targets = targets_frozen.range_audit(repo, base, head, plan, phase_int)
    surfaces = trust_boundary.surfaces_for_range(repo, base, head, run_git=run_git)

    det = {"slug": design_dir.name, "phase": phase_key, "base": base, "head": head,
           "lint": [fragility_lint.render(h) for h in lint.hits],
           "lint_exit": lint.exit, "invariance": inv, "targets": targets,
           "surfaces": surfaces}
    scratch.mkdir(parents=True, exist_ok=True)
    (scratch / "deterministic.json").write_text(json.dumps(det, indent=2) + "\n",
                                                encoding="utf-8")
    criteria = _design_scope(design_dir) if jdi else _criteria(plan, phase_int)
    prompts = {kind: _prompt(kind, design_dir.name, phase_key, base, head, scratch,
                              criteria, det, surfaces) for kind in SLOTS}
    (scratch / "finder.prompt.md").write_text(prompts["finder"], encoding="utf-8")
    (scratch / "checker.prompt.md").write_text(prompts["checker"], encoding="utf-8")

    carry.setdefault("phases", {})[phase_key] = {
        "base": base, "head": head,
        "started_at": datetime.now(timezone.utc).isoformat(), "status": "open"}
    _write_carry(design_dir, carry)
    return {"status": "ready", "scratch": str(scratch),
            "finder": {"cheap_class": FINDER_CLASS, "prompt": prompts["finder"]},
            "checker": {"agent": CHECKER_AGENT, "prompt": prompts["checker"]}}


def put(scratch, slot, text) -> Path:
    """One strict-JSON reply into the scratch dir; anything else is a ValueError."""
    if slot not in SLOTS:
        raise ValueError(f"unknown slot: {slot}")
    if strict_json_reply.one_object(text) is None:
        raise ValueError("reply is not one strict JSON object")
    out = Path(scratch) / f"{slot}.reply.json"
    out.write_text(text, encoding="utf-8")
    return out


def _read_reply(path) -> dict:
    """A reply file's one strict JSON object, or ``{}`` when it is absent/unparseable."""
    if path is None or not Path(path).exists():
        return {}
    return strict_json_reply.one_object(Path(path).read_text(encoding="utf-8")) or {}


def _worker_status(worker: dict) -> dict:
    """finding id -> ``fixed`` | ``disputed`` (with its reason) from the worker reply."""
    out = {str(i): {"status": "fixed"} for i in worker.get("fixed") or []}
    for item in worker.get("disputed") or []:
        if isinstance(item, dict) and item.get("id") is not None:
            out[str(item["id"])] = {"status": "disputed", "reason": item.get("reason")}
    return out


def close(design_dir, phase, *, scratch, worker_reply_path=None) -> dict:
    """End the phase: every checker finding the worker did not fix becomes a carry item."""
    design_dir = Path(design_dir)
    phase_key = str(phase)
    carry = _read_carry(design_dir)
    entry = (carry.get("phases") or {}).get(phase_key) or {}
    if entry.get("status") == "closed":
        return {"carried": 0, "fixed": 0, "status": "already-closed"}

    findings = _read_reply(Path(scratch) / "checker.reply.json").get("findings") or []
    statuses = _worker_status(_read_reply(worker_reply_path))
    items = carry.setdefault("items", [])
    carried = fixed = 0
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        state = statuses.get(str(finding.get("id")))
        if state and state["status"] == "fixed":
            fixed += 1
            continue
        item = {"phase": phase_key, "id": finding.get("id"), "file": finding.get("file"),
                "line_range": finding.get("line_range"), "summary": finding.get("summary"),
                "blocking": finding.get("blocking"),
                "status": "disputed" if state else "unfixed"}
        if state:
            item["reason"] = state["reason"]
        items.append(item)
        carried += 1

    carry.setdefault("phases", {}).setdefault(phase_key, {})["status"] = "closed"
    _write_carry(design_dir, carry)
    return {"carried": carried, "fixed": fixed}


def known_items(design_dir) -> list:
    """Every carry item across phases — the impl audit's "already known" input."""
    return _read_carry(Path(design_dir)).get("items") or []


def jdi_warning(design_dir) -> str | None:
    """The advisory line for a just-do-it design whose carry has no ``jdi`` entry."""
    design_dir = Path(design_dir)
    if weight_class.read_class(design_dir)[0] != "just-do-it":
        return None
    if "jdi" in (_read_carry(design_dir).get("phases") or {}):
        return None
    return JDI_WARN


def _add_design_phase(parser) -> None:
    """``--design-dir`` + ``--phase`` (a string: a number or ``jdi``), passed through."""
    parser.add_argument("--design-dir", required=True)
    parser.add_argument("--phase", required=True)


def main(argv=None) -> int:
    """The four verbs, each printing exactly one JSON value."""
    parser = argparse.ArgumentParser(prog="phase_check.py")
    subs = parser.add_subparsers(dest="cmd", required=True)
    prep = subs.add_parser("prepare")
    _add_design_phase(prep)
    prep.add_argument("--base", required=True)
    prep.add_argument("--head", required=True)
    prep.add_argument("--repo", default=".")
    prep.add_argument("--plan", default=None)
    prep.add_argument("--jdi", action="store_true")
    prep.add_argument("--local", action="store_true")
    put_p = subs.add_parser("put")
    put_p.add_argument("--scratch", required=True)
    put_p.add_argument("--slot", required=True, choices=SLOTS)
    close_p = subs.add_parser("close")
    _add_design_phase(close_p)
    close_p.add_argument("--scratch", required=True)
    close_p.add_argument("--worker-reply", default=None)
    known_p = subs.add_parser("known")
    known_p.add_argument("--design-dir", required=True)
    jdi_p = subs.add_parser("jdi-warn")
    jdi_p.add_argument("--design-dir", required=True)

    args = parser.parse_args(argv)
    if args.cmd == "jdi-warn":
        line = jdi_warning(args.design_dir)
        if line is not None:
            print(line)
        return 0
    if args.cmd == "put":
        try:
            out = put(args.scratch, args.slot, sys.stdin.read())
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}))
            return 1
        print(json.dumps({"path": str(out)}))
        return 0
    if args.cmd == "prepare":
        res = prepare(args.design_dir, args.phase, base=args.base, head=args.head,
                      repo=args.repo, plan_path=args.plan, jdi=args.jdi, local=args.local)
    elif args.cmd == "close":
        res = close(args.design_dir, args.phase, scratch=args.scratch,
                    worker_reply_path=args.worker_reply)
    else:
        res = known_items(args.design_dir)
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
