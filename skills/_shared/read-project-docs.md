# Read Project Docs

Read the project docs if they exist — do not require them. **Read vision first** so every downstream judgment is framed against the "why":

1. `docs/vision.md` — **the why**. Problem, users, principles, non-goals, success signals. Every recommendation, design, and plan should serve the vision. Flag anything that contradicts it.
2. `docs/architecture.md` — the how. System structure and key decisions.
3. `docs/product_roadmap.md` — the what next. Current state, inventory, sequence.
4. `docs/known_issues.md` — the what's broken.

Treat `docs/vision.md` as load-bearing context — if a proposed design, plan, or recommendation conflicts with the vision's principles or non-goals, say so explicitly and ask the user whether to proceed, revise the work, or update the vision.

If `docs/vision.md` is missing, suggest running `/tdd-setup` (which creates it as its first step). If the other three are missing, suggest `/tdd-docs-init`. Do not block in either case — the user may want to proceed without them.
