---
name: tdd-session-restore
description: Restore session context from handoff.md in the design's directory at the start of a new conversation. Gives you continuity without re-explaining.
argument-hint: "[design-name]"
---

# Session Restore

Pick up where the last session left off by loading the handoff and design artifacts.

**Argument**: `<design-name>` (optional) — must match an existing directory under `docs/tdd-designs/`.

If no argument is given, read `.claude/last-design` (project root) for the most recently active design name. If that file doesn't exist or is empty, list available designs under `docs/tdd-designs/` and ask the user which one to restore.

## Steps

1. **Resolve the design name**: Use the argument if given, otherwise read `~/.claude/last-design`. If neither is available, list designs and ask.
2. **Resolve the design directory**: `docs/tdd-designs/<design-name>/`.
3. **Read `handoff.md`** from the design directory. If it doesn't exist, tell the user there's no prior session to restore. Check if any other artifacts exist (design.md, plan.md) and summarize what's available, then stop.
4. **Read the sibling artifacts** that exist in the design directory (design.md, detailed-design.md, plan.md, review.md) — quick scan for context, not deep-dive.
5. **Read the files mentioned** in the handoff's State and Next sections (just a quick scan — don't deep-dive unless something looks wrong).
6. **Read Current Focus**: If `docs/product_roadmap.md` exists and has a `## Current Focus` table, read it. Use this to contextualize the design's status within the broader project — is it the top priority? Is it blocking other work?
7. **Present a brief status** to the user:
   - What design they're working on and which phase
   - What artifacts exist (design ✓, detailed ✓, plan ✓, etc.)
   - What's done vs. what's next
   - Where this design sits in the Current Focus table (if present)
   - Any open questions from last time
8. **Ask** if they want to continue where they left off or pivot to something else.

## Rules
- **Validate `<design-name>`** per `skills/_shared/validate-name.md`.
- Keep the status update under 15 lines. The user already wrote the handoff — don't parrot it back verbatim, synthesize it.
- If the handoff references files that no longer exist or state that looks stale, flag it.
- Don't start doing work until the user confirms direction.
