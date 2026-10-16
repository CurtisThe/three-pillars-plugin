"""round_plan — which angles a round runs, and the base it reviews against.

design: review-convergence (Tasks 4.2-4.4, 4.6, detailed-design-pr-loop §D3)

Review bar: round 1 reviews the whole PR; every later round reviews only the
**fix delta** since the last round that actually produced a review. Two primitives
own that: `prior_reviewed_head` picks the base (the newest prior round whose
`tail/findings.json` is not degraded-only and whose head differs from the head
being prepared — so a `.1` rerun-review on the same head inherits its parent's
base and its delta is never empty), and `delta_text` renders that range as the
loop's own changes: the patches of `origin_blame.fix_commits` plus, for each
first-parent **merge**, only its hand-resolution hunks
(`git show --remerge-diff`). A base sync contributes nothing but the loop's
resolution, so a base author's new call site can never turn the security lens on
for a delta round.

`plan` is the entry point: it derives the round number from the round dirs (cold
resume, like `round_scratch.prepare`). Round 1 (`mode: full`) returns the full-PR
angle set — the loaded finders (one `combined` finder when the PR diff is under
`SMALL_DIFF_LINES`), the Opus check, and the `security` angle appended always, so
no `config.review.angles` can drop the lens or name an angle twice. Round n ≥ 2
(`mode: delta`) returns exactly ONE angle, `delta_check_angle`, based on
`prior_reviewed_head`: no finders, no Opus check, no rulings. Its lens is the
detector over `delta_text` — never over the range, which a base sync pollutes. A
round prepared at the very head the last round reviewed (a fix round with no
applicable fixes commits nothing) inherits that round's own base and findings
(`_same_head_round`); a round with neither raises `PlanRefused` instead of silently
widening back to the full diff.

Stdlib only. `run_git` is `origin_blame`'s seam over `git -C <cwd> <args>` and is
reused unchanged, so one fake git drives both modules in tests.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_SHARED = _HERE.parent.parent / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import angles  # noqa: E402
import finder_round  # noqa: E402
import iterate_state  # noqa: E402
import review_loop_forge  # noqa: E402
import round_budget  # noqa: E402
import trust_boundary  # noqa: E402
from finding_class import tally  # noqa: E402
from origin_blame import _default_run_git, fix_commits  # noqa: E402

# A round-1 PR diff below this many counted lines collapses its finders to one.
SMALL_DIFF_LINES = 300
# The single angle a delta round (round n >= 2) runs.
DELTA_CHECK = "delta-check"
# The one finder a small (round 1) diff runs.
COMBINED = "combined"

MANIFEST = "angles.json"  # the round manifest (round_scratch.MANIFEST)
FINDINGS = "tail/findings.json"  # the reproducer's output (round_mix.FINDINGS)

_ROUND_DIR = re.compile(r"^r(\d+)(\.1)?$")


class PlanRefused(ValueError):
    """`plan` will not prepare this round; the message starts `prepare-refused: `."""


def _git(run_git, cwd, *args):
    return (run_git or _default_run_git)(cwd, list(args))


def _round_dirs(rounds_dir) -> list[Path]:
    """Every `r<N>[.1]` round dir under `rounds_dir`, newest round first."""
    try:
        entries = list(Path(rounds_dir).iterdir())
    except OSError:
        return []
    keyed = []
    for entry in entries:
        match = _ROUND_DIR.match(entry.name)
        if not match or not entry.is_dir():
            continue
        keyed.append(((int(match.group(1)), 1 if match.group(2) else 0), entry))
    return [entry for _, entry in sorted(keyed, key=lambda pair: pair[0],
                                         reverse=True)]


def _manifest_str(entry: Path, key: str) -> str:
    """The manifest's string `key`, or "" when missing, unreadable or not a string."""
    try:
        manifest = json.loads((entry / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = manifest.get(key) if isinstance(manifest, dict) else None
    return value if isinstance(value, str) else ""


def _manifest_head(entry: Path) -> str:
    """The manifest's `head`, or "" when the manifest is missing or unreadable."""
    return _manifest_str(entry, "head")


def _findings(entry: Path):
    """The round's tail findings list, or None when absent / unreadable / not a list."""
    try:
        data = json.loads((entry / FINDINGS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) else None


def _degraded_only(findings) -> bool:
    """True when the round produced sentinels and no blocker: nothing was reviewed."""
    counts = tally(findings)
    return counts["blocking"] == 0 and counts["degraded"] > 0


def _prior_round(rounds_dir, head):
    """The newest prior round that qualifies as a base, or None when none does.

    A round qualifies when its manifest names a head, that head differs from `head`,
    and its findings exist and are not degraded-only. A same-head round (a `.1`
    rerun-review, or a re-prepare after a clean review) is therefore skipped and the
    base inherits the round before it.
    """
    for entry in _round_dirs(rounds_dir):
        prior = _manifest_head(entry)
        if not prior or prior == head:
            continue
        findings = _findings(entry)
        if findings is None or _degraded_only(findings):
            continue
        return entry
    return None


def prior_reviewed_head(rounds_dir, head) -> str | None:
    """The base a delta round reviews against, or None when no prior round qualifies.

    The head of `_prior_round`: newest round first, so a `.1` rerun-review inherits
    its parent's base and the delta is never empty.
    """
    entry = _prior_round(rounds_dir, head)
    return _manifest_head(entry) if entry is not None else None


def _same_head_round(rounds_dir, head):
    """The newest round that reviewed `head` itself, with its reviewed base — or None.

    Same-head inheritance (the `.1` rule, generalised): a fix round with no applicable
    fixes makes no commit, so the next round is prepared at the very head the last
    round reviewed and `_prior_round` finds nothing. Such a round qualifies when its
    findings exist and are not degraded-only and its manifest names a `base` other
    than `head`; the new round then re-reviews that same range against its findings.
    A manifest without `base` (or a lost / degraded rounds dir) never qualifies, so
    the plan still refuses. → `(entry, base)`.
    """
    if not head:
        return None
    for entry in _round_dirs(rounds_dir):
        if _manifest_head(entry) != head:
            continue
        findings = _findings(entry)
        if findings is None or _degraded_only(findings):
            continue
        base = _manifest_str(entry, "base")
        if base and base != head:
            return entry, base
    return None


def _is_merge(run_git, cwd, sha: str) -> bool:
    """True when `sha` has more than one parent (a sync merge, in practice)."""
    rc, out = _git(run_git, cwd, "rev-list", "--parents", "-n1", sha)
    if rc != 0:
        return False
    return len(out.split()) > 2


def _patch(run_git, cwd, sha: str, *flags) -> str:
    rc, out = _git(run_git, cwd, "show", *flags, "--format=", sha)
    return out.strip("\n") if rc == 0 and out.strip() else ""


def delta_text(repo, prior, head, *, run_git=None) -> str:
    """The loop's own changes between `prior` and `head`, as one patch text.

    First-parent walk, oldest first: a fix commit contributes its patch; a merge
    contributes only its hand-resolution hunks, never the base commits it brings in.
    "" when the range is empty or git fails.
    """
    if not prior or not head or prior == head:
        return ""
    rc, out = _git(run_git, repo, "rev-list", "--first-parent", "--reverse",
                   f"{prior}..{head}")
    if rc != 0:
        return ""
    shas = [line.strip() for line in out.splitlines() if line.strip()]
    fixes = fix_commits(repo, prior, head, run_git=run_git)
    parts = []
    for sha in shas:
        if _is_merge(run_git, repo, sha):
            part = _patch(run_git, repo, sha, "--remerge-diff")
        elif sha in fixes:
            part = _patch(run_git, repo, sha, "--patch")
        else:
            part = ""
        if part:
            parts.append(part)
    return "\n".join(parts)


def combined(loaded) -> list:
    """One `combined` angle from several: their prompts joined, the first one's stance.

    A small round-1 diff runs one finder instead of three, so it reads one prompt
    covering every focus. The role/model come from the FIRST angle (the round's
    stance — a cheap round's finders are all the same engine), and an `advisory`
    mark rides along only when the first angle carries it, so the Opus check stays
    the only thing that can block.
    """
    first = loaded[0]
    one = {"name": COMBINED, "prompt": "; ".join(a["prompt"] for a in loaded),
           "role": first["role"], "model": first["model"]}
    if first.get("advisory"):
        one["advisory"] = True
    return [one]


def _rounds_dir(root, pr_url) -> Path:
    """The PR's rounds dir — the one `round_scratch.prepare` writes its round into."""
    import round_scratch  # noqa: PLC0415 — lazy: round_scratch imports this module

    return Path(root) / "rounds" / round_scratch._pr_number(pr_url)


def _round_number(root, pr_url) -> int:
    """The round being prepared: derived from the round dirs, like `prepare` does.

    `round_scratch` is imported lazily — it will import this module (Task 4.6), so a
    module-level cycle must not exist. A missing or empty rounds dir is round 1.
    """
    import round_scratch  # noqa: PLC0415 — lazy: round_scratch imports this module

    return round_scratch._next_ordinal(_rounds_dir(root, pr_url))[0]


def delta_check_angle(prior_findings_path, *, security_brief=None) -> dict:
    """The ONE angle a delta round runs: the fix delta, plus the prior round's findings.

    `prior_findings_path` is the base round's `tail/findings.json` — the blockers whose
    closure this round exists to report. `security_brief` is passed only when the delta
    touched a trust boundary; without it the prompt carries neither the brief path nor
    `SECURITY_BAR`, so a plain fix delta is not reviewed as a security change.
    """
    prompt = (
        "Review ONLY the fix delta of this round's range, never the whole PR: each "
        "first-parent non-merge commit contributes its patch, and each first-parent "
        "merge contributes only its hand resolution "
        f"(`git show --remerge-diff <merge>`) — never the base changes a sync merge "
        f"brings in. Read the prior round's findings at {prior_findings_path} and, for "
        "each prior blocker, say closed or not: re-emit an open one as your own "
        "finding. Flag any new defect in the delta.")
    if security_brief:
        prompt += (f" Read the security brief at {security_brief}. "
                   f"{trust_boundary.SECURITY_BAR}")
    return {"name": DELTA_CHECK, "role": "confirmer", "model": "opus", "prompt": prompt}


def _delta_plan(rounds_dir, *, n, repo, pr_base, head, run_git=None) -> dict:
    """Round n ≥ 2: one delta-check angle, based on the last round that reviewed.

    The lens is the detector over `delta_text` — the loop's own patch text — because a
    plain range read would report a sync merge's base changes. Any detector failure
    turns the lens ON: the round fails toward review, never away from it. When no
    prior round reviewed a different head, a round that reviewed THIS head lends its
    own base and findings (`_same_head_round`); with neither (a lost or degraded rounds
    dir, a manifest without `base`) the plan refuses rather than silently widening to
    the full diff.
    """
    prior = _prior_round(rounds_dir, head)
    if prior is not None:
        base = _manifest_head(prior)
    else:
        same = _same_head_round(rounds_dir, head)
        if same is None:
            raise PlanRefused("prepare-refused: no prior reviewed head")
        prior, base = same
    try:
        touched = bool(trust_boundary.surfaces(
            delta_text(repo, base, head, run_git=run_git)))
    except Exception:  # any detector failure: the lens stays on
        touched = True
    return {"round": n, "base": base, "pr_base": str(pr_base), "mode": "delta",
            "angles": [delta_check_angle(
                prior / FINDINGS,
                security_brief=trust_boundary.brief_path(repo) if touched else None)],
            "security": touched, "diff_lines": _diff_lines(repo, pr_base, head)}


def _round_one_angles(config, *, repo, pr_base, head, diff_lines, rulings_path, scope,
                      available) -> list:
    """Round 1's angle list: the finders (collapsed when small), the check, security.

    The `security` angle replaces any loaded angle of that name — a config that
    declares one would otherwise put the same name in the round dir twice — and is
    appended last whatever the detector found: a detector failure leaves the lens ON
    with no surfaces, which is the fail-closed reading of an unreadable diff.
    """
    entries = finder_round.round_angles(
        config, root=repo, scope=scope, rulings_path=rulings_path,
        **({} if available is None else {"available": available}))
    if isinstance(diff_lines, int) and diff_lines < SMALL_DIFF_LINES:
        finders = [a for a in entries
                   if a["name"] != finder_round.CHECK_NAME and not a.get("skipped")]
        kept = [a for a in entries
                if a["name"] == finder_round.CHECK_NAME or a.get("skipped")]
        entries = combined(finders) + kept if finders else kept
    entries = [a for a in entries if a["name"] != angles.SECURITY_ANGLE]
    try:
        surfaces = trust_boundary.surfaces_for_range(repo, pr_base, head, three_dot=True)
    except Exception:  # any detector failure: the lens stays on, with no surfaces
        surfaces = []
    return entries + [angles.security_angle(trust_boundary.brief_path(repo), surfaces)]


def _diff_lines(repo, pr_base, head):
    """Counted lines of the whole PR diff (`three-pillars-docs/**` excluded), or None.

    `None` when the measure cannot be taken (fake shas outside a git repo, a git
    failure): the plan fails **toward review** — an unknown size never collapses the
    finders to one `combined` angle, so a PR nobody measured gets the full lens.
    """
    try:
        rows = round_budget.git_numstat(pr_base, head, cwd=repo)
    except round_budget.BudgetError:
        return None
    return round_budget.split(rows)["total"]


def _stamp_review_weight(state_path, review_weight) -> None:
    """Record the round's review weight in iterate-state — read-modify-write.

    Runs only after the plan is computed, so a refused round leaves the state as it
    found it. An **absent state file stays absent** — bootstrapping iterate-state is
    `load_or_bootstrap`'s job, never the plan's.
    """
    if not review_weight or not state_path:
        return
    path = Path(state_path)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # absent (or unreadable): nothing to merge into
        return
    if not isinstance(state, dict):
        return
    state["review_weight"] = review_weight
    iterate_state.write_state_atomic(path, state)


def plan(config, *, root, pr_url, pr_base, head, repo=".", rulings_path=None,
         scope=None, review_weight=None, state_path=None, available=None,
         run_git=None) -> dict:
    """The round's plan: its number, the base it reviews, its angles, its lens.

    `mode: full` (round 1) reviews the whole PR from `pr_base`; `mode: delta`
    (round n ≥ 2) reviews only the fix delta since the last round that reviewed, and
    refuses with `PlanRefused` when no prior round qualifies. `diff_lines` is the
    whole PR either way — the growth budget measures the PR, not the delta.
    `review_weight` + `state_path` stamp the weight into iterate-state once the plan
    exists (see `_stamp_review_weight`). A `ValueError` from the angle layer (a cheap
    round without rulings, an unknown `scope` name) propagates.
    """
    cause = review_loop_forge.gitea_cause(repo)
    if cause is not None:
        raise PlanRefused(cause)
    n = _round_number(root, pr_url)
    if n >= 2:
        out = _delta_plan(_rounds_dir(root, pr_url), n=n, repo=repo, pr_base=pr_base,
                          head=head, run_git=run_git)
    else:
        diff_lines = _diff_lines(repo, pr_base, head)
        entries = _round_one_angles(config, repo=repo, pr_base=pr_base, head=head,
                                    diff_lines=diff_lines, rulings_path=rulings_path,
                                    scope=scope, available=available)
        out = {"round": 1, "base": str(pr_base), "pr_base": str(pr_base),
               "mode": "full", "angles": entries, "security": True,
               "diff_lines": diff_lines}
    _stamp_review_weight(state_path, review_weight)
    return out
