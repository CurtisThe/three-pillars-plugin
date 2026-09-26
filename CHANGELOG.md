# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Fixed

## [2.4.0] — 2026-09-26

Batch release of the September hardening waves on top of v2.3.0: audits must now prove a guard binds by watching it go RED and GREEN rather than by reading it, the autonomous PR-review loop gets a written round budget and a reproducer-gated blocking bar, an opt-in `--local` mode sends simple plan tasks to a cheaper model behind a mechanical test oracle, design kickoffs start from a state-space map, and design runs are always launched as their own top-level session. Base-sync, worktree teardown, fleet launches and design completion also get a round of correctness fixes.

### Added

- **Guard certification — audits prove a guard binds** — when `/tp-design-audit`, `/tp-implementation-audit`, `/tp-phase-review` or the autonomous audit fan-out claims a test/check/gate *enforces* a property, a new independent `tp-certifier` agent writes inputs that violate and preserve the property and `certify.py` re-runs them in a throw-away clone to decide the claim mechanically (`binds` / `known-bypass` / `unverified` / `not-binding`); reviews gain a mandatory `## Guards certified` section, certifying phrases without a backing claim are flagged, and verdicts gain `KNOWN BYPASS` and `UNVERIFIED` so an honest partial is no longer forced into PASS.
- **`--local` cheap-tier implementation (opt-in)** — `/tp-phase-implement --local` and `/tp-run-full-design --local` run each plan task through a tier ladder: a new `tp-task-worker` attempts eligible tasks on a cheaper model in an isolated attempt worktree, the task's declared tests are re-run to verify it, and a failure retries then escalates (cheap → Sonnet → Opus); reviews, audits and orchestration stay on Opus. Off unless you set `local_implement.enabled` (plus `local_implement.full_design` for unattended runs) in `.three-pillars/config.json`, tunable via `model`, `fallback_model`, `max_retries`, `max_files` and `escalate`. Routing the cheap rung to a local GPU model needs the separate local-llm-skills backend (`claude-hybrid`); three-pillars only decides which tasks go cheap.
- **`Targets` field on plan tasks** — `/tp-plan` writes a strict, machine-read `**Targets**` line per task (backticked pytest targets, or `none`), validated by `/tp-plan-audit`; it is what `--local` and the post-worker test re-run actually execute. A task without one runs on Opus and is reported unverified.
- **State-space framing for design kickoffs** — `/tp-design` and `/tp-promote` build a state-space map (loci, dimensions, flip test) before asking anything, so confirm blocks ask only questions whose answer changes the design, each with a plain-language problem paragraph; the map persists as `## State space`, an advisory `state_space_lint.py` warns on gaps, and `/tp-design-audit` (and the Slot 4/6 fan-out) adds a map check for better alternatives dismissed without evidence.
- **Round budget for `/tp-pr-iterate`** — the review loop now stops on a written rule: `budget-exhausted` at a round cap with blocking findings still open (default 6), diff growth past 1.5× the round-1 baseline, or a runaway test/code ratio; `cap-exhausted` at a wall clock (default 4h); `convergence-failure` after three consecutive blocking rounds. Limits live under `pdw.guards.*` in `.three-pillars/config.json`, and `review.angles` overrides the default review angles.
- **`/tp-phase-review` lists tasks built below Opus** — for `--local` phases the review lists every task finished on a cheap rung, weakest evidence first (e.g. its test was already green at base).

### Changed

- **Design runs are launched, never hosted** — `/tp-run-full-design` refuses to start inside a parent agent's subagent and prints the launcher command instead; `/tp-promote` now launches the run as its own top-level session in a fresh tmux window via a shared launcher (pinned profile, pre-trusted worktree) instead of chaining into it in the same session, and the pro fleet launcher uses the same path (pro).
- **Reproducer-gated blocking bar in the PR loop** — only a finding that carries a reproducer which actually fails on the reviewed head blocks; one that does not reproduce becomes a non-blocking note, and `/tp-design-complete` lists those notes for the operator. Each round runs in its own per-round, per-angle scratch space, so one angle's cleanup can no longer delete the loop's shared state.
- **Worker test results are verified, not self-reported** — after each `tp-worker` phase, `/tp-run-full-design` re-runs every task's declared Targets at the pushed candidate SHA in a scratch tree and escalates a confirmed red instead of trusting the worker's report.
- **Reviews and audits always run on Opus** — every council persona is pinned to Opus, as are the audit exploration and review-angle subagents.
- **Living-doc hand-resolutions keep the approval** — a base-sync that hand-resolves a semantic living-doc hunk (a status-row flip, a known-issue transition, the `*Last updated:*` preamble) now carries the existing PR approval instead of forcing a re-approval of a PR whose code never changed.
- **Stricter base-sync resolver** — `decision-entry-insertion` conflicts are now auto-resolved, `id-renumber-collision` is withheld and always deferred to a human, the mechanical resolver preserves every input line or defers, and `/tp-merge-from-main` exits 3 when `git merge` itself fails (nothing merged) instead of reporting a conflict.
- **Light designs can resume at build** — `/tp-run-full-design --mode build` on a light design starts at Slot 7 with just `design.md` + `plan.md`, no longer demanding a `detailed-design.md` (and a redone plan audit).
- **Fleet worker launches fail open on monitoring, closed on the payload** (pro) — a liveness sidecar that cannot import `jsonschema` no longer kills the worker before `claude` starts; a launch preflight checks prerequisites, the worker window puts `<wt>/.venv/bin` first on PATH, and `jsonschema` is a listed fleet prerequisite. The running-sessions view shows degraded rows in place and exits 0/2/1 for healthy / liveness-unknown / failed.

