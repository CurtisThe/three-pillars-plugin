"""gate_cli.py — deterministic merge gate CLI.

Exit codes:
  0 = PASS  (all predicates passed)
  1 = FAIL  (at least one predicate failed)
  2 = INDETERMINATE (fetch error, empty rollup, null SHA, usage error)

Prints GATE_LABEL on EVERY path (never "safe to merge").
Prints the blocking predicate name + detail on non-PASS paths.

Usage:
  python3 skills/tp-merge/scripts/gate_cli.py [--repo <path>] <pr_url>

`--repo <path>` (task 8.2, dispatch-from-seat activation) is the ONLY recognized
option: it resolves to a git toplevel (`git -C <path> rev-parse --show-toplevel`)
and is threaded to `evaluate_fn(pr_url, repo_root=<resolved>)`. Without it the call
shape is UNCHANGED (`evaluate_fn(pr_url)`) — see SKILL.md step 6.7 for the full
dispatch-from-seat invocation this flag enables.

stdlib-only (C1 invariant: no `import anthropic`, no `subprocess.run(["claude", ...])`).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# ---- sys.path: ensure _shared/ is on path so deterministic_gate is importable ----
_SCRIPTS_DIR = Path(__file__).resolve().parent
_SHARED_DIR = _SCRIPTS_DIR.parent.parent / "_shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

# ---- tp-pr-iterate/scripts for loop_driver (_CI_TERMINAL_CONCLUSIONS) ----
_LOOP_DIR = _SCRIPTS_DIR.parent.parent / "tp-pr-iterate" / "scripts"
if str(_LOOP_DIR) not in sys.path:
    sys.path.insert(0, str(_LOOP_DIR))

from deterministic_gate import (  # noqa: E402
    GATE_LABEL,
    GateVerdict,
    evaluate_gate,
)

# gate_roster is imported lazily below so gate_cli stays importable even in
# environments where gate_roster hasn't been deployed yet.


# Exit code mapping per verdict
_EXIT_CODES = {
    GateVerdict.PASS: 0,
    GateVerdict.FAIL: 1,
    GateVerdict.INDETERMINATE: 2,
}


def _resolve_repo_toplevel(path: str) -> "str | None":
    """Resolve `path` to its git toplevel via `git -C <path> rev-parse --show-toplevel`.

    Returns None on any failure (non-zero exit, git missing, exception) — the
    caller folds that to a usage-error INDETERMINATE (fail-closed, never guesses).
    """
    try:
        result = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            return None
        top = result.stdout.strip()
        return top or None
    except Exception:
        return None


def _parse_argv(argv: list[str]) -> "tuple[str | None, list[str], bool]":
    """Strict parse: `--repo <path>` is the ONLY recognized option.

    Returns (repo_path_or_None, positionals, ok). ok is False on ANY usage
    violation: an unrecognized flag, `--repo` with no following value, or a
    duplicate `--repo`. Extra positionals are NOT a parse-time violation here —
    the caller enforces `len(positionals) == 1` itself (mirrors the pre-existing
    strict-positional-count check).
    """
    repo: "str | None" = None
    positionals: list[str] = []
    ok = True
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--repo":
            if i + 1 >= len(argv) or repo is not None:
                ok = False
                i += 1
                continue
            repo = argv[i + 1]
            i += 2
            continue
        if a.startswith("-"):
            ok = False
            i += 1
            continue
        positionals.append(a)
        i += 1
    return repo, positionals, ok


def _indeterminate(detail: str) -> int:
    """Print the label + an INDETERMINATE block and return exit 2.

    Shared by the usage-error and gate-could-not-run paths so the
    label-on-every-path + exit-2-when-the-gate-cannot-run contract holds
    identically for both.
    """
    print(f"GATE: {GATE_LABEL}")
    print(f"VERDICT: {GateVerdict.INDETERMINATE.value}")
    print("BLOCKING:")
    print(f"  [{detail}]")
    return _EXIT_CODES[GateVerdict.INDETERMINATE]


def main(argv: list[str], *, evaluate_fn=None) -> int:
    """Parse argv, evaluate the gate, print results, return exit code.

    Args:
        argv: the argument list WITHOUT the program name — i.e. ``sys.argv[1:]``
              (which is what ``__main__`` passes and what the tests pass directly).
              Exactly one positional <pr_url> is required; `--repo <path>` is the
              ONLY recognized option (task 8.2).
        evaluate_fn: optional injected evaluate function for testing (default: evaluate_gate).

    Returns:
        0 on PASS, 1 on FAIL, 2 on INDETERMINATE / usage-error / gate-could-not-run.
    """
    if evaluate_fn is None:
        evaluate_fn = evaluate_gate

    # Strict parse: exactly one positional (the PR URL), plus the optional
    # `--repo <path>` flag. Any OTHER flag, `--repo` with no value, a duplicate
    # `--repo`, or extra positionals are a usage error (fail-closed at 2), never
    # silently dropped.
    repo_arg, positionals, ok = _parse_argv(argv)
    if not ok or len(positionals) != 1:
        print(
            "Usage: gate_cli.py [--repo <path>] <pr_url>\n"
            f"Error: expected exactly one PR URL argument (+ optional --repo <path>); "
            f"got argv={argv!r}",
            file=sys.stderr,
        )
        return _indeterminate("usage-error — exactly one <pr_url> argument is required")

    pr_url = positionals[0]

    repo_root = None
    if repo_arg is not None:
        repo_root = _resolve_repo_toplevel(repo_arg)
        if repo_root is None:
            return _indeterminate(
                f"usage-error — --repo {repo_arg!r} did not resolve to a git toplevel"
            )

    # Evaluate the gate. evaluate_gate is total, but the CLI must honor
    # "label on every path / exit 2 when the gate cannot run" even if an injected
    # or future evaluate_fn raises. A bare escape would surface as a traceback +
    # exit 1 (mis-read as FAIL) with no label — so map any raise to INDETERMINATE.
    # Without --repo the call shape is UNCHANGED (evaluate_fn(pr_url)) — injected
    # single-arg test doubles keep working.
    try:
        if repo_root is not None:
            outcome = evaluate_fn(pr_url, repo_root=repo_root)
        else:
            outcome = evaluate_fn(pr_url)
    except Exception as e:  # noqa: BLE001 — fail-closed: any error → INDETERMINATE+label
        return _indeterminate(f"gate-could-not-run — {type(e).__name__}: {e}")

    # Print GATE_LABEL on EVERY path (D6: honest label, never "safe to merge")
    print(f"GATE: {outcome.label}")
    print(f"VERDICT: {outcome.verdict.value}")

    # Print blocking predicate names+details on non-PASS paths
    if outcome.verdict != GateVerdict.PASS:
        print("BLOCKING:")
        for pred in outcome.blocking:
            print(f"  [{pred.name}] {pred.detail}")

    # Print the full predicate roster on EVERY path (PASS, FAIL, INDETERMINATE).
    # Guarded: empty roster on a legacy/injected outcome → print nothing extra
    # (total-function behavior; never crashes if gate_roster is unavailable).
    try:
        import gate_roster  # noqa — in _shared/ beside deterministic_gate
        roster_lines = gate_roster.render_roster(outcome)
        if roster_lines:
            print("ROSTER:")
            for line in roster_lines:
                print(line)
    except Exception:
        pass  # fail-open: roster printing must never block a refusal or a merge

    return _EXIT_CODES.get(outcome.verdict, 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
