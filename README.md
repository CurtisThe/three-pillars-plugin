# three-pillars

A [Claude Code](https://claude.ai/code) plugin that wraps AI-assisted development in structured quality gates — design-first pipelines, council-based deliberation, and session continuity across conversations.

## Install

```
claude plugin marketplace add CurtisThe/three-pillars-plugin
claude plugin install three-pillars@three-pillars-plugin
```

Restart Claude Code. Your 25 skills and 18 council agents are live.

### Optional extras

**Framework instructions** — copy `CLAUDE.md` to `~/.claude/CLAUDE.md` for the TDD pipeline methodology guide. Skills work without it, but CLAUDE.md gives Claude persistent context about the framework across all conversations.

**Status line** — copy `statusline.sh` to `~/.claude/statusline.sh` for a context window progress bar. Add to your `settings.json`:
```json
"statusLine": { "type": "command", "command": "~/.claude/statusline.sh", "padding": 1 }
```

## Why this exists

AI coding assistants are fast. The bottleneck is no longer writing code — it's writing the *right* code. Three-pillars adds the missing layers: a design-first pipeline that forces clarity before implementation, council-based deliberation that stress-tests decisions from multiple angles, and session continuity that preserves context across conversations and machines.

## How it works

**Design documents are the source of truth, tests are the proof, and audits are the gates.** Nothing ships without being traced back to a design and validated against the codebase.

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

## What's included

**25 skills** organized into pipelines:

| Pipeline | Skills | Purpose |
|---|---|---|
| Getting Started | guide, setup | What to do next, test infrastructure configuration |
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

| Command | What it does |
|---|---|
| `/tdd-guide [intent]` | Read project docs and recommend the highest-impact next step |
| `/tdd-setup` | Analyze project stack and configure test infrastructure for the TDD pipeline |

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
| `/tdd-design-complete <name>` | Archive to `docs/completed-tdd-designs/` |

### Project docs

| Command | What it does |
|---|---|
| `/tdd-docs-init` | Scaffold `architecture.md`, `product_roadmap.md`, `known_issues.md` |
| `/tdd-docs-update` | Targeted updates after a milestone |

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
