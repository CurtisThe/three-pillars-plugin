# Read Project Docs

Read the project docs if they exist — do not require them. **Read vision first** so every downstream judgment is framed against the "why":

1. `three-pillars-docs/vision.md` — **the why**. Problem, users, principles, non-goals, success signals. Every recommendation, design, and plan should serve the vision. Flag anything that contradicts it.
2. `three-pillars-docs/architecture.md` — the how. System structure and key decisions.
3. `three-pillars-docs/product_roadmap.md` — the what next. Current state, inventory, sequence.
4. `three-pillars-docs/known_issues.md` — the what's broken (**open issues only**; RESOLVED history lives in the append-only sibling `three-pillars-docs/known_issues_resolved.md` — read it only when you need a closed issue's history).

Treat `three-pillars-docs/vision.md` as load-bearing context — if a proposed design, plan, or recommendation conflicts with the vision's principles or non-goals, say so explicitly and ask the user whether to proceed, revise the work, or update the vision.

If `three-pillars-docs/vision.md` is missing, suggest running `/tp-setup` (which creates it as its first step). If the other three are missing, suggest `/tp-docs-init`. Do not block in either case — the user may want to proceed without them.
