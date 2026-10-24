# three-pillars

Three-pillars is the published canon for design-first AI-assisted development. **One repo, three purposes**: methodology writing (the canon), a [Claude Code](https://claude.ai/code) reference implementation (`skills/` + `agents/`, installable today), and the source for the auto-generated Hermes distribution at `CurtisThe/three-pillars-hermes` (build pipeline planned, see [CHANGELOG.md](CHANGELOG.md)). The methodology is durable; the implementations propagate from it.

The discipline: design before plan before code, with council-based deliberation and audit gates at every phase. The bet: AI lets you ship code fast — three-pillars makes sure you're shipping the *right* code.

## Install

### Let your AI set it up

Do you use an AI coding assistant (Claude Code, Cursor, Codex, ...)? Paste this into it:

> Set up the three-pillars plugin for Claude Code on this computer for me: https://github.com/CurtisThe/three-pillars-plugin - follow the "For AI assistants" section of README.md in that repository.

It checks for `git`, `gh` and Python, adds the plugin marketplace, installs the plugin, and tells you how to load it.

### Or do it yourself

Pick **one** route per Claude account. A plugin added in the desktop app also syncs into Claude Code (as `three-pillars@synced`), so installing it both ways gives you every skill twice.

#### Claude Code (terminal)

**Prerequisites**: [Claude Code](https://claude.ai/code), `git`, GitHub CLI (`gh`) and Python 3.

In your shell:

```bash
claude plugin marketplace add CurtisThe/three-pillars-plugin
claude plugin install three-pillars@three-pillars
```

Or inside a Claude Code session:

```
/plugin marketplace add CurtisThe/three-pillars-plugin
/plugin install three-pillars@three-pillars
```

The in-session `/plugin install` opens the plugin panel; choose a scope there (**user** makes it available in every project). Then run `/reload-plugins`, or start a new session. 40 skills and their agents are now live.

To share it with everyone working in one repo, add `--scope project` to the shell commands. That records the marketplace and plugin in the repo's `.claude/settings.json`.

##### Run your main session inside tmux

Autonomous design runs open each run as its own tmux session, linked into the session you launched from. Start Claude Code inside tmux: `tmux new -s <repo>`, then `claude` (or `claude --continue` to keep a conversation). Without tmux the launcher stops and prints a manual command. Interactive skills work without it.

#### Claude desktop app

The desktop app (Mac and Windows) has two places that take plugins.

- **Cowork and chat** — open **Customize → Plugins → Add → Add marketplace**, enter `CurtisThe/three-pillars-plugin`, then install **three-pillars** from the list. The plugin syncs to your Claude account, and Claude Code on any machine signed in to that account sees it as `three-pillars@synced`.
- **Code tab** — local Code-tab sessions use the same plugins as Claude Code on that machine. Either add the marketplace from the account (above), or type `/plugin marketplace add CurtisThe/three-pillars-plugin` in a Code-tab session. Then click **+** next to the prompt box → **Plugins** → **Add plugin** and pick **three-pillars**. **Manage plugins** in the same menu turns it off or removes it. Plugins are not available in cloud sessions or WSL.

#### Manual install (no marketplace)

For trying a checkout or working offline:

```bash
git clone https://github.com/CurtisThe/three-pillars-plugin ~/three-pillars-plugin

# One session only (shows as three-pillars@inline):
claude --plugin-dir ~/three-pillars-plugin

# Or keep it installed from the local clone:
claude plugin marketplace add ~/three-pillars-plugin
claude plugin install three-pillars@three-pillars
```

A local marketplace is read in place, so `git pull` in the clone followed by `/reload-plugins` picks up a new release. Cloning alone does nothing: Claude Code does not scan arbitrary folders for plugins.

### For AI assistants

Steps for an AI agent installing this plugin for a person:

1. Check that `claude`, `git`, `gh` and `python3` are on the PATH. If `python3 -c "import jsonschema"` fails, run `pip install jsonschema` (a few skills need it). Claude Code plugins never install Python packages themselves.
2. Run `claude plugin marketplace add CurtisThe/three-pillars-plugin`, then `claude plugin install three-pillars@three-pillars`. Use these shell forms: the in-session `/plugin install` opens a panel and waits for the person to pick a scope.
3. The plugin ID is `three-pillars@three-pillars`. The part after `@` is the marketplace `name` from `.claude-plugin/marketplace.json`, not the repo name `three-pillars-plugin`.
4. Do not also install `three-pillars-pro`. It already contains every core skill, so both together give duplicate skills.
5. If `claude plugin list` already shows `three-pillars@synced`, it is installed through the person's account (desktop app). Stop there and do not install a second copy.
6. Tell the person to run `/reload-plugins` or start a new Claude Code session, then type `/tp-guide` in a project to confirm it works.

### Verify

Type `/tp-guide` in any project. If the skill runs, you're set. `claude plugin list` shows the installed version.

## Update

Releases ship new skills, bug fixes, and refinements. See [CHANGELOG.md](CHANGELOG.md) or the [releases page](https://github.com/CurtisThe/three-pillars-plugin/releases) for what's new.

```bash
claude plugin marketplace update three-pillars
claude plugin update three-pillars@three-pillars
```

Then run `/reload-plugins` or start a new session. Auto-update is off by default for third-party marketplaces; turn it on in `/plugin` → **Marketplaces** → **three-pillars** → **Enable auto-update**. A desktop-app install updates from **Customize → Plugins**.

Updates only replace the plugin's own files (`skills/`, `agents/`, `CLAUDE.md`, etc.). Your designs, plans and session state are untouched.

## Uninstall

```bash
claude plugin uninstall three-pillars@three-pillars
claude plugin marketplace remove three-pillars
```

Removing the marketplace also uninstalls its plugins. In the desktop app, remove it from **Customize → Plugins** (or **+ → Plugins → Manage plugins** in the Code tab).

Your project's `three-pillars-docs/` directories are **not** removed. Those belong to your project, not the plugin.

## Optional extras

Both extras are **optional**. The plugin's core features (skills, agents, session management) work without them.

**Framework instructions** — copy `CLAUDE.md` to `~/.claude/CLAUDE.md` for the TDD pipeline methodology guide. Skills work without it, but CLAUDE.md gives Claude persistent context about the framework across all conversations.

**Status line** — a bash script that shows your context-window usage, active design, and git status in Claude Code's status line.

Claude Code reads only the `agent` and `subagentStatusLine` keys from a plugin's `settings.json` and ignores every other key there, so the plugin's own `statusLine` entry does nothing. The status line needs an entry in your **user** settings, `~/.claude/settings.json`:
```json
"statusLine": { "type": "command", "command": "~/.claude/statusline.sh", "padding": 1 }
```

To enable it, copy the script into place and add that entry (one-time, manual):
```bash
cp statusline.sh ~/.claude/statusline.sh
chmod +x ~/.claude/statusline.sh
```

**If you skip this step:** nothing breaks. With no user-settings entry there is simply no status line; with the entry but no script, the command fails silently and the status line renders empty. No functionality is lost.

The same holds for the plugin's `permissions` block: its `git commit --no-verify` deny is not applied from the plugin. The first-run preflight offers to add that deny to your project's `.claude/settings.json` instead.

**Why `~/.claude/` and not inside the project?** The status line is a user-global Claude Code feature, not per-project. It lives next to your user-wide `settings.json` and applies to every Claude Code session. The `statusline.sh` script itself is read-only: it reads git status, file-existence checks for `.claude/last-design` and `three-pillars-docs/tp-designs/`, and formats the output for your terminal. No network requests. No writes. See `statusline.sh` for the source (it's ~200 lines of bash).

**Reviewer note:** if you're auditing this plugin, the `~/.claude/statusline.sh` path in its `settings.json` is inert (Claude Code ignores that key in a plugin) and a user-scoped external dependency with graceful failure, not a silent install hook. It requires explicit user action to enable: the user-settings `statusLine` entry above.

## Why this exists

AI coding assistants are fast. The bottleneck is no longer writing code — it's writing the *right* code. Three-pillars adds the missing layers: a design-first pipeline that forces clarity before implementation, council-based deliberation that stress-tests decisions from multiple angles, and session continuity that preserves context across conversations and machines.

## What's in this repo

Three layers, one source of truth:

- **The canon (methodology writing)** — this `README.md`, [`CONTRIBUTING.md`](CONTRIBUTING.md), the `CLAUDE.md` framework guide, and the monthly cadence: `METHODOLOGY.md` (planned v1.6.0+), `adoption/` guides, `examples/` worked examples. Vendor-agnostic and host-agnostic — engage the methodology without installing anything.
- **The Claude Code reference implementation** — `skills/` (39 `tp-*` skills + `/council`, including the autonomous PR-iteration loop `/tp-pr-iterate`/`/tp-pr-fix`) and `agents/` (18 council personas), installable via `claude plugin install`. The patterns the canon describes, made operational for Claude Code adopters.
- **The Hermes-distribution source** — `scripts/build-hermes-distribution.py` (planned) + a GitHub Action will transform `skills/` into a Hermes-installable skill package at every release tag, force-pushed to `CurtisThe/three-pillars-hermes`. No drift by construction — humans never edit the downstream repo. See [CHANGELOG.md](CHANGELOG.md) for status.

## Runtime prerequisites

The plugin's core features (skills, agents, session management) work with **Claude Code**, **git**, and **GitHub CLI (`gh`)** on any POSIX shell with **Python 3** available. No extra installs for core skills.

A few skills shell out to Python helpers that import the `jsonschema` package:

```bash
pip install jsonschema
```

Claude Code plugins don't install Python dependencies, so this is not declared in any manifest — install it so those skills are self-contained. (The `jsonschema` package is used by the tier-return validator and the classifier judge.)

## What's been shipped

As of v2.2.0, substantive additions include the autonomous PR-iteration loop (`/tp-pr-iterate`, `/tp-pr-fix`) that polls review comments, classifies them, and dispatches one structural-fix commit per round until the review settles. See [CHANGELOG.md](CHANGELOG.md) for the running record.

## How it works

**`three-pillars-docs/vision.md` is the "why", design documents are the source of truth, tests are the proof, and audits are the gates.** Nothing ships without being traced back to a design that serves the vision and validated against the codebase. Every skill reads vision first and uses it as the tie-breaker when technical options are equivalent.

**Typical flow for a feature:**
```
/tp-design auth-revamp          # Interactive design conversation → design.md
/tp-design-detail auth-revamp   # Concrete modules, interfaces, test boundaries → detailed-design.md
/tp-design-audit auth-revamp    # Council reviews design against codebase — before any code
/tp-plan auth-revamp            # Sequenced tasks with test criteria → plan.md
/tp-plan-audit auth-revamp      # Verify plan traces fully to design — catch gaps and creep
/tp-phase-implement auth-revamp 1  # Red-green-refactor cycles, parallel agents for independent tasks
/tp-phase-review auth-revamp 1     # Review against design; flag regressions
/tp-implementation-audit auth-revamp  # Final audit: does the code match what was designed?
```

**When you're not sure an approach will work**, spike first:
```
/tp-spike websocket-scaling     # Frame hypothesis and success criteria
/tp-spike-auto websocket-scaling  # Autonomous: plan → audit → implement → results
# Review decisions.md the next morning, then:
/tp-spike-learn websocket-scaling   # Feed learnings back into project docs
```

**Context survives across conversations:**
```
/tp-session-save auth-revamp    # Saves working state to handoff.md (gitignored, local-only)
# Close the conversation, switch machines, come back later:
/tp-session-restore auth-revamp # Full continuity — no re-explaining
```

**Collaboration** — works solo, scales to teams:

- **Branch-per-design**: each design or spike lives on its own branch, `tp/{design-name}`. Skills prompt to create the branch if you start on `main`, and push it to `origin` immediately on creation so teammates see in-flight work without waiting for the first commit.
- **Advisory lock**: `three-pillars-docs/tp-designs/{name}/lock.json` records who holds the design and on which branch. Committed to git — parallel work produces a merge conflict at PR time, which forces a conversation instead of silently merging divergent implementations.
- **Takeover**: if the holder abandons the design, the next developer passes `--force-takeover` to claim it; the prior holder is preserved in `previous_owners[]` for history.
- **Graceful handoff**: the holder can run `/tp-design-release {name}` to step away cleanly — `owner` goes to `null`, and the next person claims the design without needing `--force-takeover`.
- **Remote-aware**: lock-enforcing skills `git fetch` at the start of each preflight, so they catch teammates' claims that were pushed but not yet pulled locally. Offline-tolerant — the check fails open.

**What the framework handles vs. what you still need**: this framework enforces **ownership** — who currently holds a claimed design and whether a parallel claim is allowed. It does not handle **assignment** — who should be working on what in the first place. That lives in your existing planning tool (Jira, Asana, Linear, GitHub Projects, a whiteboard, Slack). As long as your team coordinates assignments there, the lock here catches accidental overlap and abandoned work without trying to replace the planning system. Aspirational future: hooks or MCP servers could sync lock state with those external tools — out of scope today, but a direction the framework can grow into.

Lock-enforcing skills (design, spike, detail, plan, audits, implement, review) refuse to proceed if another developer holds the lock. Read-only skills (`/tp-session-restore`, learn/guide) inspect the lock and warn but never block. See `skills/_shared/collaboration.md` for the full protocol.

### Commits at every phase

Every skill that produces substantial work commits before returning — design.md, plan.md, per-task code, review.md, audit results, learn updates. One commit per task during `/tp-phase-implement`. Commits are scoped (never `git add -A`), conventionally named (`Design: {name} high-level`, `Plan: {name}`, `Implement: {name} 1.2 — title`, `Learn: {name} design`, etc.), and never include Co-Authored-By trailers. The working tree stays clean between phases. Each commit is pushed to `origin` fail-open — a failed push is logged and never blocks the commit — while opening a PR is still reserved for `/tp-design-complete`. See `skills/_shared/commit-after-work.md` for the full protocol.

## What's included

**40 skills** organized into pipelines:

| Pipeline | Skills | Purpose |
|---|---|---|
| Getting Started | guide, setup, test-setup, migrate | Vision draw-out, project doc scaffolding, test infrastructure, legacy migration |
| TDD Design | design, design-detail, design-audit | Design documents and review |
| TDD Planning | plan, plan-audit | Task sequencing and verification |
| TDD Implementation | phase-implement, task-cycle, phase-review, implementation-audit | Red-green-refactor execution |
| Autonomous | run-full-design, spike-auto | Unattended end-to-end pipeline execution |
| Spike | spike, spike-plan, spike-implement, spike-results, spike-learn | Hypothesis-driven experiments |
| Design Lifecycle | design-learn, design-release, design-complete | Post-implementation synthesis, handoff, and archival |
| Project Docs | docs-init, docs-update | Living documentation maintenance |
| Session | session-save, session-restore, session-clear | Cross-conversation continuity |
| Collaboration | inflight | In-flight design registry |
| Infrastructure | council | Multi-persona deliberation |

**18 council agents** — Aristotle, Feynman, Torvalds, Taleb, Kahneman, Meadows, and others. Used by `/council` for standalone deliberation and automatically by audit skills.

## Skills reference

Most skills take a `{design-name}` as their first argument, corresponding to a directory under `three-pillars-docs/tp-designs/`.

### Getting started

Fresh-project setup follows a deliberate order — **why** before **how**, **how** before **tests**:

| Command | What it does |
|---|---|
| `/tp-setup` | Conversational draw-out of the project's "why" into `three-pillars-docs/vision.md`. Vision only — no test-runner decisions. Run this first on any new project. |
| `/tp-docs-init` | Scaffold `architecture.md`, `product_roadmap.md`, `known_issues.md` from codebase analysis, using the vision as context. |
| `/tp-test-setup` | Configure test infrastructure (runner, layout, permissions, starter test) informed by `architecture.md`. Runs *after* docs-init so the test choices are grounded in the documented system structure. |
| `/tp-guide [intent]` | Read project docs (vision first) and recommend the highest-impact next step. Weighs recommendations against the stated vision. |
| `/tp-migrate` | Migrates an existing project from the legacy `docs/` + `tdd-*` layout to the current `three-pillars-docs/` + `tp-*` layout. Run once on repos that predate the rename. |

### Design phase

| Command | What it does |
|---|---|
| `/tp-design {name}` | Interactive conversation that produces `design.md` |
| `/tp-design-detail {name}` | Translates `design.md` into `detailed-design.md` — modules, interfaces, test boundaries |
| `/tp-design-audit {name}` | Multi-angle review of the detailed design against the codebase |

### Planning phase

| Command | What it does |
|---|---|
| `/tp-plan {name}` | Generates `plan.md` — sequenced tasks with test criteria, grouped by phase |
| `/tp-plan-audit {name}` | Verifies plan traces fully to both design documents |

### Implementation phase

| Command | What it does |
|---|---|
| `/tp-phase-implement {name} [phase]` | Executes a phase via red-green-refactor cycles |
| `/tp-task-cycle {name} <phase.task>` | Single red-green-refactor cycle for one task |
| `/tp-phase-review {name} [phase]` | Reviews completed phase against design and plan |
| `/tp-implementation-audit {name}` | Final audit — does the code match what was designed? |

### Autonomous orchestration

| Command | What it does |
|---|---|
| `/tp-run-full-design {name}` | Drives the full TDD pipeline unattended — design → detail → plan → implement → audits → PR — logging every decision to `decisions.md` for morning review |
| `/tp-spike-auto {name}` | Interactive spike design, then autonomous spike-plan → audit → implement → results chain |

### Spike pipeline

| Command | What it does |
|---|---|
| `/tp-spike {name}` | Frame a hypothesis and success criteria |
| `/tp-spike-plan {name}` | Lightweight experiment plan from the spike design |
| `/tp-spike-implement {name}` | Execute experiments with human review gates |
| `/tp-spike-results {name}` | Capture findings and verdict |
| `/tp-spike-learn {name}` | Synthesize learnings into project docs |

### Design lifecycle

| Command | What it does |
|---|---|
| `/tp-design-learn {name}` | Synthesize a design's impact into project docs |
| `/tp-design-release {name}` | Release your lock without completing — graceful handoff to a teammate |
| `/tp-design-complete {name}` | Archive to `three-pillars-docs/completed-tp-designs/`, commit, and offer a PR back to the base branch |

### Project docs

| Command | What it does |
|---|---|
| `/tp-docs-init` | Scaffold `architecture.md`, `product_roadmap.md`, `known_issues.md` (assumes `three-pillars-docs/vision.md` already exists via `/tp-setup`) |
| `/tp-docs-update [vision\|architecture\|roadmap\|known-issues]` | Targeted updates after a milestone. Vision updates follow a sticky-vision protocol — do not drift the vision to match implementation. |

### Session management

| Command | What it does |
|---|---|
| `/tp-session-save {name}` | Save context to `handoff.md` for cross-conversation continuity |
| `/tp-session-restore [name]` | Restore context at start of a new conversation |
| `/tp-session-clear {name}` | Clear stale context when switching tasks |

### Collaboration

| Command | What it does |
|---|---|
| `/tp-inflight [--json]` | Show every in-flight `tp/*` design branch across the team — owner, phase, branch age, staleness flag. Read-only, fail-open. |
| `/tp-seed {slug} [text]` | File an idea as a `seed.md` with its weight class settled up front. Offers to add it to a close open seed first, scores the four axes, shows the rough token cost per class, then writes and commits the seed. No design work. |

### Council of High Intelligence

`/council` convenes multi-persona deliberation for complex decisions. 18 reasoning personas analyze problems from independent angles, cross-examine each other, and produce synthesized recommendations.

Modes: full (18 members, 3 rounds), quick (fast 2-round), duo (2-member dialectic), or auto-triad (system picks the best 3).

## Status

**Actively maintained.** New patterns land monthly per the cadence above; smaller fixes (typos, broken links, refinements) land between releases. Cadence is monthly because methodology content isn't best produced weekly and quarterly looks abandoned. See [CHANGELOG.md](CHANGELOG.md) for the running record.

The Claude Code reference implementation (`skills/` + `agents/`) is in production use — install it, run `/tp-guide`, ship designs. The Hermes-distribution build pipeline ships in a near-term release; until then, Hermes adopters can hand-port the methodology from this canon.

## Who maintains this

Curtis ([@CurtisThe](https://github.com/CurtisThe)) — practitioner working on AI agent discipline in production engineering contexts. Contributions welcome per [CONTRIBUTING.md](CONTRIBUTING.md); for substantive proposals, open an issue first so we can align on `three-pillars-docs/vision.md`.

## License

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution.

| Component | License | Source |
|---|---|---|
| Council of High Intelligence | MIT | [0xNyk/council-of-high-intelligence](https://github.com/0xNyk/council-of-high-intelligence) |
