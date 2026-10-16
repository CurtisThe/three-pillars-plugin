"""evidence_complete — the §D8 terminal predicate: the round's evidence is in.

design: review-convergence (Task 5.7, detailed-design-pr-loop §D8)

A bookkeeping refusal (a `--state` that resolves elsewhere, a finish that came back
non-zero) on a round that already holds everything an acceptance needs is a
**terminal**, not another round: the operator approves the head with a `tp-accept:`
review-body line instead of paying for a round of paperwork. `check` is that
predicate, and it fails closed — an acceptance posted against the wrong head is
worse than one more round:

- `R/tail/findings.json` is a readable list;
- no finding blocks (`severity.is_blocking`) and none is a degraded sentinel (the
  same test `round_freeze` uses — a degraded review is *missing* evidence, not
  clean evidence);
- >= 1 non-advisory confirmer angle on Claude left a parseable reply
  (`angles.confirmer_ran` over the non-advisory entries — an advisory angle's
  reply is not the evidence an acceptance rests on);
- `git rev-parse HEAD` still equals the manifest's `head`: any git failure, empty
  output or mismatch is NOT complete.
- no required confirmer reply carries a `capped: true` finding (read from the
  confirmer's own reply file, never from `tail/findings.json`); confirmers are not
  capped today (caps companion §1), so this is a defensive guard.

`check` returns `(True, what-the-evidence-is)` or `(False, the clause that failed)`;
the caller supplies its own refusal reason to the emitted terminal.

Stdlib only; the git call is the same injectable seam every converge site uses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import angles  # noqa: E402
import review_proof  # noqa: E402
import round_scratch  # noqa: E402
import severity  # noqa: E402
from finding_class import is_sentinel  # noqa: E402

EXIT_EVIDENCE = 4


def accept_hint(head: str, reason: str) -> str:
    """The line the operator pastes into a review body to accept this head."""
    return f"Approve with a review body line: tp-accept: {head} {reason}"


def _manifest(round_dir) -> "dict | None":
    try:
        doc = json.loads((Path(round_dir) / round_scratch.MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _findings(round_dir) -> "list | None":
    try:
        data = json.loads((Path(round_dir) / round_scratch.TAIL / "findings.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) else None


def _confirmer_reply(manifest: dict, round_dir) -> bool:
    """True iff a non-advisory confirmer on Claude left a parseable reply."""
    real = [e for e in manifest.get("angles") or () if isinstance(e, dict)
            and not e.get("advisory")]
    return angles.confirmer_ran({**manifest, "angles": real}, round_dir)


def _capped_confirmer(manifest: dict, round_dir) -> "str | None":
    """Name of the first non-advisory Claude confirmer whose reply is capped."""
    for entry in manifest.get("angles") or ():
        if not isinstance(entry, dict) or entry.get("advisory"):
            continue
        if entry.get("role") != "confirmer" or angles.tier(entry) != "claude":
            continue
        findings, _parseable = angles.parse_codereview_result(
            angles._reply_text(entry, round_dir))
        if any(f.get("capped") is True for f in findings):
            return str(entry.get("name") or "confirmer")
    return None


def _head(run_git) -> "str | None":
    """`git rev-parse HEAD` via the seam; None on ANY failure (fail closed)."""
    try:
        rc, stdout, _stderr = (run_git or review_proof._default_run_git)(
            ["git", "rev-parse", "HEAD"])
    except Exception as exc:  # noqa: BLE001 — a git that raises is a git that failed
        del exc
        return None
    if rc != 0:
        return None
    return stdout.strip() or None


def check(round_dir, *, run_git=None) -> "tuple[bool, str]":
    """(complete, reason) for the round dir — §D8's evidence-in predicate."""
    manifest = _manifest(round_dir)
    if manifest is None:
        return False, "manifest-unreadable"
    findings = _findings(round_dir)
    if findings is None:
        return False, "findings-unreadable"
    for finding in findings:
        if not isinstance(finding, dict):
            return False, "finding-not-an-object"
        if is_sentinel(finding):
            return False, "degraded-review-sentinel"
        if severity.is_blocking(finding):
            return False, "blocking-finding"
    if not _confirmer_reply(manifest, round_dir):
        return False, "no-parseable-claude-confirmer-reply"
    capped = _capped_confirmer(manifest, round_dir)
    if capped:
        return False, f"capped-confirmer-reply: {capped}"
    head = _head(run_git)
    if head is None:
        return False, "head-unreadable"
    reviewed = str(manifest.get("head") or "")
    if not reviewed or not (head.startswith(reviewed) or reviewed.startswith(head)):
        return False, "head-moved"
    return True, (f"{len(findings)} finding(s), none blocking, no sentinel, a parseable "
                  f"Claude confirmer reply, HEAD still {head}")
