"""gate_roster.py — Full predicate roster for evaluate_gate output.

Every gate run — including PASS — enumerates each predicate evaluated with its
verdict (PASS / FAIL / INDETERMINATE / OMITTED). The library owns roster
semantics; gate_cli and land.py only print.

Symbols:
  RosterEntry             — frozen dataclass for a single predicate's verdict
  render_roster(outcome)  — list[str] of human-readable lines

The rendering never implies semantic verification ("safe to merge" wording is
absent by design — see GATE_LABEL in deterministic_gate.py).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deterministic_gate import GateOutcome, PredicateResult

# Ensure _shared/ is on sys.path
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from project_root import find_project_root  # noqa: E402
from diff_balloon_guard import derive_base_ref  # noqa: E402

# Valid status values for RosterEntry
_VALID_STATUSES = frozenset({"PASS", "FAIL", "INDETERMINATE", "OMITTED"})


@dataclass(frozen=True)
class RosterEntry:
    """A single predicate's verdict in the full roster.

    name:   predicate name (e.g. 'threads', 'human_approved', 'ci_local_stamp')
    status: one of PASS | FAIL | INDETERMINATE | OMITTED
    detail: the predicate's detail string (or omission reason)
    """
    name: str
    status: str
    detail: str

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                f"RosterEntry.status must be one of {sorted(_VALID_STATUSES)}, "
                f"got {self.status!r}"
            )

    @classmethod
    def from_result(cls, result: "PredicateResult") -> "RosterEntry":
        """Map a PredicateResult to a RosterEntry.

        PASS  → status='PASS'
        FAIL  → status='FAIL'
        INDETERMINATE → status='INDETERMINATE'
        """
        from deterministic_gate import GateVerdict
        verdict_to_status = {
            GateVerdict.PASS: "PASS",
            GateVerdict.FAIL: "FAIL",
            GateVerdict.INDETERMINATE: "INDETERMINATE",
        }
        status = verdict_to_status.get(result.verdict, "INDETERMINATE")
        return cls(name=result.name, status=status, detail=result.detail or "")

    @classmethod
    def omitted(cls, name: str, *, reason: str) -> "RosterEntry":
        """Create an OMITTED entry with the owning config key or seam reason.

        Examples:
          RosterEntry.omitted('copilot', reason='review.expects_copilot=false')
          RosterEntry.omitted('ci_local_stamp', reason='<stamp> inactive (hermetic run)')
        """
        return cls(name=name, status="OMITTED", detail=reason)


def build_predicates_and_roster(
    *,
    pr_url: str,
    rollup: list,
    failure_class,
    threads,
    mergeable,
    head_oid: str,
    config: dict,
    r: dict,
    copilot_runners,
    running_live: bool,
    shared_dir,
) -> "tuple[list, list]":
    """Evaluate all gate predicates and build the roster entries list.

    Returns (predicates, roster_entries) in canonical order:
      threads, mergeable, checks, diff_not_ballooned, copilot, human, ci_local_stamp.

    Extracted from evaluate_gate in deterministic_gate.py to keep that function
    readable and to stay within the 800-line file-size cap.
    Behavior is byte-identical to the original inline version.
    """
    import subprocess
    import sys
    from pathlib import Path

    # Late imports to avoid circular dependency (gate_roster is imported by deterministic_gate)
    from deterministic_gate import (
        pred_threads_resolved,
        pred_mergeable,
        pred_checks_success,
        pred_copilot_on_head,
        pred_human_approved,
        _expects_github_checks,
        _expects_copilot_review,
        _diff_balloon_factor,
        GateVerdict,
        PredicateResult,
    )
    from human_approval import _require_human_approval  # noqa

    # Resolve project root from the invocation cwd's repo (not the module path).
    # Both the balloon predicate and the stamp predicate use this root.
    _project_root = find_project_root()

    p1 = pred_threads_resolved(threads)
    p2 = pred_mergeable(mergeable)
    p3 = pred_checks_success(
        rollup,
        failure_class,
        expects_github_checks=_expects_github_checks(config),
    )
    predicates = [p1, p2, p3]
    roster_entries: list = [
        RosterEntry.from_result(p1),
        RosterEntry.from_result(p2),
        RosterEntry.from_result(p3),
    ]

    # p_balloon: active when balloon_sizes key present OR pure live mode
    if "balloon_sizes" in r or running_live:
        import diff_balloon_guard  # noqa
        _injected_sizes = r.get("balloon_sizes", None)
        if _injected_sizes is not None:
            # Hermetic path: sizes injected directly, no root/base resolution needed
            _p_balloon = diff_balloon_guard.pred_diff_not_ballooned(
                repo=".",
                base_ref="master",
                head_ref=head_oid,
                factor=_diff_balloon_factor(config),
                sizes=_injected_sizes,
            )
        else:
            # Live path: resolve project root + base ref, then measure.
            # Remote name is always "origin" — framework convention: the gate
            # reads the project under operation, which is always checked out with
            # an "origin" remote by the framework's branch-per-design convention.
            # Non-origin clones are not a supported configuration.
            _derive_base_ref_fn = r.get("derive_base_ref_fn", None)
            if _project_root is None:
                _p_balloon = PredicateResult(
                    name="diff_not_ballooned",
                    verdict=GateVerdict.INDETERMINATE,
                    detail="could not resolve project root for diff balloon measurement",
                )
            else:
                _base = (
                    _derive_base_ref_fn(pr_url)
                    if _derive_base_ref_fn is not None
                    else derive_base_ref(pr_url)
                )
                if _base is None:
                    _p_balloon = PredicateResult(
                        name="diff_not_ballooned",
                        verdict=GateVerdict.INDETERMINATE,
                        detail="could not resolve base ref for diff balloon measurement",
                    )
                else:
                    # Fetch origin/<base> so the ref exists locally.
                    # "origin" is the framework-convention remote name.
                    _fetch = subprocess.run(
                        ["git", "-C", str(_project_root), "fetch", "origin", _base],
                        capture_output=True, text=True, check=False,
                    )
                    if _fetch.returncode != 0:
                        _p_balloon = PredicateResult(
                            name="diff_not_ballooned",
                            verdict=GateVerdict.INDETERMINATE,
                            detail=(
                                f"could not fetch origin/{_base} for diff balloon "
                                f"measurement: {_fetch.stderr.strip()}"
                            ),
                        )
                    else:
                        _p_balloon = diff_balloon_guard.pred_diff_not_ballooned(
                            repo=str(_project_root),
                            base_ref=f"origin/{_base}",
                            head_ref=head_oid,
                            factor=_diff_balloon_factor(config),
                            sizes=None,
                        )
        predicates.append(_p_balloon)
        roster_entries.append(RosterEntry.from_result(_p_balloon))
    else:
        roster_entries.append(RosterEntry.omitted(
            "diff_not_ballooned",
            reason="<balloon> inactive (hermetic run — no balloon_sizes injected)",
        ))

    # p4 (Copilot): OMITTED when review.expects_copilot=false
    if _expects_copilot_review(config):
        _p_copilot = pred_copilot_on_head(pr_url, runners=copilot_runners)
        predicates.append(_p_copilot)
        roster_entries.append(RosterEntry.from_result(_p_copilot))
    else:
        roster_entries.append(RosterEntry.omitted(
            "copilot_on_head", reason="review.expects_copilot=false",
        ))

    # p5 (human approval): OMITTED when require_human_approval resolves false
    if _require_human_approval(config):
        _p_human = pred_human_approved(pr_url, runners=r, config=config)
        predicates.append(_p_human)
        roster_entries.append(RosterEntry.from_result(_p_human))
    else:
        roster_entries.append(RosterEntry.omitted(
            "human_approved", reason="review.require_human_approval=false",
        ))

    # p6 (ci-local stamp): active when stamp key present OR pure live mode.
    # The stamp predicate receives the project root resolved above.
    # Hermetic carve-out: when a stamp is injected the predicate evaluates entirely
    # from the injected dict (repo_root is not read), so check _stamp_key_present
    # BEFORE the _project_root-is-None guard — mirrors the balloon's injected-sizes
    # carve-out so hermetic stamp injection works from a non-repo cwd.
    _stamp_key_present = "stamp" in r
    if _stamp_key_present or running_live:
        import ci_local_stamp  # noqa
        if _stamp_key_present:
            # Hermetic path: stamp injected directly — no repo_root access needed.
            # Pass a sentinel repo_root so the signature is satisfied; it is never read.
            _p_stamp = ci_local_stamp.pred_ci_local_stamp(
                head_oid, repo_root=str(_project_root or "."), stamp=r["stamp"],
            )
        elif _project_root is None:
            _p_stamp = PredicateResult(
                name="ci_local_stamp",
                verdict=GateVerdict.INDETERMINATE,
                detail="could not resolve project root for ci_local_stamp",
            )
        else:
            _p_stamp = ci_local_stamp.pred_ci_local_stamp(
                head_oid, repo_root=str(_project_root),
            )
        predicates.append(_p_stamp)
        roster_entries.append(RosterEntry.from_result(_p_stamp))
    else:
        roster_entries.append(RosterEntry.omitted(
            "ci_local_stamp",
            reason="<stamp> inactive (hermetic run — no stamp key injected)",
        ))

    return predicates, roster_entries


def render_roster(outcome: "GateOutcome") -> "list[str]":
    """Render the roster from a GateOutcome as a list of human-readable lines.

    One line per predicate entry + a summary line.

    PASS with ≥1 OMITTED renders a visually distinct summary:
      VERDICT: PASS (N predicate(s) OMITTED)

    Empty roster returns an empty list (no crash; gate_cli guards empty case).

    Never uses "safe to merge" wording — the gate only proves mechanical
    predicates; semantic verification is the reviewer's responsibility.
    """
    roster = getattr(outcome, "roster", None) or ()
    if not roster:
        return []

    lines = []
    omitted_count = sum(1 for e in roster if e.status == "OMITTED")

    for entry in roster:
        icon = {
            "PASS": "[PASS]",
            "FAIL": "[FAIL]",
            "INDETERMINATE": "[INDET]",
            "OMITTED": "[OMIT]",
        }.get(entry.status, f"[{entry.status}]")

        detail_part = f" — {entry.detail}" if entry.detail else ""
        lines.append(f"  {icon} {entry.name}{detail_part}")

    # Summary line
    from deterministic_gate import GateVerdict
    verdict = outcome.verdict
    if verdict == GateVerdict.PASS and omitted_count > 0:
        lines.append(
            f"VERDICT: PASS ({omitted_count} predicate(s) OMITTED — "
            "predicate omissions do not imply semantic verification)"
        )
    else:
        lines.append(f"VERDICT: {verdict.value}")

    return lines
