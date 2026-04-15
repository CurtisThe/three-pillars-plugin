# The Three Pillars

Every line of AI-assisted code serves three masters.

```
                    ┌─────────────────┐
                    │    BUSINESS      │
                    │   ALIGNMENT      │
                    │                  │
                    │  "Does this move │
                    │   the needle?"   │
                    └────────┬─────────┘
                             │
                    ┌────────┴─────────┐
                    │                  │
               ┌────┴────┐      ┌─────┴─────┐
               │  SPEED  │      │  QUALITY   │
               │         │      │            │
               │ "Ship   │      │ "Will this │
               │  today" │      │  survive   │
               │         │      │  contact   │
               │         │      │  with      │
               │         │      │  reality?" │
               └─────────┘      └────────────┘
```

## The pillars

**Speed** — AI makes fast trivially available. The hard part is making fast
*correct*. TDD skills, rapid prototyping agents, and tight feedback loops
keep velocity honest.

**Quality** — Tests that run before every commit. Council deliberation that
stress-tests decisions from 18 angles before you build. The goal is to catch 
the failures that cost more to fix later than to prevent now.

**Business alignment** — AI requires the right kind of context to force it to 
stay focused on real business needs. Stakeholder agents represent the people who sign 
off, the people who use it, and the people who maintain it.

## How this repo embodies the pillars

### Speed

- Two-command plugin install — no cloning, no bootstrap scripts.
- 25 TDD skills that automate the design-plan-implement-review cycle. Red-green-refactor with Claude as pair.
- Spike pipeline for time-boxed experiments — validate unknowns before committing to a full design.
- `/tdd-spike-auto` runs an entire spike hands-off: plan, audit, implement, capture results. Review `decisions.md` the next morning.
- Parallel agent execution during implementation — independent tasks run concurrently.

### Quality

- Council of High Intelligence: 18 reasoning personas stress-test decisions before code is written.
- Design-first pipeline: every implementation traces back to a design document and passes through audit gates.
- Council deliberation is built into the pipeline — `/tdd-plan-audit` and `/tdd-design-audit` convene the council automatically.
- Domain-specific council triads (architecture, risk, debugging, product, AI safety) focus the right expertise on the right problems.

### Business Alignment

- Four living project docs (`vision.md`, `architecture.md`, `product_roadmap.md`, `known_issues.md`) ground every design in the real state of the codebase — and in a stated "why" the audits can cite as a tie-breaker.
- `/tdd-setup` draws the vision out of the user conversationally; `/tdd-docs-init` scaffolds the other three from codebase analysis; `/tdd-docs-update` maintains all four after milestones, with a sticky-vision protocol that prevents drift.
- `/tdd-design-learn` and `/tdd-spike-learn` close the feedback loop — learnings from completed work flow back into project docs and surface affected downstream designs.
- Session continuity (`/tdd-session-save` / `/tdd-session-restore`) preserves context across conversations and machines, so nothing is lost between sessions.

## Long-term vision: decentralized AI ownership

Each business unit owns and maintains its own stakeholder AI persona — its prompt, context documents, MCP servers, skills, and grounding material. Engineering doesn't define what the Product stakeholder cares about; the Product team does.

This means:
- **Product** maintains an agent that knows current priorities, customer pain points, and roadmap constraints. They update its context as strategy shifts.
- **Engineering** maintains an agent grounded in the actual system architecture, tech debt reality, and operational history. It connects to internal MCP servers for live service health.
- **Operations** maintains an agent wired into monitoring, incident history, and runbook knowledge. It knows what breaks and why.
- **Each team's agent is a first-class participant** in council deliberations, not a caricature written by someone outside the team.

The three-pillars repo becomes the coordination layer — it defines how agents deliberate together, but each team controls what their agent knows and how it reasons. Central governance sets the protocol; distributed ownership sets the substance.

This scales because no single person needs to understand every domain. The AI does the synthesis. The humans own the inputs.

## The roadmap

### Done
- [x] Plugin marketplace distribution (two-command install)
- [x] Council of High Intelligence (18 thinkers, 4 modes, 20+ pre-built triads)
- [x] TDD pipeline (27 skills): guide, setup, test-setup, design, detail, audit, plan, implement, review, final audit
- [x] Spike pipeline: hypothesis-driven experiments with structured findings
- [x] Autonomous spike execution (`/tdd-spike-auto`) with decision logging
- [x] Session continuity across conversations and machines
- [x] Design lifecycle management (learn, complete, archive)
- [x] Four living project docs (vision, architecture, roadmap, known-issues) with setup, init, and update skills

### Next: Stakeholder agents
- [ ] Adapt the council agent pattern for company-specific personas
- [ ] Product stakeholder: "Does this solve the customer's actual problem?"
- [ ] Engineering stakeholder: "Can we maintain this at scale?"
- [ ] Operations stakeholder: "What happens when this fails at 3am?"
- [ ] Customer stakeholder: "Would I pay for this? Would I notice?"
- [ ] Business unit agents representing specific teams/domains
- [ ] `/stakeholders` skill for lightweight alignment checks before PRs

### Later: Company council
- [ ] Combined council mode: historical thinkers + company stakeholders
- [ ] Domain-specific triads (e.g., Feynman + Product + Engineering for architecture decisions)
- [ ] Integration with existing planning and review workflows

---

*The best code is code that didn't need to be written.*
*The second best is code that was written once, tested immediately, and solved the right problem.*
