"""review_loop_forge — the one cause line naming why the loop refuses Gitea.

design: review-convergence (Task 11.3, detailed-design-gates §E3)

The review loop and the deterministic merge gate are GitHub-shaped today: the
loop plans GitHub-shaped rounds and the gate's predicates read GitHub-shaped PR
state. On a Gitea origin neither can PROVE anything, so both must say so with
the SAME named cause instead of degrading silently. `gitea_cause` is that line;
the two call sites that make it visible are the gate's null-head INDETERMINATE
detail and `round_plan.plan`'s up-front refusal. The work that removes the
refusal is the separate `gitea-forge-adapter` design, named in the text so the
operator sees the path forward rather than a dead end.

Total by construction: any error from `forge.resolve` (no git, missing repo,
unreadable config) returns None and never raises — a missing observation must
not become a refusal the loop cannot explain. Stdlib only.
"""
from __future__ import annotations

# The exact, shared cause text. Never reword in a call site — one string, so the
# loop's refusal and the gate's detail line name the same thing.
GITEA_CAUSE = ("gate: forge gitea not supported by review loop "
               "(gitea-forge-adapter)")


def gitea_cause(repo_root) -> "str | None":
    """`GITEA_CAUSE` when `repo_root`'s origin resolves to Gitea, else None.

    Reads the repo's own `.three-pillars/config.json` (a configured `forge.kind`
    settles the kind, so a fixture or a configured repo resolves with no probe).
    """
    try:
        import forge  # noqa — in _shared/ beside this file
        info = forge.resolve(repo_root)
    except Exception:  # noqa — total: no observation, so no claim
        return None
    return GITEA_CAUSE if getattr(info, "kind", "") == "gitea" else None
