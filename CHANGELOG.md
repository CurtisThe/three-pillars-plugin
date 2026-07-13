# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

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
