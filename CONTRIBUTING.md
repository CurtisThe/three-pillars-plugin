# Contributing

Three-pillars is a tri-purpose project — methodology canon, Claude Code reference implementation, and source for the auto-generated Hermes distribution. Contributions are welcome, with posture varying by change type. The single rule across all change types: nothing ships that contradicts [`three-pillars-docs/vision.md`](three-pillars-docs/vision.md), the project's source of truth for what this exists to do.

## Posture by change type

**Typo fixes, broken-link fixes, clarifying prose edits** — open a pull request directly. Small, mechanical, low-risk; the maintainer applies and re-syncs. No issue needed first.

**Substantive content changes** (new methodology guidance, new persona definitions, new worked examples, restructuring an existing section) — open a GitHub issue first to discuss alignment with `vision.md`. The maintainer reviews against the vision's stated problem, users, principles, and non-goals. Approved proposals then proceed as a pull request.

**Skill or agent code changes** (anything under `skills/` or `agents/`) — these go through the project's own TDD pipeline (`/tp-design` → `/tp-design-detail` → `/tp-design-audit` → `/tp-plan` → `/tp-plan-audit` → `/tp-phase-implement` → `/tp-design-complete`). External contributors open an issue describing the desired behavior change; the maintainer (or contributor, with maintainer guidance) opens the design and walks it through the pipeline. The discipline applies equally to internal and external work.

**Methodology canon additions** (e.g., a future `METHODOLOGY.md` revision, an `adoption/` guide, an `examples/` worked example) — these are released on a monthly cadence (see `CHANGELOG.md`). Substantive proposals can be filed as issues; the maintainer schedules them into an upcoming release rather than landing them immediately.

## How to file an issue

1. Brief problem statement — what's wrong or missing, in 1–3 sentences.
2. Why it matters — connect to a `vision.md` problem, principle, or success signal.
3. Proposed approach (if you have one) — high-level, not implementation-detailed.
4. Whether you'd like to draft the PR yourself or hand off to the maintainer.

The maintainer responds with one of: accept (proceed to PR or schedule into a release), shape (suggest a different approach), or decline (with rationale tied to `vision.md`).

## How to file a pull request

For typo and link-fix PRs: open directly, reference the issue if any. Maintainer merges to dev repo, then re-syncs.

For substantive PRs (post-issue-approval): open against the dev repo's main branch, target the agreed-upon design name or content path. Include a brief description of what changed and why, with a link to the approving issue.

## What lives where

This repository (the public `CurtisThe/three-pillars-plugin` repo) is a **published distribution** synced from a private dev repo via `release.sh`. The dev repo is the source of truth; this repo carries an allowlisted snapshot suitable for `claude plugin install`.

| In this (public) repo | In the dev repo |
|---|---|
| `README.md`, `LICENSE`, `CHANGELOG.md`, `CONTRIBUTING.md` | Same files (source); `README.md` generated from `README.plugin.md` |
| `skills/`, `agents/`, `.claude-plugin/`, `settings.json`, `statusline.sh` | Source of truth for everything above |
| `CLAUDE.md` | Generated from dev's `CLAUDE.plugin.md` |
| Nothing else | Project docs (`three-pillars-docs/`), design artifacts, dev tooling, tests, `release.sh` |

Direct edits to this repo land as proposals for the dev repo. The next release sync will reflect the merged state.

## License

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution.
