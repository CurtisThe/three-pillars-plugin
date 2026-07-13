"""gc_candidate_branches.py — classifier + reaper for candidate/* branches.

A standalone sibling to gc_candidates.py (which reaps worktrees) and gc_residue.py
(which reaps tp/* and worktree-agent-* branches). This module reaps the
`candidate/*` branch namespace, which gc_residue.py explicitly leaves protected.

Enumerates `candidate/{slug}/{id}` refs from BOTH surfaces — local
(`refs/heads/candidate/*`) and remote-tracking (`refs/remotes/origin/candidate/*`)
— via a single `git for-each-ref` (NOT ls-remote: the age axis needs the tip's
committer date). A ref present on both surfaces yields TWO per-surface rows so the
apply path can delete each surface independently.

Classification predicate (safety-floor-first, per design B2–B6):

    if is_live(slug, cand_id):                 -> protected   (reason=live-candidate)
    elif age_days(tip) > 14:                    -> deletable   (reason=age>14d)
    elif pr_state(tp/{slug}) == MERGED:         -> deletable   (parent + pr_state=MERGED)
    else:                                       -> left-untouched (evidence: pr_state, age)

The live-first exclusion is load-bearing (audit F1): a candidate is branched off
`tp/{slug}` HEAD, so a live candidate whose worker has not yet committed can read
as `age>14d` when the base is old — therefore the live check beats BOTH disjuncts
and is applied FIRST.

Evidence discipline (from gc_residue.py): for the MERGE axis, pr_state.py's PR-state
is the only evidence; UNKNOWN is NEVER MERGED; enumeration / worktree-scan failure is
fail-closed (classify_candidates RAISES so nothing is deleted). The AGE axis is a
self-contained staleness floor (the tip's own committer date, a positive local fact);
a non-numeric/empty committerdate ⇒ age-unknown ⇒ NOT deletable-on-age.

Pure classification lives here; the delete/apply path is gc_candidate_branches_apply.py.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

HERE = Path(__file__).parent
# Relocated into skills/_shared/ so the FREE tp-post-merge teardown can invoke this
# reaper without referencing a pro-tier skill path (release leak guard). pr_state is
# a sibling here, so a single HERE insert suffices.
sys.path.insert(0, str(HERE))

from pr_state import PrVerdict, pr_state  # noqa: E402

# ---------------------------------------------------------------------------
# Patterns / constants
# ---------------------------------------------------------------------------

# Anchored candidate shape: candidate/{slug}/{cand_id}, both [a-z0-9-]+.
# A ref that does not match is silently ignored (namespace guard — never
# mis-delete by guessing at an unrecognized shape; same invariant as
# sweep_candidates.py).
_CANDIDATE_RE = re.compile(r"^candidate/([a-z0-9-]+)/([a-z0-9-]+)$")

_LOCAL_PREFIX = "refs/heads/"
_REMOTE_PREFIX = "refs/remotes/origin/"

_AGE_LIMIT_SECONDS = 14 * 86400  # 14 days


# ---------------------------------------------------------------------------
# Row dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CandidateRef:
    """One enumerated candidate ref, per-surface.

    surface: "local" (refs/heads/...) or "remote" (refs/remotes/origin/...).
    tip_unixtime: the raw `%(committerdate:unix)` token (may be "" — treated as
                  age-unknown downstream).
    """

    branch: str          # candidate/{slug}/{cand_id}
    slug: str
    cand_id: str
    surface: str
    tip_unixtime: str


@dataclass
class CandidateRow:
    """Classification record for one candidate ref.

    classification / action (kept in lock-step):
      protected       — live candidate (never deletable — hard safety exclusion)
      deletable       — parent MERGED, or age > 14d (evidence names the axis)
      left-untouched  — neither disjunct fired (UNKNOWN/OPEN/CLOSED parent, young)

    evidence carries the firing axis: {"axis": "age", "reason": "age>14d", ...}
    or {"axis": "merge", "parent": "tp/{slug}", "pr_state": "MERGED"} — the apply
    path reads `axis` to decide fetch-failure suppression of remote deletes.
    """

    branch: str
    slug: str
    cand_id: str
    surface: str
    classification: str
    action: str
    evidence: dict = field(default_factory=dict)
    pr_verdict: Optional[PrVerdict] = None


# ---------------------------------------------------------------------------
# Enumeration (fail-closed)
# ---------------------------------------------------------------------------


def _for_each_ref(repo: Path) -> str:
    """Enumerate both candidate surfaces via a single git for-each-ref.

    Raises RuntimeError on non-zero exit (fail-closed: we must not classify
    branches as safe-to-delete if we cannot reliably enumerate them).
    """
    result = subprocess.run(
        [
            "git", "for-each-ref",
            "--format=%(refname) %(committerdate:unix)",
            "refs/heads/candidate", "refs/remotes/origin/candidate",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git for-each-ref failed (exit {result.returncode}): "
            f"{result.stderr.strip()!r}. Cannot safely classify candidate "
            "branches without a reliable enumeration."
        )
    return result.stdout


def enumerate_candidate_refs(
    repo: Path, *, slug: Optional[str] = None
) -> list[CandidateRef]:
    """Return one CandidateRef per matching candidate ref across BOTH surfaces.

    A ref present on both surfaces yields two rows (one local, one remote).
    Non-candidate refs and refs not matching `^candidate/[a-z0-9-]+/[a-z0-9-]+$`
    are silently ignored (namespace guard). `slug=` scopes to one design.

    Raises RuntimeError on enumeration failure (fail-closed).
    """
    out = _for_each_ref(repo)
    refs: list[CandidateRef] = []
    for raw in out.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        refname = parts[0]
        tip = parts[1].strip() if len(parts) > 1 else ""

        if refname.startswith(_LOCAL_PREFIX):
            branch = refname[len(_LOCAL_PREFIX):]
            surface = "local"
        elif refname.startswith(_REMOTE_PREFIX):
            branch = refname[len(_REMOTE_PREFIX):]
            surface = "remote"
        else:
            continue

        m = _CANDIDATE_RE.match(branch)
        if not m:
            continue
        ref_slug, cand_id = m.group(1), m.group(2)
        if slug is not None and ref_slug != slug:
            continue
        refs.append(CandidateRef(
            branch=branch,
            slug=ref_slug,
            cand_id=cand_id,
            surface=surface,
            tip_unixtime=tip,
        ))
    return refs


# ---------------------------------------------------------------------------
# Age axis (self-contained staleness floor)
# ---------------------------------------------------------------------------


def _age_deletable(tip_unixtime: str, now: float) -> tuple[bool, Optional[int]]:
    """Return (deletable_on_age, age_days).

    A non-numeric / empty committerdate ⇒ (False, None): age is UNKNOWN, so the
    age disjunct never fires (never a huge-age false positive). The boundary is
    strict `>`: exactly 14 days old is NOT deletable-on-age.
    """
    try:
        tip = float(tip_unixtime)
    except (TypeError, ValueError):
        return (False, None)
    age_seconds = now - tip
    return (age_seconds > _AGE_LIMIT_SECONDS, int(age_seconds // 86400))


# ---------------------------------------------------------------------------
# Live-candidate exclusion via attached worktrees (fail-closed)
# ---------------------------------------------------------------------------


def _live_worktree_slugs(repo: Path) -> set[str]:
    """Return the set of slugs whose parent `tp/{slug}` has an attached worktree.

    A `tp/{slug}` worktree is an in-flight-run signal: its candidate branch(es)
    must be auto-protected. Raises RuntimeError on enumeration failure
    (fail-closed, mirroring gc_residue._live_worktree_branches): if we cannot
    verify worktree attachment we must not classify anything deletable.
    """
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git worktree list failed (exit {result.returncode}): "
            f"{result.stderr.strip()!r}. Cannot safely classify candidate "
            "branches without live-worktree enumeration."
        )
    slugs: set[str] = set()
    for line in result.stdout.splitlines():
        if line.startswith("branch "):
            ref = line[len("branch "):].strip()
            if ref.startswith("refs/heads/tp/"):
                slug = ref[len("refs/heads/tp/"):].strip()
                if slug:
                    slugs.add(slug)
    return slugs


# ---------------------------------------------------------------------------
# Core classifier (safety-floor-first; fail-closed)
# ---------------------------------------------------------------------------


def classify_candidates(
    repo: Path,
    *,
    slug: Optional[str] = None,
    live: "frozenset[tuple[str, str]] | set[tuple[str, str]]" = frozenset(),
    now: Optional[float] = None,
) -> list[CandidateRow]:
    """Classify every candidate ref (both surfaces) per the design predicate.

    `live` is a set of `(slug, cand_id)` tuples that must never be deleted
    (the caller-supplied `--live-candidate` seam). The live check is applied
    FIRST so it beats both the age and merge disjuncts.

    Raises RuntimeError on enumeration failure (fail-closed): nothing is deleted
    if we cannot reliably enumerate.
    """
    if now is None:
        now = time.time()

    refs = enumerate_candidate_refs(repo, slug=slug)  # raises fail-closed
    live_wt_slugs = _live_worktree_slugs(repo)        # raises fail-closed
    live_set = set(live)

    rows: list[CandidateRow] = []
    for ref in refs:
        # --- Safety-floor: live candidate (FIRST — beats both disjuncts) ---
        # Live iff the caller named (slug, cand_id) OR the parent tp/{slug}
        # still has an attached worktree (an in-flight-run signal). Membership
        # on (slug, cand_id) protects BOTH the local and remote rows.
        if (ref.slug, ref.cand_id) in live_set or ref.slug in live_wt_slugs:
            rows.append(CandidateRow(
                branch=ref.branch, slug=ref.slug, cand_id=ref.cand_id,
                surface=ref.surface, classification="protected",
                action="protected", evidence={"reason": "live-candidate"},
            ))
            continue

        # --- Age axis (self-contained staleness floor) ---
        age_del, age_days = _age_deletable(ref.tip_unixtime, now)
        if age_del:
            rows.append(CandidateRow(
                branch=ref.branch, slug=ref.slug, cand_id=ref.cand_id,
                surface=ref.surface, classification="deletable",
                action="deletable",
                evidence={"axis": "age", "reason": "age>14d", "age_days": age_days},
            ))
            continue

        # --- Merge axis (only when age ≤ 14d): pr_state is the ONLY evidence ---
        verdict = pr_state(f"tp/{ref.slug}", cwd=repo)
        if verdict.state == "MERGED":
            rows.append(CandidateRow(
                branch=ref.branch, slug=ref.slug, cand_id=ref.cand_id,
                surface=ref.surface, classification="deletable",
                action="deletable",
                evidence={"axis": "merge", "parent": f"tp/{ref.slug}",
                          "pr_state": "MERGED"},
                pr_verdict=verdict,
            ))
        else:
            # OPEN / CLOSED / NO_PR / UNKNOWN — never deletable on the merge axis.
            rows.append(CandidateRow(
                branch=ref.branch, slug=ref.slug, cand_id=ref.cand_id,
                surface=ref.surface, classification="left-untouched",
                action="left-untouched",
                evidence={"pr_state": verdict.state, "age_days": age_days},
                pr_verdict=verdict,
            ))
    return rows


# ---------------------------------------------------------------------------
# CLI entry point (delegates to gc_candidate_branches_cli — kept thin so this
# classifier module stays under the file-size soft-warn; the runnable path
# remains gc_candidate_branches.py, which the SKILL.md wire-ins invoke).
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    from gc_candidate_branches_cli import main as _cli_main
    return _cli_main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
