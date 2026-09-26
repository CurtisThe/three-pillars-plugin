"""reproduce — run each blocking finding's reproducer against the reviewed head.

design: iterate-convergence-budget (Tasks 5.2, 5.3)

Review bar: "Only a demonstrated shipped-behaviour defect with a reproducer
blocks; mutation survivors, test-tightening, exotic env, lint-guard bypasses,
style and perf are non-blocking notes."

Per blocking (structural, non-sentinel) finding:
- reproduced (stays blocking): pytest exit 1, or a command whose exit/stdout
  violates its `expect` (the expectation describes correct behaviour);
- not-reproduced (ran and passed): `blocking=False`, `verdict="minor"`,
  `downgrade={reason:"not-reproduced", output<=500}`;
- inconclusive (pytest 2/3/4/5, timeout, OSError): stays blocking, noted with
  `downgrade={reason:"inconclusive", ...}` — the runner never fails open;
- round-dir mode: a structural finding without a valid reproducer (legacy
  shape) is downgraded with `schema_note="legacy-no-reproducer"`.

Sentinels are never touched. Test reproducers are written to
`scratch_dir/repro_<i>.py` and run as `python3 -m pytest -q -p no:cacheprovider`;
command reproducers run as argv lists, never through a shell, always with a
timeout.

CLI: `reproduce.py --round-dir R --cwd W --head <sha>` refuses (exit 2) unless
HEAD in W equals `--head` and tracked code is clean (`tree_scope.tracked_dirty`:
the loop-excluded config and design docs and untracked files are ignored), and
re-checks after running. It merges the manifest replies, writes
`R/tail/findings.json`, appends downgrade and note lines to the manifest's
`log_path` (never decisions.md) and prints
`{blocking, downgraded, inconclusive, notes, tally}`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_SHARED = _HERE.parent.parent / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import tree_scope  # noqa: E402
from argv_runner import OUTPUT_CAP, run_argv, tail as _tail  # noqa: E402,F401 — OUTPUT_CAP re-exported
from finding_class import is_sentinel, note_line, tally, valid_reproducer  # noqa: E402
from review_merge import merge_codereview_angles  # noqa: E402

DEFAULT_TIMEOUT = 120
PYTHON = sys.executable or "python3"
PYTEST_ARGS = ("-m", "pytest", "-q", "-p", "no:cacheprovider")

REPRODUCED = "reproduced"
NOT_REPRODUCED = "not-reproduced"
INCONCLUSIVE = "inconclusive"
LEGACY = "legacy-no-reproducer"


def _run(runner, argv, cwd, timeout):
    """→ (returncode | None, stdout, output<=500). None: the run itself failed."""
    r = run_argv(argv, cwd=cwd, timeout=timeout, runner=runner)
    return r.rc, r.stdout, r.tail


def _outcome_test(repro, i, *, cwd, scratch_dir, runner, timeout):
    scratch = Path(scratch_dir)
    try:
        scratch.mkdir(parents=True, exist_ok=True)
        script = scratch / f"repro_{i}.py"
        script.write_text(repro["source"], encoding="utf-8")
    except OSError as exc:
        return INCONCLUSIVE, _tail(f"could not write reproducer: {exc}")
    rc, _, out = _run(runner, [PYTHON, *PYTEST_ARGS, str(script)], cwd, timeout)
    if rc == 1:
        return REPRODUCED, out
    if rc == 0:
        return NOT_REPRODUCED, out
    return INCONCLUSIVE, out


def _outcome_command(repro, *, cwd, runner, timeout):
    rc, stdout, out = _run(runner, list(repro["argv"]), cwd, timeout)
    if rc is None:
        return INCONCLUSIVE, out
    expect = repro["expect"]
    matched = True
    if "exit" in expect and rc != expect["exit"]:
        matched = False
    if "stdout_contains" in expect and expect["stdout_contains"] not in stdout:
        matched = False
    return (NOT_REPRODUCED if matched else REPRODUCED), out


def _outcome_one(repro, name, *, cwd, scratch_dir, runner, timeout):
    if repro["kind"] == "test":
        return _outcome_test(repro, name, cwd=cwd, scratch_dir=scratch_dir,
                             runner=runner, timeout=timeout)
    return _outcome_command(repro, cwd=cwd, runner=runner, timeout=timeout)


def _outcome_any(f, i, *, cwd, scratch_dir, runner, timeout):
    """The primary reproducer, then any deduped twin's `alt_reproducers`: the first
    REPRODUCED wins; otherwise INCONCLUSIVE beats NOT_REPRODUCED (never fail open)."""
    alts = [r for r in (f.get("alt_reproducers") or ()) if valid_reproducer(r)]
    results = []
    for j, repro in enumerate([f["reproducer"], *alts]):
        name = i if j == 0 else f"{i}_{j}"
        outcome, output = _outcome_one(repro, name, cwd=cwd, scratch_dir=scratch_dir,
                                       runner=runner, timeout=timeout)
        if outcome == REPRODUCED:
            return outcome, output
        results.append((outcome, output))
    inconclusive = [r for r in results if r[0] == INCONCLUSIVE]
    return (inconclusive or results)[0]


def _record(i, finding, reason, output=""):
    return {"index": i, "file": finding.get("file", ""), "reason": reason,
            "output": output}


def run_reproducers(findings, *, cwd, scratch_dir, runner=subprocess.run,
                    timeout=DEFAULT_TIMEOUT, round_dir_mode=True):
    """→ `(findings, downgrades)`: copied findings with outcomes applied, plus one
    `{index, file, reason, output}` record per downgraded or inconclusive finding."""
    out, downgrades = [], []
    for i, orig in enumerate(findings or ()):
        f = dict(orig)
        out.append(f)
        if is_sentinel(f) or f.get("verdict") != "structural":
            continue
        repro = f.get("reproducer")
        if not valid_reproducer(repro):
            if round_dir_mode:
                f.update(blocking=False, verdict="minor", schema_note=LEGACY)
                downgrades.append(_record(i, f, LEGACY))
            continue
        outcome, output = _outcome_any(f, i, cwd=cwd, scratch_dir=scratch_dir,
                                       runner=runner, timeout=timeout)
        if outcome == REPRODUCED:
            continue
        f["downgrade"] = {"reason": outcome, "output": output}
        if outcome == NOT_REPRODUCED:
            f.update(blocking=False, verdict="minor")
        downgrades.append(_record(i, f, outcome, output))
    return out, downgrades


# ---------- CLI ----------


class Refused(Exception):
    """A precondition failed; the CLI exits 2 with this reason."""


def _rev(cwd, rev) -> str:
    """Full SHA of `rev` in `cwd`, or "" when it does not resolve."""
    argv = ["git", "-C", str(cwd), "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _assert_tree(cwd, head, *, after=False):
    actual = _rev(cwd, "HEAD")
    if not actual or actual != _rev(cwd, head):
        raise Refused("head-mismatch")
    try:
        dirty = tree_scope.tracked_dirty(cwd)
    except tree_scope.TreeScopeError as exc:
        raise Refused(f"git-error: {exc}") from exc
    if dirty:
        raise Refused("reproducer-dirtied-tree" if after else "dirty-tracked-code")


def _load_manifest(round_dir: Path) -> dict:
    try:
        manifest = json.loads((round_dir / "angles.json").read_text(encoding="utf-8"))
        if not isinstance(manifest["paths"]["log_path"], str) or "round" not in manifest:
            raise KeyError("paths.log_path / round")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Refused(f"manifest-invalid: {exc}") from exc
    return manifest


def _read_reply(round_dir: Path, entry) -> str:
    """Missing/empty reply → "" (parses as the unparseable sentinel: fail-closed)."""
    try:
        rp = Path(entry["reply_path"])
        rp = rp if rp.is_absolute() else round_dir / rp
        return rp.read_text(encoding="utf-8")
    except (OSError, KeyError, TypeError, UnicodeDecodeError):
        return ""


def _downgrade_line(round_n, finding, reason) -> str:
    rng = finding.get("line_range")
    start = rng[0] if isinstance(rng, (list, tuple)) and rng else 0
    summary = " ".join(str(finding.get("summary") or "").split())[:160]
    return (f"[tp-pr-iterate/downgrade] round {round_n} {reason} "
            f"{finding.get('file', '')}:{start} — {summary}")


def run_cli(round_dir, cwd, head, *, timeout=DEFAULT_TIMEOUT, runner=subprocess.run) -> dict:
    """The round-dir run; raises `Refused` on a failed pre/post tree check."""
    round_dir = Path(round_dir)
    manifest = _load_manifest(round_dir)
    _assert_tree(cwd, head)
    replies = [_read_reply(round_dir, e) for e in manifest.get("angles") or ()]
    tail_dir = round_dir / "tail"
    findings, records = run_reproducers(merge_codereview_angles(replies), cwd=cwd,
                                        scratch_dir=tail_dir, runner=runner, timeout=timeout)
    _assert_tree(cwd, head, after=True)
    round_n = manifest["round"]
    touched = {r["index"] for r in records}
    notes = [f for i, f in enumerate(findings) if i not in touched
             and not is_sentinel(f) and f.get("verdict") != "structural"]
    lines = [_downgrade_line(round_n, findings[r["index"]], r["reason"]) for r in records]
    lines += [note_line(round_n, f) for f in notes]
    tail_dir.mkdir(parents=True, exist_ok=True)
    (tail_dir / "findings.json").write_text(json.dumps(findings, indent=2) + "\n",
                                            encoding="utf-8")
    if lines:
        log_path = Path(manifest["paths"]["log_path"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write("".join(line + "\n" for line in lines))
    t = tally(findings)
    return {"blocking": t["blocking"],
            "downgraded": sum(1 for r in records if r["reason"] != INCONCLUSIVE),
            "inconclusive": sum(1 for r in records if r["reason"] == INCONCLUSIVE),
            "notes": len(notes), "tally": t}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run each blocking finding's reproducer.")
    ap.add_argument("--round-dir", required=True)
    ap.add_argument("--cwd", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = ap.parse_args(argv)
    try:
        summary = run_cli(args.round_dir, args.cwd, args.head, timeout=args.timeout)
    except Refused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 2
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
