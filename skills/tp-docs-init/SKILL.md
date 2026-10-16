---
name: tp-docs-init
description: Scaffold architecture.md, product_roadmap.md, and known_issues.md in three-pillars-docs/ from codebase analysis. Creates the three project docs that the TDD pipeline reads for context. Assumes three-pillars-docs/vision.md already exists — if missing, recommends /tp-setup first.
---

# Docs Init

Analyze the current codebase and scaffold the three project docs that the TDD pipeline uses for context (alongside `three-pillars-docs/vision.md`, which is created by `/tp-setup`).

**No arguments** — operates on the current repository.

## Prerequisite

`three-pillars-docs/vision.md` should exist — it's the "why" pillar that the roadmap, architecture, and known-issues docs frame themselves against. If it's missing, tell the user and recommend running `/tp-setup` first. Do not block: the user can opt to proceed without a vision, but the resulting scaffolds will be weaker because there's no "why" to anchor current state and priorities against.

## Environment prereq — optional status line

While you're scaffolding docs, also check whether the plugin's optional status line is installed. The plugin ships a `statusline.sh` script that shows context-window usage, active design, and git status — but it requires a one-time copy to `~/.claude/statusline.sh` to activate (the plugin's `settings.json` already references that path).

Check:
```bash
test -x "$HOME/.claude/statusline.sh" && echo "installed" || echo "missing"
```

If **missing**, do not block the docs scaffolding. After the docs are written, surface a one-line recommendation to the user:

> *Optional: the three-pillars status line is not installed. Run `cp statusline.sh ~/.claude/statusline.sh && chmod +x ~/.claude/statusline.sh` from the plugin's install directory to enable the context-window progress bar. Skip this if you don't want a custom status line — nothing breaks either way.*

If **installed**, say nothing (it's already working).

This check lives here, in docs-init, because `/tp-docs-init` is where a user first encounters the architecture of a fresh project — it's the natural moment to surface environment setup the user may have skipped during install. It is NOT a hard prerequisite: proceed with the scaffolding regardless of the statusline's state.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

1. **Create `three-pillars-docs/` directory** if it doesn't exist.
2. **Check for `three-pillars-docs/vision.md`**. If missing, recommend `/tp-setup` and ask whether to proceed anyway. If present, read it — every scaffolded doc should align with the vision's problem, users, principles, and non-goals.
3. **Check which docs already exist**:
   - `three-pillars-docs/architecture.md`
   - `three-pillars-docs/product_roadmap.md`
   - `three-pillars-docs/known_issues.md`
   - `three-pillars-docs/project-context.md` (the spawned-agent context doc — scaffolded as a stub in step 5b, never regenerated from analysis)
   For each that exists, tell the user and skip it unless they opt to regenerate.
4. **Analyze the codebase** to inform scaffolding:
   - Read README, CLAUDE.md, `three-pillars-docs/vision.md`, and any existing docs
   - Scan source tree structure (key directories, languages, frameworks)
   - Read recent git log for project trajectory
   - Check for existing design artifacts in `three-pillars-docs/tp-designs/` and `three-pillars-docs/completed-tp-designs/`
5. **For each missing doc**, scaffold the condensed template, then fill it with content derived from the analysis:
   ```bash
   python3 "$TP_ROOT"/skills/_shared/living_doc_scaffold.py --doc architecture
   python3 "$TP_ROOT"/skills/_shared/living_doc_scaffold.py --doc product_roadmap
   python3 "$TP_ROOT"/skills/_shared/living_doc_scaffold.py --doc known_issues
   ```
   Each call writes that doc's template plus its cold archive sibling (`known_issues` also seeds the cold `known_issues_low.md`), and is an idempotent no-op when the doc already exists — it never overwrites operator work. Then replace the placeholders with the real content from step 4, keeping the template's condensed shape: **one bullet per item** (one row per table entry), a `## History` section with one line per update, and the template's one-line pointer `> History and evidence live in <archive>.` left in place — the live doc is an index of what is true now; the archive is the record. `known_issues.md` carries High and Medium only, with the "N Low issues → `known_issues_low.md`" pointer.

5b. **Scaffold the spawned-agent context doc (`project-context.md`) as a stub.** Unlike the three docs above, `three-pillars-docs/project-context.md` is an **operator-authored placeholder** — it carries the conventions / stack / domain-rules injected into every spawned subagent (council members, phase-implement / run-full-design workers, pr-fix / readonly-auditor dispatches), so it is filled in by hand, never generated from codebase analysis. Scaffold it **idempotently** with:
   ```bash
   python3 "$TP_ROOT"/skills/_shared/project_context.py scaffold
   ```
   This writes the fixed schema (`## Conventions` / `## Stack` / `## Domain rules`) with a one-line purpose header and fill-in guidance **only when the file is absent** — it is a **no-op that never overwrites** an existing operator-authored doc (design principle: never overwrite operator work), so it is safe to run on every `/tp-docs-init`. Tell the user whether it was created or left unchanged, and that they should replace the placeholders with their project's real rules. The loader `skills/_shared/project_context.py` size-checks the doc against a ~12 KB injected cap at dispatch time.

6. **Present each scaffolded doc** to the user for review before writing.
7. **Commit the artifacts** per `skills/_shared/commit-after-work.md`. Artifact paths to stage (include only docs actually created/updated in steps 5–6):
   - `three-pillars-docs/architecture.md`
   - `three-pillars-docs/product_roadmap.md`
   - `three-pillars-docs/known_issues.md`
   - `three-pillars-docs/known_issues_low.md` and each doc's `*_archive.md` (only when step 5 created them)
   - `three-pillars-docs/project-context.md` (only if step 5b created the stub)
   Commit message: `Docs: init project docs` (or `Docs: init {file1},{file2}` if only a subset was scaffolded).
8. **Tell the user the next step**: Once the three docs are in place, the natural next step on a fresh project is `/tp-test-setup` — it configures test infrastructure informed by the `architecture.md` you just scaffolded. This sequencing is deliberate: testing-framework choices belong *after* the architecture is documented, not before.

## Rules
- This skill takes no design-name argument (it operates on the repo, not a `[a-z0-9-]+` design directory).
- **Do not scaffold a Vision section in product_roadmap.md.** Vision lives in `three-pillars-docs/vision.md` and the roadmap links to it. If an existing roadmap has a Vision section, offer to migrate its content into `three-pillars-docs/vision.md` and replace the roadmap section with a link.
- Content must reflect the **actual codebase** and the **stated vision**, not generic templates. If the analysis finds real architecture decisions, components, or issues, include them. Flag to the user any place where what the code does seems to contradict `three-pillars-docs/vision.md` — that's a signal the vision is stale or the code has drifted.
- Never overwrite an existing doc without explicit user confirmation.
- Each doc should be a useful starting point, not a complete document — the user will refine.
- If the codebase is too small or new to derive meaningful content, say so and write minimal stubs with section headers only.