### Fixed

- **Worktree garbage collection reaps normally merged worktrees** (pro) — a branch whose upstream was auto-deleted on merge was treated as never-pushed and skipped forever; a landed-evidence ladder (merged PR containing HEAD, else ancestor of a freshly fetched base) now tells the two apart, and nested candidate worktrees are torn down inner-first.
- **`/tp-pr-iterate` first round no longer fails `state-read-failed`** — the round runner bootstraps a fresh iterate state when none exists instead of exiting 2 on the very first round.
- **`/tp-design-complete` stages the completion stamp** — a bundled `git add` with a stale pathspec aborted silently, so the `completed:` stamp never reached the commit; each artifact is now added separately.
- **Zero-drop verifier no longer rubber-stamps unknown shapes** — a mechanically resolved living doc in which it recognizes no entries now reports `UNVERIFIABLE` (exit 2) and defers, instead of a false `ZERO-DROP`.
- **Shared scripts resolve on every install layout** — the FREE `_shared` resolver now also checks `$CLAUDE_PLUGIN_ROOT`, `--skill-dir` and its own location, so `--skill-dir` and non-cache plugin installs no longer fail; an unreadable plugin cache fails loud rather than with a traceback, and SKILL.md call sites check the resolver's exit.
- **`/tp-pr-iterate` dedupe overstated the finding count** — two review angles describing one defect at identical coordinates now collapse to one finding; the survivor keeps the more severe (canonicalized) verdict and any GitHub `thread_id`, anchorless file-level findings and distinct Copilot threads are never merged, and conflict deferral no longer drops every `/code-review` finding in a round. The fix round also actions the loop's own `/code-review` findings instead of deferring them as `non-collaborator`.
- **Fleet monitoring finds worker transcripts** (pro) — transcript paths are now derived the way Claude Code slugs project directories, under the worker's pinned profile.
- **Order/load-dependent test flakes under `-n auto`** — deadline-based assertions in the supervisor and framework-check tests now wait on the condition they prove, and the live framework-check run is marked `serial`.

## [2.3.0] — 2026-07-13

Batch release of a month of fleet-driven hardening on top of v2.2.0: an offline briefing/cockpit for shepherding many parallel runs, a stronger and more portable autonomous merge boundary (head-bound review proof, approval that survives safe base-syncs, retired approval tags), faster autonomous iteration, and correctness fixes for running the framework as an installed plugin against a separate project.

### Added

- **Offline HTML briefing & cockpit** (pro) — self-contained between-wave / parallel-run briefings with per-run cards and a compact paste-back grammar, so the operator can shepherd more runs at once; degrades gracefully to the terminal.
- **`--mode` slot-range axis on `/tp-run-full-design`** — select which pipeline tiers a run executes (e.g. skip design, run only the review/merge tail).
- **Tier-7 convergence primitive** — a single-shot finisher for the autonomous "reviewed-stable" terminal, replacing the ad-hoc per-round shell-out and the trap set that came with it.
- **Candidate-branch reaper** — the worktree `gc` path and `/tp-post-merge` now reap merged `candidate/*` branches behind a backup-ref floor.
- **`/tp-session-restore` resolves completed designs** — restoring an archived design frames it as completed (with its completion date) instead of reporting "nothing to restore".

### Changed

