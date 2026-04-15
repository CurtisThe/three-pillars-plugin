# three-pillars

A [Claude Code](https://claude.ai/code) plugin that wraps AI-assisted development in structured quality gates — design-first pipelines, council-based deliberation, and session continuity across conversations.

## Install

**Prerequisites**: [Claude Code](https://claude.ai/code) installed on your machine.

Two commands in your terminal:

```bash
claude plugin marketplace add CurtisThe/three-pillars-plugin
claude plugin install three-pillars@three-pillars-plugin
```

Restart Claude Code. That's it — 27 skills and 18 council agents are live.

**Verify** by typing `/tdd-guide` in any project. If the skill runs, you're set.

## Update

Releases ship new skills, bug fixes, and refinements. Check the [releases page](https://github.com/CurtisThe/three-pillars-plugin/releases) or the top of the commit log to see what's new.

```bash
claude plugin update three-pillars@three-pillars-plugin
```

Restart Claude Code after updating so the new skills are loaded. Your existing designs, plans, and session state are untouched — updates only replace the plugin's own files (`skills/`, `agents/`, `CLAUDE.md`, etc.).

## Uninstall

```bash
claude plugin uninstall three-pillars@three-pillars-plugin
claude plugin marketplace remove CurtisThe/three-pillars-plugin
```

Your project's `docs/tdd-designs/` directories are **not** removed — those belong to your project, not the plugin.

### Optional extras

Both extras are **optional**. The plugin's core features (skills, agents, session management) work without them.

**Framework instructions** — copy `CLAUDE.md` to `~/.claude/CLAUDE.md` for the TDD pipeline methodology guide. Skills work without it, but CLAUDE.md gives Claude persistent context about the framework across all conversations.

**Status line** — a bash script that shows your context-window usage, active design, and git status in Claude Code's status line.

The plugin's shipped `settings.json` already references `~/.claude/statusline.sh`:
```json
"statusLine": { "type": "command", "command": "~/.claude/statusline.sh", "padding": 1 }
```

To enable it, copy the script into place (one-time, manual):
```bash
cp statusline.sh ~/.claude/statusline.sh
chmod +x ~/.claude/statusline.sh
```

**If you skip this step:** nothing breaks. Claude Code will try to run the command, silently fail (file not found), and render an empty status line. No functionality is lost.

**Why `~/.claude/` and not inside the project?** The status line is a user-global Claude Code feature, not per-project. It lives next to your user-wide `settings.json` and applies to every Claude Code session. The `statusline.sh` script itself is read-only: it reads git status, file-existence checks for `.claude/last-design` and `docs/tdd-designs/`, and formats the output for your terminal. No network requests. No writes. See `statusline.sh` for the source (it's ~200 lines of bash).

**Reviewer note:** if you're auditing this plugin, the `~/.claude/statusline.sh` path in `settings.json` is a user-scoped external dependency with graceful failure, not a silent install hook. It requires explicit user action to enable.

## Why this exists

AI coding assistants are fast. The bottleneck is no longer writing code — it's writing the *right* code. Three-pillars adds the missing layers: a design-first pipeline that forces clarity before implementation, council-based deliberation that stress-tests decisions from multiple angles, and session continuity that preserves context across conversations and machines.

## How it works

**`docs/vision.md` is the "why", design documents are the source of truth, tests are the proof, and audits are the gates.** Nothing ships without being traced back to a design that serves the vision and validated against the codebase. Every skill reads vision first and uses it as the tie-breaker when technical options are equivalent.

**Typical flow for a feature:**
```
/tdd-design auth-revamp          # Interactive design conversation → design.md
/tdd-design-detail auth-revamp   # Concrete modules, interfaces, test boundaries → detailed-design.md
/tdd-design-audit auth-revamp    # Council reviews design against codebase — before any code
/tdd-plan auth-revamp            # Sequenced tasks with test criteria → plan.md
/tdd-plan-audit auth-revamp      # Verify plan traces fully to design — catch gaps and creep
/tdd-phase-implement auth-revamp 1  # Red-green-refactor cycles, parallel agents for independent tasks
/tdd-phase-review auth-revamp 1     # Review against design; flag regressions
/tdd-implementation-audit auth-revamp  # Final audit: does the code match what was designed?
```

**When you're not sure an approach will work**, spike first:
```
/tdd-spike websocket-scaling     # Frame hypothesis and success criteria
/tdd-spike-auto websocket-scaling  # Autonomous: plan → audit → implement → results
# Review decisions.md the next morning, then:
/tdd-spike-learn websocket-scaling   # Feed learnings back into project docs
```

**Context survives across conversations:**
```
/tdd-session-save auth-revamp    # Saves working state to handoff.md (gitignored, local-only)
# Close the conversation, switch machines, come back later:
/tdd-session-restore auth-revamp # Full continuity — no re-explaining
```

**Collaboration** — works solo, scales to teams:

- **Branch-per-design**: each design or spike lives on its own branch, `tdd/<design-name>`. Skills prompt to create the branch if you start on `main`, and push it to `origin` immediately on creation so teammates see in-flight work without waiting for the first commit.
- **Advisory lock**: `docs/tdd-designs/<name>/lock.json` records who holds the design and on which branch. Committed to git — parallel work produces a merge conflict at PR time, which forces a conversation instead of silently merging divergent implementations.
- **Takeover**: if the holder abandons the design, the next developer passes `--force-takeover` to claim it; the prior holder is preserved in `previous_owners[]` for history.
- **Graceful handoff**: the holder can run `/tdd-design-release <name>` to step away cleanly — `owner` goes to `null`, and the next person claims the design without needing `--force-takeover`.
- **Remote-aware**: lock-enforcing skills `git fetch` at the start of each preflight, so they catch teammates' claims that were pushed but not yet pulled locally. Offline-tolerant — the check fails open.

**What the framework handles vs. what you still need**: this framework enforces **ownership** — who currently holds a claimed design and whether a parallel claim is allowed. It does not handle **assignment** — who should be working on what in the first place. That lives in your existing planning tool (Jira, Asana, Linear, GitHub Projects, a whiteboard, Slack). As long as your team coordinates assignments there, the lock here catches accidental overlap and abandoned work without trying to replace the planning system. Aspirational future: hooks or MCP servers could sync lock state with those external tools — out of scope today, but a direction the framework can grow into.

Lock-enforcing skills (design, spike, detail, plan, audits, implement, review) refuse to proceed if another developer holds the lock. Read-only skills (`/tdd-session-restore`, learn/guide) inspect the lock and warn but never block. See `skills/_shared/collaboration.md` for the full protocol.

### Commits at every phase

Every skill that produces substantial work commits before returning — design.md, plan.md, per-task code, review.md, audit results, learn updates. One commit per task during `/tdd-phase-implement`. Commits are scoped (never `git add -A`), conventionally named (`Design: <name> high-level`, `Plan: <name>`, `Implement: <name> 1.2 — title`, `Learn: <name> design`, etc.), and never include Co-Authored-By trailers. The working tree stays clean between phases. Pushing and opening a PR happens only at `/tdd-design-complete`. See `skills/_shared/commit-after-work.md` for the full protocol.

## What's included

**27 skills** organized into pipelines:

| Pipeline | Skills | Purpose |
|---|---|---|
| Getting Started | guide, setup, test-setup | Vision draw-out, project doc scaffolding, test infrastructure configuration |
| TDD Design | design, design-detail, design-audit | Design documents and review |
| TDD Planning | plan, plan-audit | Task sequencing and verification |
| TDD Implementation | phase-implement, task-cycle, phase-review, implementation-audit | Red-green-refactor execution |
| Spike | spike, spike-plan, spike-implement, spike-results, spike-learn, spike-auto | Hypothesis-driven experiments |
| Design Lifecycle | design-learn, design-complete | Post-implementation synthesis and archival |
| Project Docs | docs-init, docs-update | Living documentation maintenance |
| Session | session-save, session-restore, session-clear | Cross-conversation continuity |
| Infrastructure | council | Multi-persona deliberation |

**18 council agents** — Aristotle, Feynman, Torvalds, Taleb, Kahneman, Meadows, and others. Used by `/council` for standalone deliberation and automatically by audit skills.

## Skills reference

Most skills take a `<design-name>` as their first argument, corresponding to a directory under `docs/tdd-designs/`.

### Getting started

Fresh-project setup follows a deliberate order — **why** before **how**, **how** before **tests**:

| Command | What it does |
|---|---|
| `/tdd-setup` | Conversational draw-out of the project's "why" into `docs/vision.md`. Vision only — no test-runner decisions. Run this first on any new project. |
| `/tdd-docs-init` | Scaffold `architecture.md`, `product_roadmap.md`, `known_issues.md` from codebase analysis, using the vision as context. |
| `/tdd-test-setup` | Configure test infrastructure (runner, layout, permissions, starter test) informed by `architecture.md`. Runs *after* docs-init so the test choices are grounded in the documented system structure. |
| `/tdd-guide [intent]` | Read project docs (vision first) and recommend the highest-impact next step. Weighs recommendations against the stated vision. |

### Design phase

| Command | What it does |
|---|---|
| `/tdd-design <name>` | Interactive conversation that produces `design.md` |
| `/tdd-design-detail <name>` | Translates `design.md` into `detailed-design.md` — modules, interfaces, test boundaries |
| `/tdd-design-audit <name>` | Multi-angle review of the detailed design against the codebase |

### Planning phase

| Command | What it does |
|---|---|
| `/tdd-plan <name>` | Generates `plan.md` — sequenced tasks with test criteria, grouped by phase |
| `/tdd-plan-audit <name>` | Verifies plan traces fully to both design documents |

### Implementation phase

| Command | What it does |
|---|---|
| `/tdd-phase-implement <name> [phase]` | Executes a phase via red-green-refactor cycles |
| `/tdd-task-cycle <name> <phase.task>` | Single red-green-refactor cycle for one task |
| `/tdd-phase-review <name> [phase]` | Reviews completed phase against design and plan |
| `/tdd-implementation-audit <name>` | Final audit — does the code match what was designed? |

### Spike pipeline

| Command | What it does |
|---|---|
| `/tdd-spike <name>` | Frame a hypothesis and success criteria |
| `/tdd-spike-plan <name>` | Lightweight experiment plan from the spike design |
| `/tdd-spike-implement <name>` | Execute experiments with human review gates |
| `/tdd-spike-results <name>` | Capture findings and verdict |
| `/tdd-spike-learn <name>` | Synthesize learnings into project docs |
| `/tdd-spike-auto <name>` | Autonomous end-to-end spike execution |

### Design lifecycle

| Command | What it does |
|---|---|
| `/tdd-design-learn <name>` | Synthesize a design's impact into project docs |
| `/tdd-design-release <name>` | Release your lock without completing — graceful handoff to a teammate |
| `/tdd-design-complete <name>` | Archive to `docs/completed-tdd-designs/`, commit, and offer a PR back to the base branch |

### Project docs

| Command | What it does |
|---|---|
| `/tdd-docs-init` | Scaffold `architecture.md`, `product_roadmap.md`, `known_issues.md` (assumes `docs/vision.md` already exists via `/tdd-setup`) |
| `/tdd-docs-update [vision\|architecture\|roadmap\|known-issues]` | Targeted updates after a milestone. Vision updates follow a sticky-vision protocol — do not drift the vision to match implementation. |

### Session management

| Command | What it does |
|---|---|
| `/tdd-session-save <name>` | Save context to `handoff.md` for cross-conversation continuity |
| `/tdd-session-restore [name]` | Restore context at start of a new conversation |
| `/tdd-session-clear <name>` | Clear stale context when switching tasks |

### Council of High Intelligence

`/council` convenes multi-persona deliberation for complex decisions. 18 reasoning personas analyze problems from independent angles, cross-examine each other, and produce synthesized recommendations.

Modes: full (18 members, 3 rounds), quick (fast 2-round), duo (2-member dialectic), or auto-triad (system picks the best 3).

## License

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution.

| Component | License | Source |
|---|---|---|
| Council of High Intelligence | MIT | [0xNyk/council-of-high-intelligence](https://github.com/0xNyk/council-of-high-intelligence) |
