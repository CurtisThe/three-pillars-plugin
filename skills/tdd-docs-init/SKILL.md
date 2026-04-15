---
name: tdd-docs-init
description: Scaffold architecture.md, product_roadmap.md, and known_issues.md in docs/ from codebase analysis. Creates the three project docs that the TDD pipeline reads for context. Assumes docs/vision.md already exists — if missing, recommends /tdd-setup first.
---

# Docs Init

Analyze the current codebase and scaffold the three project docs that the TDD pipeline uses for context (alongside `docs/vision.md`, which is created by `/tdd-setup`).

**No arguments** — operates on the current repository.

## Prerequisite

`docs/vision.md` should exist — it's the "why" pillar that the roadmap, architecture, and known-issues docs frame themselves against. If it's missing, tell the user and recommend running `/tdd-setup` first. Do not block: the user can opt to proceed without a vision, but the resulting scaffolds will be weaker because there's no "why" to anchor current state and priorities against.

## Environment prereq — optional status line

While you're scaffolding docs, also check whether the plugin's optional status line is installed. The plugin ships a `statusline.sh` script that shows context-window usage, active design, and git status — but it requires a one-time copy to `~/.claude/statusline.sh` to activate (the plugin's `settings.json` already references that path).

Check:
```bash
test -x "$HOME/.claude/statusline.sh" && echo "installed" || echo "missing"
```

If **missing**, do not block the docs scaffolding. After the docs are written, surface a one-line recommendation to the user:

> *Optional: the three-pillars status line is not installed. Run `cp statusline.sh ~/.claude/statusline.sh && chmod +x ~/.claude/statusline.sh` from the plugin's install directory to enable the context-window progress bar. Skip this if you don't want a custom status line — nothing breaks either way.*

If **installed**, say nothing (it's already working).

This check lives here, in docs-init, because `/tdd-docs-init` is where a user first encounters the architecture of a fresh project — it's the natural moment to surface environment setup the user may have skipped during install. It is NOT a hard prerequisite: proceed with the scaffolding regardless of the statusline's state.

## Steps

1. **Create `docs/` directory** if it doesn't exist.
2. **Check for `docs/vision.md`**. If missing, recommend `/tdd-setup` and ask whether to proceed anyway. If present, read it — every scaffolded doc should align with the vision's problem, users, principles, and non-goals.
3. **Check which docs already exist**:
   - `docs/architecture.md`
   - `docs/product_roadmap.md`
   - `docs/known_issues.md`
   For each that exists, tell the user and skip it unless they opt to regenerate.
4. **Analyze the codebase** to inform scaffolding:
   - Read README, CLAUDE.md, `docs/vision.md`, and any existing docs
   - Scan source tree structure (key directories, languages, frameworks)
   - Read recent git log for project trajectory
   - Check for existing design artifacts in `docs/tdd-designs/` and `docs/completed-tdd-designs/`
5. **For each missing doc**, scaffold with content derived from the analysis:

   **architecture.md** scaffold sections:
   - Overview (what the system does, high-level architecture — consistent with vision's Problem section)
   - Goals and Non-Goals (non-goals should echo `docs/vision.md`'s non-goals, not contradict them)
   - Key Components (modules, services, data stores)
   - Architecture Decisions (choices made and rationale — note when a decision was driven by a vision principle)
   - Constraints (hardware, dependencies, compatibility)

   **product_roadmap.md** scaffold sections:
   - **(No Vision section.)** Open with a single line: `> **Why this exists:** see [docs/vision.md](vision.md).` The vision lives in one place; the roadmap does not duplicate it.
   - Current State (what works today, what doesn't)
   - Design Inventory (table of TDD designs with status)
   - Implementation Sequence (what to build next, dependencies — ordered by impact against the vision)
   - Methodology (how we build — TDD pipeline, spikes)

   **known_issues.md** scaffold sections:
   - Critical / High (blocking issues)
   - Medium (functional issues, workarounds exist)
   - Low (cosmetic, minor, tech debt)

6. **Present each scaffolded doc** to the user for review before writing.
7. **Commit the artifacts** per `skills/_shared/commit-after-work.md`. Artifact paths to stage (include only docs actually created/updated in step 6):
   - `docs/architecture.md`
   - `docs/product_roadmap.md`
   - `docs/known_issues.md`
   Commit message: `Docs: init project docs` (or `Docs: init <file1>,<file2>` if only a subset was scaffolded).
8. **Tell the user the next step**: Once the three docs are in place, the natural next step on a fresh project is `/tdd-test-setup` — it configures test infrastructure informed by the `architecture.md` you just scaffolded. This sequencing is deliberate: testing-framework choices belong *after* the architecture is documented, not before.

## Rules
- This skill takes no design-name argument (it operates on the repo, not a `[a-z0-9-]+` design directory).
- **Do not scaffold a Vision section in product_roadmap.md.** Vision lives in `docs/vision.md` and the roadmap links to it. If an existing roadmap has a Vision section, offer to migrate its content into `docs/vision.md` and replace the roadmap section with a link.
- Content must reflect the **actual codebase** and the **stated vision**, not generic templates. If the analysis finds real architecture decisions, components, or issues, include them. Flag to the user any place where what the code does seems to contradict `docs/vision.md` — that's a signal the vision is stale or the code has drifted.
- Never overwrite an existing doc without explicit user confirmation.
- Each doc should be a useful starting point, not a complete document — the user will refine.
- If the codebase is too small or new to derive meaningful content, say so and write minimal stubs with section headers only.
