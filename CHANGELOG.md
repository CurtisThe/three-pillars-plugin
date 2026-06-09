# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

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
