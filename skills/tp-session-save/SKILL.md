---
name: tp-session-save
description: Save structured session context to handoff.md in the design's directory for continuity across conversations. Use at end of a session or before switching phases.
argument-hint: "{design-name} [--stage-boundary] [--cheap-tier[=ab]]"
effort: high
---

# Session Compact

Write a structured handoff that captures what compaction and memory would lose — the *why* behind decisions, not just the *what*.

**Argument**: `{design-name}` (required) — must match an existing directory under `three-pillars-docs/tp-designs/`. `--cheap-tier[=ab]` (optional, deprecated) changes nothing: the cheap-tier handoff draft (step 3) runs in every invocation, per `skills/_shared/cheap-dispatch.md`, and `<mode>` is `on`.

> **Top-level / cross-design work** (fleet launches, merge-queue drains, multi-design campaigns) has no single design dir — save it under the reserved **`orchestration`** slot (`/tp-session-save orchestration`). It is not a design (no `design.md` / lock / branch), so `/tp-design-complete` never archives it out from under you. See `three-pillars-docs/tp-designs/orchestration/README.md`.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

1. **Resolve the design directory**: `three-pillars-docs/tp-designs/{design-name}/`. If it doesn't exist, tell the user no design by that name exists and stop.
2. **Read the existing handoff** at `three-pillars-docs/tp-designs/{design-name}/handoff.md` (if it exists). Note anything still relevant — you'll carry it forward. Everything else is discarded.
3. **Review this conversation** — what was discussed, decided, built, and left unfinished.
   <!-- cheap-tier:handoff -->
   **Cheap-tier handoff draft (never with `--stage-boundary`; the loop is `skills/_shared/cheap-dispatch.md`).** Run `python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py spec --slot handoff --root . --cheap-tier <mode> --probe --design {design-name}` in Bash with timeout 300000; a null rung means step 4 as today. Otherwise write step 3's findings to a scratch facts payload JSON (`phase`, `decisions`, `state`, `next`, `open_questions`, `carried_forward`, and every PR number and SHA the handoff may cite), never the session context, and spawn `Agent(subagent_type=<spec.agent_ref>, model=<spec.model>, …)` to write one scratch file from it: the step-4 handoff under its template headings.
   Check it with the `prose_shape` oracle: `python3 "$TP_ROOT"/skills/_shared/cheap_oracle_run.py check --slot handoff --artifact <A.json> --ctx <C.json>` (artifact `path`; ctx `kind` `handoff`, `root` `.`, `facts`). On `accept`, step 4 writes the draft, corrected against this conversation, and shows the written handoff to the operator to approve or edit. A dropped draft means step 4 writes the handoff as today.
   After an accepted draft is written, run `python3 "$TP_ROOT"/skills/_shared/prose_oracle.py save-draft --root three-pillars-docs/tp-designs/{design-name} --slot handoff --draft <draft> --final <handoff.md> --reviewed <operator approved>` (`true` only once the operator approved it). Record the attempt per the dispatch doc; under `ab`, run its pure-slot pair and use neither arm.
   <!-- /cheap-tier -->
4. **Overwrite `three-pillars-docs/tp-designs/{design-name}/handoff.md`** entirely with fresh content from this session. The new file is the source of truth — the old one is gone. Use these sections:

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

5. **Update the MRU.** Run the MRU snippet from `skills/_shared/validate-name.md` with `name={design-name}` so the first line of `.claude/last-design` is the design you just saved — saving a session *is* using it. This is what lets a later `/clear` + `/tp-session-restore` (no argument) resolve back to this design (or to the `orchestration` slot for fleet / cross-design sessions). Never `git add` the file (it's gitignored).

## Stage boundary (`--stage-boundary`)

`/tp-run-full-design` passes `--stage-boundary` inline before a stage reset
(`skills/tp-run-full-design/throughput.md` §Stage reset). The handoff then also must carry
`## Rulings` (operator/seat rulings in force), `## Ladder decisions` (tier and retry calls a fresh
context must not re-litigate), `## Open obligations` (what the run owes later, e.g. post-merge
measurement runs) and `## Run budget` — exactly one fenced JSON block, `argv` being the run's
verbatim argument tail:

```json
{"argv": "<verbatim tail>", "tokens_used": 0, "started_epoch": 0, "retry_counters": {"<slot>": 0}}
```

The resumed run seeds `--max-tokens`, `--max-wall-clock` and `--max-attempts` from it; a missing or
unparseable block halts it with `[orchestrator] resume-budget-missing`. The 60-line limit does not
apply to these four sections.

## Rules
- **Validate `<design-name>`** per `skills/_shared/validate-name.md`.
- **Before writing**, check that the project's `.gitignore` contains `three-pillars-docs/tp-designs/*/handoff.md`. If missing, append it (with a `# three-pillars session artifacts` comment). Tell the user what was added.
- `handoff.md` is gitignored — it stays local and is not committed to version control. This prevents session context (which may reference sensitive configuration) from entering VCS. Other design artifacts (`design.md`, `plan.md`, `decisions.md`, `demos/`) are tracked — only `handoff.md` is purely per-developer ephemeral state.
- Keep it under 60 lines total. Dense and specific, not verbose.
- Use file paths and function names, not vague descriptions.
- Don't repeat what's in CLAUDE.md, git log, or memory files.
- Don't repeat what's already in sibling artifacts (design.md, plan.md, etc.) — the handoff captures *session* context, not *design* context.
- If nothing meaningful happened yet, say so in one line instead of fabricating content.
