"""gate_cli.py — deterministic merge gate CLI.

Exit codes:
  0 = PASS  (all predicates passed)
  1 = FAIL  (at least one predicate failed)
  2 = INDETERMINATE (fetch error, empty rollup, null SHA, usage error)

Prints GATE_LABEL on EVERY path (never "safe to merge").
Prints the blocking predicate name + detail on non-PASS paths.

Usage:
  python3 skills/tp-merge/scripts/gate_cli.py <pr_url>

stdlib-only (C1 invariant: no `import anthropic`, no `subprocess.run(["claude", ...])`).
"""

from __future__ import annotations

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
              Exactly one positional <pr_url> is required; this CLI takes no options.
        evaluate_fn: optional injected evaluate function for testing (default: evaluate_gate).

    Returns:
        0 on PASS, 1 on FAIL, 2 on INDETERMINATE / usage-error / gate-could-not-run.
    """
    if evaluate_fn is None:
        evaluate_fn = evaluate_gate

    # Strict parse: the CLI accepts exactly one positional (the PR URL) and no
    # options. No program-name heuristic — argv is already program-name-free, so
    # we never have to guess which token is the script. Extra positionals or any
    # option token are a usage error (fail-closed at 2), never silently dropped.
    flags = [a for a in argv if a.startswith("-")]
    positionals = [a for a in argv if not a.startswith("-")]
    if flags or len(positionals) != 1:
        print(
            "Usage: gate_cli.py <pr_url>\n"
            f"Error: expected exactly one PR URL argument; got argv={argv!r}",
            file=sys.stderr,
        )
        return _indeterminate("usage-error — exactly one <pr_url> argument is required")

    pr_url = positionals[0]

    # Evaluate the gate. evaluate_gate is total, but the CLI must honor
    # "label on every path / exit 2 when the gate cannot run" even if an injected
    # or future evaluate_fn raises. A bare escape would surface as a traceback +
    # exit 1 (mis-read as FAIL) with no label — so map any raise to INDETERMINATE.
    try:
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