- **Autonomous workers default to Opus** — previously Sonnet.
- **Push-after-commit is the default** — each artifact commit is pushed to `origin` fail-open (a failed push is logged, never blocks the commit); the PR boundary is unchanged, opening a PR still happens only at `/tp-design-complete`.
- **Stronger, more portable autonomous merge boundary** — the gate now requires a **head-bound review proof** each round; **human approval survives mechanically-safe base-syncs** (no re-approval tax when only auto-resolvable living-doc classes changed); the legacy `APPROVED`-tag approval path was **retired** in favor of the deterministic gate; and PRs can be authored by a machine account so a human review is always the distinct approver.
- **Plugin-mode parity** — fixed framework behaviors that assumed the operated-on repo is the framework's own checkout, so an installed plugin now works correctly against a separate project.
- **Faster autonomous iteration** — a fast CI lane trims the inner red-green loop; fleet workers wire into it.
- **Steadier fleet operation** — more reliable parallel launches, clean tmux teardown, and briefing-server keepalive/reaping.
- **Base-sync auto-resolves more living-doc conflict classes** (prepend/append-log) behind the zero-drop verifier; free `_shared` helper scripts now resolve on any install layout, not just the dev checkout.
- **Corrected tier documentation** — the README/CLAUDE variants now derive their tier claims from the release manifest: the merge (`/tp-merge`, `/tp-merge-from-main`) and autonomous PR-loop (`/tp-pr-fix`, `/tp-pr-iterate`) skills are free; the parallel-worktree and fleet-orchestration skills are the paid tier.
- Additional enforcement / quality hardening: shipped-surface currency invariant, plan-audit hardening, design-complete stamp guard, distinct audit lock phases, spike-evidence versioning, and a shared project-context primitive.

### Fixed

- `/tp-session-restore` no longer reports "nothing to restore" for a completed (archived) design.
- Stale agent-worktree branches left by fleet runs are now cleaned up.

## [2.2.0] — 2026-06-16

Batch release of the W4–W8 trust / safety / quality hardening waves on top of v2.1.0: a new recovery skill, deeper autonomous-run automation, and five new fail-closed enforcement invariants that make the autonomous merge boundary — and the paper trail around it — portable and self-checking.

### Added

- **`/tp-revert`** (free) — land a clean, single-commit revert of a merged design through the standard merge gate, with a depth/forecast probe that refuses-with-reality on deep or conflict-laden reverts. The recovery arm of the fleet-safety barbell.
- **Weight-class design-depth axis** — four classes (`just-do-it` / `light` / `spike` / `full`) scale ceremony to the size of the change while keeping every check-level; `/tp-plan-audit --light` runs one merged council pass for small changes.
- **Sanctioned hot-patch lane** — a seat-exempt single-commit path for fast direct-to-default-branch fixes, with an append-only ledger and a new enforcement invariant so unsanctioned traffic becomes observable.
- **Offline HTML briefing for `/tp-promote`** — a self-contained between-wave briefing with per-seed cards and a compact paste-back answer grammar; degrades gracefully to the terminal confirm.
- **Record / replay for the autonomous orchestrator** — capture and re-drive an offline run trajectory behind a fail-closed secret/PII filter, seeding offline regression for the loop.
- **Self-rescheduling run-monitor loop** — polls a running parallel batch, re-renders the cross-run digest each tick, and stops at settled-or-in-trouble, closing the hands-off gap between launch and merge.
- **Branch-residue cleanup + seat immunization** — the worktree-management skill safely removes residue branches behind a backup-ref floor and offers consent-gated immunization against the harness `core.bare` config bleed.
- **Reply-and-resolve thread disposition** — a shared helper plus a dispose-only path decouples PR-thread resolution from the iteration loop; the merge gate names the dispose gesture when a thread predicate blocks.

### Changed

- **The autonomous merge boundary is now portable and provenance-checked** — gate config reads from committed HEAD, a sixth predicate requires a fresh local-CI stamp, the enforcement layer resolves its root on any install (not just the dev machine), and `git commit --no-verify` is denied.
- **Human approval is ergonomic and current-on-head** — approval is carried in a SHA-tagged label *or* a native `APPROVED` PR review, both verified human-actor and current on the head commit; a single-account collision is detected with flip guidance.
- **The backward paper trail self-reconciles after merges** — archived designs, stale status rows, and rotted invariant citations are repaired by a dated-amendment protocol and a new citation-coherence invariant; invariant numbers are now append-only.
- **Enforced file-size caps** (500 lines / 50 000 chars, either axis) via a shared guard behind both the pre-commit hook and a framework-check invariant.
- **Collision-aware merge sequencing** for parallel batches, plus an `orchestrator:<email>` lock-owner identity so a human and their own orchestrator count as one actor.

## [2.1.0] — 2026-06-09

Batch release of the W1–W3 design waves on top of v2.0.0: new free pipeline skills, the workspace-topology layer, and a hardened autonomous fleet/merge path.

### Added

