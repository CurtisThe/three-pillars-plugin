---
name: tdd-session-save
description: Save structured session context to handoff.md in the design's directory for continuity across conversations. Use at end of a session or before switching phases.
argument-hint: "<design-name>"
---

# Session Compact

Write a structured handoff that captures what compaction and memory would lose — the *why* behind decisions, not just the *what*.

**Argument**: `<design-name>` (required) — must match an existing directory under `docs/tdd-designs/`.

## Steps

1. **Resolve the design directory**: `docs/tdd-designs/<design-name>/`. If it doesn't exist, tell the user no design by that name exists and stop.
2. **Read the existing handoff** at `docs/tdd-designs/<design-name>/handoff.md` (if it exists). Note anything still relevant — you'll carry it forward. Everything else is discarded.
3. **Review this conversation** — what was discussed, decided, built, and left unfinished.
4. **Overwrite `docs/tdd-designs/<design-name>/handoff.md`** entirely with fresh content from this session. The new file is the source of truth — the old one is gone. Use these sections:

```
## Phase
What phase/task the user was working on. One line.

## Decisions
Bulleted list of non-obvious decisions and trade-offs made this session.
Skip anything already visible in code diffs or commit messages.

## State
What's done, what's half-done, what's blocked.
Be specific: file names, function names, test results, branch state.

## Next
What the user will likely want to do next. Ordered by priority.

## Open Questions
Unresolved items to raise next session.

## Carried Forward
Any still-relevant context from the prior handoff (max 5 lines).
Drop anything superseded by this session's work.
```

## Rules
- **Validate `<design-name>`** per `skills/_shared/validate-name.md`.
- Keep it under 60 lines total. Dense and specific, not verbose.
- Use file paths and function names, not vague descriptions.
- Don't repeat what's in CLAUDE.md, git log, or memory files.
- Don't repeat what's already in sibling artifacts (design.md, plan.md, etc.) — the handoff captures *session* context, not *design* context.
- If nothing meaningful happened yet, say so in one line instead of fabricating content.
