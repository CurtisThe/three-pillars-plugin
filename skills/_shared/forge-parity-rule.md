# The forge-parity rule

## Rule

A design that touches a **forge surface** carries a `## Forge behaviour`
section. The framework runs on more than one forge (GitHub and Gitea), and a
feature that only works on one of them must say so rather than fail quietly on
the other.

A forge surface is any place the framework talks to the forge: a PR create,
read, comment, label or merge; the review loop; the merge gate; CI status;
branch protection; notifications. `FORGE_SURFACES` in
`skills/_shared/forge_floor.py` is the canonical keyword list: the floor check
reads a design's prose for those keywords, so that table is the whole input
domain.

The section states three things:

- **GitHub behaviour** — what the feature does on GitHub.
- **Gitea behaviour** — what it does on Gitea.
- **The visible degraded path** — what the user sees when a forge or backend
  cannot do it. A degraded path that is silent is a failure of the rule, not a
  way of meeting it: Gitea degrades *visibly* (a printed line, a non-zero exit
  with a reason, a recorded skip), never as a quiet no-op.

Forge calls go through the interface in `skills/_shared/forge.py`, not through
`gh` or `tea` called inline. A github.com-only path in shipped code is a
finding for the same reason a silent no-op is: it works on one forge and does
nothing on the other.

## Audit question

Ask this of every forge surface a design, plan, or piece of shipped prose
relies on:

> For each forge surface this relies on: what happens on GitHub, what on
> Gitea, and is the Gitea degraded path visible? Does it go through `forge.py`?

A silent Gitea no-op, a github.com-only path, or a direct `gh` call outside
`forge.py` is a finding. So is no answer at all.

## Where this is applied

- **Design floor.** A `floor: 3` design's `design.md` carries a required
  `## Forge behaviour` section whenever its prose names a forge surface
  (`FORGE_SURFACES`). `skills/_shared/forge_floor.py` is the check; a design
  that names no forge surface omits the section.
- **Design and plan audit.** `/tp-design-audit` and `/tp-plan-audit` ask the
  audit question beside the consumer-repo question. A silent Gitea no-op or a
  github.com-only path is MEDIUM in the design audit and INCONSISTENT in the
  plan audit.
- **Implementation audit.** `/tp-implementation-audit`'s shipped-promises
  dimension reads the diff for a silent Gitea no-op or a github.com-only path
  and files it as a shipped-promises finding.
- **Review.** The review checklist item keyed `forge-parity` flags the same
  pattern in a pull request's diff.
- **Dev-repo scan.** A warn-only invariant in the three-pillars dev repo, the
  forge call-site scan (forge-interface Task 2.4), flags direct `gh` calls
  outside `forge.py`. It is belt-and-suspenders there, never the enforcement a
  user's repo relies on, per `skills/_shared/consumer-repo-rule.md`.
