# tp-run-full-design — boundary contracts

The orchestrator's two boundary contracts, moved verbatim out of `SKILL.md` (which keeps each heading with a pointer here). The **pickup contract** is what Tier 1 validates before any other work; the **explicit artifact contract** is the literal list Tier 3 appends to every `worker_prompt`. Behavior is unchanged: the orchestrator reads this file where `SKILL.md` points to it.

## Pickup contract v1

The orchestrator validates the returned contract against this schema before doing any other work. The contract is JSON-shaped, **version 1**, and the validation rules are intentionally strict — a malformed contract aborts the run before Tier 2 spends tokens.

```json
{
  "version": 1,
  "slug": "kebab-case-design-name",
  "branch": "tp/{slug}",
  "dir": "three-pillars-docs/tp-designs/{slug}",
  "task_metadata": {
    "title": "Human-readable task title",
    "hypothesis": "What is unknown / what we want to learn",
    "external_ref": "Opaque pickup-skill-specific reference",
    "phase_hook": null,
    "writeup_hook": null,
    "escalate_hook": null
  }
}
```

Validation rules — each maps to an explicit failure mode:

- **`version` is required and must equal `1`.** The orchestrator refuses any contract whose `version` it does not recognize. Append `[tp-run-full-design/tier-1] unknown-pickup-version <value>` to decisions.md and exit non-zero. Forward-compatibility shims are deferred to a v2 design — never silently downgrade.
- **`slug`, `branch`, `dir`, `task_metadata`** are required top-level keys. Missing any → `[tp-run-full-design/tier-1] missing-required-field <key>` and exit non-zero.
- **`slug`** must match `[a-z0-9-]+` per `skills/_shared/validate-name.md`. Mismatch → `[tp-run-full-design/tier-1] invalid-slug <value>`.
- **`branch`** must equal `tp/{slug}` exactly. Mismatch (e.g., pickup skill returned a candidate branch by accident) → `[tp-run-full-design/tier-1] branch-slug-mismatch`.
- **`dir`** must equal `three-pillars-docs/tp-designs/{slug}` exactly and the directory must exist on disk.
- **`task_metadata.title`** is required and non-empty (used in the Tier 6 PR title).
- **`phase_hook`, `writeup_hook`, `escalate_hook`** may each be `null` or an opaque string. If `null`, the corresponding callback is omitted (fire-and-forget) and noted once in decisions.md as `[tp-run-full-design/tier-1] hook-omitted <hook-name>`. Per detailed-design.md §Decisions (OQ2), hook failures are Medium-confidence boundary events that **do not abort the run**.

## explicit_artifact_contract

The contract appended to `worker_prompt` is a literal numbered list. Six items, in order, no negotiation:

1. **Set up the candidate branch for this phase.**
   - **Phase 1**: `git checkout -b candidate/{slug}/single {base-ref}` — create the shared candidate branch off the orchestrator's base ref (typically `tp/{slug}` HEAD). Do NOT work on the auto-entry `worktree-agent-<id>` branch (S13 finding F2).
   - **Phase 2+**: `git fetch origin && git checkout candidate/{slug}/single` — continue building on the branch Phase 1 already pushed. Do not create a new branch.
2. **Implement this phase's tasks on the candidate branch.** Execute only the tasks belonging to Phase N from `plan.md` — prior phases are already committed on the branch. Each task is one red-green-refactor cycle and one commit on the candidate branch.
3. **Commit work on the candidate branch.** One commit per plan task. No `--no-verify`, no `Co-Authored-By` trailer, no `git add -A` — scope each commit to the files the task touched.
4. **`git push -u origin candidate/{slug}/{candidate_id}`** — push the candidate branch to origin. This is the boundary-crossing mechanism (S13 answer to Round 1 finding B2): once pushed, the candidate is durable even if the worker worktree is later cleaned up.
5. **Return a structured response** as the final answer text — a fenced JSON block in the exact shape below, with no content after it. This block is the orchestrator's ONLY input from the worker; anything else in the response text is treated as scratch.
   ```json
   {
     "schema": "tp-run-full-design/candidate/v1",
     "candidate_id": "{candidate_id}",
     "branch": "candidate/{slug}/{candidate_id}",
     "sha": "<git rev-parse HEAD>",
     "summary": "<short narrative — what was implemented, key tradeoffs>",
     "test_results": {
       "passed": <int>, "failed": <int>, "skipped": <int>,
       "raw": "<test-runner stdout, truncated to 4000 chars>"
     },
     "telemetry": {
       "duration_ms": <int>, "tokens_used": <int>, "tool_calls": <int>
     }
   }
   ```
6. **Do NOT write artifact files to the parent worktree.** Specifically: do not create or edit anything under `three-pillars-docs/tp-designs/{slug}/candidates/`. The orchestrator writes those artifacts itself in Tier 3.5 — the worker only computes and reports. (Why: Claude Code's harness blocks subagent `.md` Write calls as a deliberate signal that subagents should compute, not file-write. Fighting that signal is what got the prior worker-writes-artifacts contract scrapped — see d12-worker-contract-revision.md.)
