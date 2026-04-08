---
name: tdd-session-clear
description: Clear the handoff.md from a design's directory when switching to a completely different task. Prevents stale context from contaminating the next session.
argument-hint: "<design-name>"
---

# Session Clear

Wipe the handoff file so the next `/tdd-session-restore` starts fresh.

**Argument**: `<design-name>` (required) — must match an existing directory under `docs/tdd-designs/`.

## Steps

1. **Resolve the design directory**: `docs/tdd-designs/<design-name>/`.
2. **Check if `handoff.md` exists** in the design directory. If not, tell the user there's nothing to clear and stop.
3. **Show the user a 2-3 line summary** of what's currently in the handoff (phase + key state) so they can confirm they want to discard it.
4. **Ask for confirmation** before deleting. A simple "Clear this?" is enough.
5. **On confirmation, delete `docs/tdd-designs/<design-name>/handoff.md`.**
6. **Confirm deletion** in one line.

## Rules
- **Validate `<design-name>`** per `skills/_shared/validate-name.md`.
- Never delete without showing what will be lost and getting confirmation.
- Don't archive or rename — just delete. If the user wanted to save it, they'd commit it.
- Only deletes `handoff.md` — never touch design.md, detailed-design.md, plan.md, review.md, or anything else in the directory.