- **`/tp-spec`** (free) — living-spec layer: a `three-pillars-docs/specs/<domain>/spec.md` current-truth tree with `add`/`validate`/`merge`, plus a deterministic drift guard so the second source of truth can't silently diverge.
- **`/tp-promote`** (free) — promote a `seed.md` to a committed, floor-clearing `design.md`, ready for a design-ready fleet pass.
- **`/tp-merge-from-main`** (free) — base-sync skill: merge the base branch *into* a design worktree and auto-resolve the safe living-doc conflict classes behind a zero-drop verifier, re-test, and re-push.
- **Workspace-topology layer** — a derived, self-checking git-worktree *seat* model with an offered (never automatic) repair path; the `/tp-post-merge`, `/tp-merge-from-main`, `/tp-design`, and `/tp-spike` skills are now topology-aware. Closes the `core.bare=true` footgun that could strand a teardown.

### Changed

- **`/tp-merge`** is now the irreversible **land gate**: it enforces `require_merge_gate_pass` (mechanical predicates including a current human approval) and runs `gh pr merge` only on PASS. The former base-sync behavior moved to `/tp-merge-from-main`.
- **Hardened the autonomous fleet / PR-iteration path** — a fail-closed PASS/FAIL/INDETERMINATE deterministic merge gate, worktree-isolation guards for parallel runs, a real independent `/code-review` arm in `/tp-pr-iterate`, and fleet promote automation.

## [2.0.0] — 2026-06-05

First public ship of the parallel-design-workflow / orchestrator / pro-tier / fleet arc: 2 agents (`tp-readonly-auditor`, `tp-worker`), the parallel-design worktree skill triad, the autonomous orchestrator `/tp-run-full-design`, the open-core pro-tier machinery (including the parallel-fleet launcher), and council orchestrator mode.

## [1.5.0] — 2026-05-27

The **first canon-shaped release.** Pre-v1.5.0 versions (v1.0.0–v1.4.1) shipped a Claude Code plugin framework; v1.5.0 reframes the repo as a tri-purpose artifact (methodology canon + Claude Code reference implementation + Hermes-distribution source) per the 2026-05-25 federated-Hermes pivot and the 2026-05-26 distribution-model decision.

### Added

- **Top-level `README.md`** rewritten for tri-purpose canon framing — the canon (methodology writing), the Claude Code reference implementation (`skills/` + `agents/`), and the source for the auto-generated Hermes distribution at `CurtisThe/three-pillars-hermes`.
- **`CHANGELOG.md`** at repo root (this file). Forward-looking from v1.5.0; pre-canon history captured in `git log` and archived design artifacts.
- **`LICENSE`** confirmed at repo root (Apache 2.0). Was present in pre-v1.5.0 releases; this entry records the canon-shape verification.
- **IP-1 posture** documented: design artifacts under `three-pillars-docs/tp-designs/` stay private to maintainers; the v1.5.0 public surface is the methodology canon + reference implementation only. Future worked examples (v1.7.0+) author fresh content rather than publishing the private originals.
- **Planned for upcoming releases** (named here for forward visibility):
  - `METHODOLOGY.md` — detailed methodology authoring (target v1.6.0 or v1.7.0)
  - `adoption/via-claude-code.md` — the legacy-path adoption guide (target v1.6.0)
  - `adoption/via-hermes-skills.md` — the Hermes-path adoption guide (target v1.8.0, gated on `CurtisThe/three-pillars-hermes` existing)
  - `adoption/via-other-agents.md` — generic methodology porting (target v1.8.0+)
  - `examples/d17-readme-rename/` and `examples/d19-hook-abandonment/` — worked examples authored fresh (targets v1.7.0 and v1.9.0)
  - `scripts/build-hermes-distribution.py` + `.github/workflows/build-hermes-distribution.yml` — release-time build pipeline that transforms this repo's `skills/` into a Hermes-installable package and force-pushes to `CurtisThe/three-pillars-hermes`. Planned for v1.5.x or v1.6.0.

### Changed

- **`CONTRIBUTING.md`** rewritten for canon posture: PRs welcome for typo and broken-link fixes; substantive content changes route through GitHub issues for alignment with `three-pillars-docs/vision.md`; skill and agent code changes go through the project's own TDD pipeline (`/tp-design` → `/tp-design-detail` → … → `/tp-design-complete`).
- **Plugin manifest version** bumped from `1.4.1` to `1.5.0` (additive minor — canon framing is additive content, not breaking).

---

Pre-v1.5.0 history captured in `git log` and archived design artifacts under `three-pillars-docs/completed-tp-designs/`.

[Unreleased]: https://github.com/CurtisThe/three-pillars-plugin/compare/v1.5.0...HEAD
[1.5.0]: https://github.com/CurtisThe/three-pillars-plugin/compare/v1.4.1...v1.5.0
