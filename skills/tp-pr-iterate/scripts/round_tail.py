"""round_tail — the round's ordered tail pass over its findings.

design: review-convergence (Task 2.3, detailed-design-pr-loop §B)

Review bar: the CLI used to call `severity.finalize` directly, so severity was the
last word before `origin` existed — a finding's origin could only ever be the
reviewer's guess. `annotate` is the one place the tail runs in its designed order:
origin first, severity last, because severity is the final authority and everything
it reads (`escape`, `reproduction`) must already be in place.

Order (detailed-design-pr-loop §B): 1 origin, 2 disposition audit, 3 severity,
4 round-freeze marker. Step 2 is live: `dispositions` names the impl audit's carry
(`audit-dispositions.json`) and only round 1 reads it — a later round's audit verdict
is stale, so its findings stay as the reviewer filed them. Step 4 stamps `frozen_at`
on a clean round into the manifest's
`paths.state_path` — after severity, because severity decides what "clean" means, and
only when the manifest names a state file (a `round_scratch` caller has none, and the
tail never bootstraps one: `run_round` owns that).

Round 1 has no earlier head, so `first_head` is the reviewed head itself and
`origin_blame.classify` takes its reviewer fallback for every finding. Inputs are
never mutated. Stdlib only.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED = _HERE.parents[1] / "_shared"
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import audit_dispositions  # noqa: E402
import origin_blame  # noqa: E402
import round_freeze  # noqa: E402
import severity  # noqa: E402


def _first_head(manifest, head, rounds_dir) -> str:
    """Round 1's head — the base every later round's fix commits are measured from.

    `rounds_dir` holds the `r<N>/` round dirs (the parent of the round dir). Without
    it, or with no readable manifest in it, or in round 1, the answer is the reviewed
    `head`: blame then finds no fix commits and every finding keeps the reviewer's tag.
    """
    if rounds_dir is None or manifest.get("round") == 1:
        return head
    heads = origin_blame.round_heads(rounds_dir)
    return heads[0] if heads else head


def _state_path(manifest):
    """The manifest's `paths.state_path`, or None when it names no state file.

    `round_scratch prepare` writes a manifest with no `paths` at all; a round run
    through `reproduce.py` always names one. Absent means nothing to mark — never a
    path invented here, because `run_round` owns the state bootstrap.
    """
    paths = manifest.get("paths")
    if not isinstance(paths, dict):
        return None
    return paths.get("state_path")


def annotate(findings, *, manifest, cwd, head, rounds_dir=None, dispositions=None,
             run_git=None) -> list:
    """Return `findings` annotated by the round's tail, severity last.

    `manifest` is the round's `angles.json`, `head` the reviewed head (resolved),
    `rounds_dir` the dir holding the round dirs, `dispositions` the impl audit's
    carry path (round 1 only; any other value is ignored). Never mutates its inputs.
    """
    classified = origin_blame.classify(
        findings, cwd=cwd, head=head,
        first_head=_first_head(manifest, head, rounds_dir), run_git=run_git)
    # Step 2 (§D4): the audit's settled disposition, before severity — so severity
    # sees it and stays the last word. Round 1 only (audit_dispositions.mark).
    if isinstance(dispositions, (str, os.PathLike)):
        classified = audit_dispositions.mark(classified, dispositions, cwd=cwd,
                                             head=head, round_no=manifest.get("round"),
                                             run_git=run_git)
    finalized = severity.finalize(classified)
    # Step 4: severity just decided whether anything blocks, so this is the only
    # place the freeze can be earned. Fail-soft by contract (round_freeze).
    state_path = _state_path(manifest)
    if state_path:
        round_freeze.mark_if_clean(state_path, head, finalized)
    return finalized
