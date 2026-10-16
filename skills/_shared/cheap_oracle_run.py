#!/usr/bin/env python3
"""cheap_oracle_run.py — the executing cheap-tier oracles and the check CLI.

design: cheap-tier-offload (Phase 2)

These oracles run commands: an argv list (never a shell), with a timeout and
the cwd taken from ctx. They register into cheap_oracle.ORACLES on import, and
cheap_oracle.check imports this module lazily on a registry miss. Like every
oracle they recompute the result and never read the artifact own claims
("ok", "ran", "exit", "passed").

- exit_code: ctx["verify_argv"], run in ctx["cwd"], exits 0.
- reproducer_fixed: reproduce.run_reproducers on the fixed tree (ctx["cwd"])
  gives NOT_REPRODUCED for ctx["finding"], and ctx["test_argv"] exits 0.
- zero_drop: verify.verify(ours, theirs, artifact["resolved"], base=base,
  mechanical_applied=True) is VERIFIED; ours / theirs are read from
  ctx["ours_path"] / ctx["theirs_path"]. base is the text at the optional
  ctx["base_path"] (the merge base), and None when the ctx names none: with a base
  the check is three-way and excuses a change only one side made (a retitle); without
  one it is the two-way check. An unreadable base_path fails like an unreadable
  ours_path. DROPS_DETECTED and UNVERIFIABLE fail.
  So does a text that is not resolved: a conflict-marker line (`<<<<<<<`,
  `|||||||`, `=======`, `>>>>>>>`) that neither side carries, or ours and theirs
  pasted together (either order) when they share a line, which repeats it.
- observed_red: artifact {"source", "test_name"} written to
  scratch_dir/repro_scaffold.py and run once, as reproduce runs a test reproducer
  (pytest plus the junit report flags) in ctx["cwd"], which must be at ctx["head"].
  Only the named test failing on an assertion is OK: a pass, a collection or usage
  error, an `<error>`, a failure that is not an assertion, an absent name, a stale
  or missing junit report, and a wrong commit each drop with their own reason.

CLI: cheap_oracle_run.py check --slot S --artifact A.json --ctx C.json prints
one JSON line, the verdict and the action, and exits 0 on every path: an
unreadable file is a failed verdict with the slot's on_fail action, and a bad
slot is one with action "escalate" (today's path). The caller acts on action.
A missing flag is still an argparse usage error (exit 2), because that is a
caller bug, not a verdict.

The sibling helpers (tp-pr-iterate reproduce, tp-merge-from-main verify) are
imported inside the oracle bodies, never at module load.
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import argv_runner  # noqa: E402 — in-repo, stdlib-only sibling
import cheap_oracle  # noqa: E402 — in-repo, stdlib-only sibling
import cheap_tier  # noqa: E402 — in-repo, stdlib-only sibling
import junit_verdict  # noqa: E402 — in-repo, stdlib-only sibling

DEFAULT_TIMEOUT = 600
_SKILLS = _SHARED.parent


def _run(argv, cwd, timeout) -> argv_runner.RunResult:
    """Run argv in cwd; rc is None when the run itself failed (timeout, OSError)."""
    return argv_runner.run_argv(argv, cwd=cwd, timeout=timeout)


def _timeout(ctx: dict):
    return ctx.get("timeout", DEFAULT_TIMEOUT)


def _exits_zero(label: str, argv, ctx: dict) -> tuple[bool, str]:
    r = _run(argv, ctx["cwd"], _timeout(ctx))
    if r.rc == 0:
        return True, ""
    if r.rc is None:
        return False, f"{label} did not finish: {r.tail}"
    return False, f"{label} exited {r.rc}: {r.tail}"


def _sibling(skill: str, module: str):
    """Import module from skills/<skill>/scripts (added to sys.path on first use)."""
    scripts = str(_SKILLS / skill / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return importlib.import_module(module)


@cheap_oracle.register("exit_code")
def exit_code(artifact: dict, ctx: dict) -> tuple[bool, str]:
    """ctx["verify_argv"], run in ctx["cwd"], exits 0 within ctx["timeout"]."""
    return _exits_zero("verify_argv", ctx["verify_argv"], ctx)


@cheap_oracle.register("reproducer_fixed")
def reproducer_fixed(artifact: dict, ctx: dict) -> tuple[bool, str]:
    """The finding reproducer no longer reproduces on the fixed tree, and the
    tests pass there."""
    reproduce = _sibling("tp-pr-iterate", "reproduce")
    finding = dict(ctx["finding"])
    if (finding.get("verdict") != "structural" or reproduce.is_sentinel(finding)
            or not reproduce.valid_reproducer(finding.get("reproducer"))):
        return False, "the finding carries no runnable structural reproducer"
    _, downgrades = reproduce.run_reproducers(
        [finding], cwd=ctx["cwd"], scratch_dir=ctx["scratch_dir"], timeout=_timeout(ctx),
        round_dir_mode=False)
    if not downgrades:  # no downgrade record: it still reproduces
        return False, f"reproducer {reproduce.REPRODUCED} on the fixed tree"
    rec = downgrades[0]
    if rec["reason"] != reproduce.NOT_REPRODUCED:
        return False, f"reproducer {rec['reason']} on the fixed tree: {rec['output']}"
    return _exits_zero("test_argv", ctx["test_argv"], ctx)


_MARKER_RE = re.compile(r"(?:<{7}|\|{7}|>{7})(?: .*)?|={7}")


def _lines(text: str) -> list[str]:
    return [ln.rstrip() for ln in text.splitlines() if ln.strip()]


def _unresolved(ours: str, theirs: str, resolved: str) -> str:
    """Why `resolved` is not a resolution, or "" when it is one."""
    sides = set(_lines(ours)) | set(_lines(theirs))
    marks = [ln for ln in _lines(resolved) if _MARKER_RE.fullmatch(ln) and ln not in sides]
    if marks:
        return f"conflict marker left in: {marks[0]!r}"
    o, t, r = _lines(ours), _lines(theirs), _lines(resolved)
    if set(o) & set(t) and r in (o + t, t + o):
        return "ours and theirs pasted together, not spliced"
    return ""


@cheap_oracle.register("zero_drop")
def zero_drop(artifact: dict, ctx: dict) -> tuple[bool, str]:
    """Every content atom of ours and theirs survives into the proposed splice, and
    the splice is resolved (no conflict marker, not a paste of both sides)."""
    verify = _sibling("tp-merge-from-main", "verify")
    ours = Path(ctx["ours_path"]).read_text(encoding="utf-8")
    theirs = Path(ctx["theirs_path"]).read_text(encoding="utf-8")
    base = Path(ctx["base_path"]).read_text(encoding="utf-8") if ctx.get("base_path") else None
    why = _unresolved(ours, theirs, artifact["resolved"])
    if why:
        return False, why
    result = verify.verify(ours, theirs, artifact["resolved"], base=base, mechanical_applied=True)
    if result.verdict == verify.VERIFIED:
        return True, ""
    dropped = f" (dropped: {', '.join(map(str, result.dropped))})" if result.dropped else ""
    return False, f"{result.verdict}{dropped}"


_DTD = re.compile(r"<!(?:DOCTYPE|ENTITY)", re.IGNORECASE)


def _assertion_failure(case) -> bool:
    failure = case.find("failure")
    msg = failure.get("message", "") if failure is not None else ""
    return failure is not None and msg.startswith(("assert", "AssertionError"))


def _judge_report(report: Path, test_name: str) -> tuple[bool, str]:
    """The observed_red verdict from a junit report of a run that exited 1."""
    try:
        text = report.read_text(encoding="utf-8")
        if _DTD.search(text):  # a report never carries a DTD
            raise ET.ParseError("DTD in junit report")
        root = ET.fromstring(text)  # nosec B314 — DTD-free input only (checked above)
    except (OSError, UnicodeDecodeError, ET.ParseError):
        return False, "no junit report (non-pytest runner?)"
    if root.find(".//error") is not None:
        return False, "error, not an assertion"
    cases = [c for c in root.iter("testcase")
             if c.get("name") == test_name or (c.get("name") or "").startswith(test_name + "[")]
    if not cases:
        return False, "named test absent"
    if not all(_assertion_failure(c) for c in cases):
        return False, "failed, not by an assertion"
    return True, ""


@cheap_oracle.register("observed_red")
def observed_red(artifact: dict, ctx: dict) -> tuple[bool, str]:
    """The scaffold's named test fails on an assertion at ctx["head"], observed
    here by running it, never from the artifact's own claim.

    The audit copy stays at `scratch_dir/repro_scaffold.py`; the run uses an
    in-tree copy (`reproduce._in_tree_scratch`), as `reproduce` runs a test
    reproducer: `scratch_dir` sits under the proof root, which in a linked
    worktree is `<main>/.git/worktrees/...`, where pytest would take its rootdir,
    ini and conftest chain from the main checkout, another commit."""
    reproduce = _sibling("tp-pr-iterate", "reproduce")
    head = _run(["git", "-C", str(ctx["cwd"]), "rev-parse", "HEAD"], ctx["cwd"], _timeout(ctx))
    if head.rc != 0 or head.stdout.strip() != ctx["head"]:
        return False, "scratch not at head"
    scratch = Path(ctx["scratch_dir"])
    report = scratch / "report.xml"
    try:
        scratch.mkdir(parents=True, exist_ok=True)
        (scratch / "repro_scaffold.py").write_text(artifact["source"], encoding="utf-8")
        report.unlink(missing_ok=True)  # an old report must never be read
        with reproduce._in_tree_scratch(ctx["cwd"]) as tree_scratch:
            script = tree_scratch / "repro_scaffold.py"
            script.write_text(artifact["source"], encoding="utf-8")
            argv = [reproduce.PYTHON, *reproduce.PYTEST_ARGS, str(script),
                    *junit_verdict.report_args(str(report))]
            r = _run(argv, ctx["cwd"], _timeout(ctx))
    except OSError as exc:
        return False, f"could not write the scaffold: {exc}"
    if r.rc is None:
        return False, f"scaffold run did not finish: {r.tail}"
    if r.rc == 0:
        return False, "passes on head"
    if r.rc != 1:
        label = "collection or usage error" if 2 <= r.rc <= 5 else "unexpected exit"
        return False, f"{label} (rc {r.rc}): {r.tail}"
    return _judge_report(report, artifact["test_name"])


# --- CLI -------------------------------------------------------------------------


def _load(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return data


def run_check(slot: str, artifact_path: str, ctx_path: str) -> dict:
    """{verdict, action} for the check subcommand; never raises."""
    try:
        artifact, ctx = _load(artifact_path), _load(ctx_path)
        verdict = cheap_oracle.check(slot, artifact, ctx)
        action = cheap_oracle.settle(slot, verdict)
    except Exception as exc:  # noqa: BLE001 — a bad slot or file is a verdict, exit 0
        verdict = {"ok": False, "oracle": "", "reason": f"cli-error: {exc}"}
        row = cheap_tier.SLOTS.get(slot) if slot != "task" else None
        action = row.on_fail if row else "escalate"
    return {"verdict": verdict, "action": action}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="cheap_oracle_run.py",
                                     description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    chk = sub.add_parser("check", help="run the slot oracle; prints {verdict, action}")
    chk.add_argument("--slot", required=True)
    chk.add_argument("--artifact", required=True)
    chk.add_argument("--ctx", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run_check(args.slot, args.artifact, args.ctx)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
