# The consumer-repo rule

## Rule

Every enforcement the framework relies on must **ship** and **run** in a user's
repo. The framework's own repo is one user plus dev tooling; a floor that
exists only in the framework's own repo raises nobody's floor.

"Ships" means: the file is on the user's disk after install, per
`.claude-plugin/release-tiers.json` — the ship list. That manifest's
`dev_only_shared` (and `dev_only_paths`, where the manifest declares it)
names the files that stay behind; if a promise's enforcement lives only in
one of those, the promise does not hold for a user.

"Runs" means: some shipped skill, hook, or CLI actually invokes the shipped
file in a user's repo — not just that a copy of it sits on disk unread.

A promise that is easiest to enforce with dev-only tooling is a signal, not
a decision: prefer the shipped floor. Extra checks that only run in the
three-pillars dev repo are fine as belt-and-suspenders there, but they must
never be cited as *the* enforcement a user's repo can rely on.

## Audit question

Ask this of every enforcement a design, plan, or piece of shipped prose
relies on:

> Does this run in a user's repo? Name the shipped file that runs it.

A dev-only answer — naming a file in `dev_only_shared` or `dev_only_paths`,
or a dev-repo-only script — is a finding. So is no answer at all.

## Where this is applied

- **Design floor.** A `floor: 2` design's `design.md` carries a required
  `## Consumer-repo behaviour` section: what ships, what runs in a user's
  repo, and what happens there when an optional piece (tmux, a bot account,
  the local router, a non-pytest runner) is absent.
- **Design and plan audit.** `/tp-design-audit` and `/tp-plan-audit` ask the
  audit question above of every enforcement the design or a plan task
  relies on.
- **Implementation audit.** `/tp-implementation-audit`'s shipped-promises
  dimension flags shipped text in the diff that cites a dev-only mechanism
  as enforcement.
- **Review.** The review checklist item keyed `promises-vs-enforcement`
  flags the same pattern in a pull request's diff.
- **Design-learn.** `/tp-design-learn` records a design's consumer-repo
  behaviour into `architecture.md`, so the floor a design actually shipped
  stays visible after the design is archived.
