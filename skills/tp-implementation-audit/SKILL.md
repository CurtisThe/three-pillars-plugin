---
name: tp-implementation-audit
description: "Final audit of a completed plan — verify the full implementation against both design.md and detailed-design.md."
argument-hint: "{design-name} [--auto] [--force-takeover] [--certify-sweep]"
effort: xhigh
---

# Implementation Audit

Comprehensive review of a completed implementation against both design documents. This runs after all phases are done (unlike `/tp-phase-review` which reviews a single phase). It answers: "Did we build what we designed?"

**Argument**: `{design-name}` (required) — must match an existing directory under `three-pillars-docs/tp-designs/`.

## Prerequisites
- `three-pillars-docs/tp-designs/{design-name}/design.md` must exist.
- `three-pillars-docs/tp-designs/{design-name}/detailed-design.md` must exist.
- `three-pillars-docs/tp-designs/{design-name}/plan.md` must exist with all phases marked as Done (or Skipped/Blocked).

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

### 0. Preflight
Run the collaboration preflight per `skills/_shared/collaboration.md` with `phase: "implementation-audit"`. This verifies the branch and refreshes the lock so the final audit artifact is written by the rightful owner. Honor `--force-takeover` if passed.

### 0b. Repo-map preamble (optional)
Per `skills/_shared/repo-map-preamble.md`. If `aider` is on PATH, generate a structural map of the codebase before walking design vs. implementation. Use it to focus interface-fidelity checks in Step 3 on files PageRank surfaces as load-bearing.

### 1. Load all design artifacts
Read `design.md`, `detailed-design.md`, `plan.md`, and any `review.md` files from the design directory. Do not skim — read fully. Also read project docs per `skills/_shared/read-project-docs.md` for project context.

### 2. Verify scope coverage against design.md
For EVERY item in design.md, verify it was implemented:

- **Each "In scope" bullet** → trace to implemented code. Is it done?
- **Each entity** → does it exist in the codebase with the described relationships?
- **Each behavior** → is it implemented and tested?
- **Each constraint** → is it respected? (performance, compatibility, resource limits)
- **"Out of scope" items** → verify nothing was accidentally implemented that shouldn't have been (scope creep).

### 3. Verify interface fidelity against detailed-design.md
For EVERY interface defined in detailed-design.md:

- **Module structure** → do files exist where the design said they would?
- **Public APIs** → do signatures match? Are input/output types correct?
- **Data flow** → does data move through the system as designed?
- **Test strategy** → are the specified test types (unit, integration, mocked boundaries) implemented as planned?

### 4. Run the full test suite
Run the project's complete test suite. Discover the test command from the project config (CLAUDE.md, Makefile, package.json, pyproject.toml, etc.):
```
{project-test-command} 2>&1 | tee "$(mktemp "${TMPDIR:-/tmp}/test_output.XXXXXX.log")"
```
All tests must pass. Flag any failures.

### 5. Check for drift between phases
If multiple phases were implemented across separate sessions:
- Look for inconsistencies where later phases contradict earlier ones
- Check that shared interfaces still agree after all phases are done
- Verify no dead code was left from intermediate implementations that got refactored

### 6. Check for gaps
Things the design promised but the implementation may have missed:
- Edge cases mentioned in the design but not tested
- Error handling described in the design but not implemented
- Configuration or extension points described but not wired up
- Integration points described but not connected

### 7. Check for unintended additions
Things the implementation added that weren't in the design:
- Extra public APIs not in detailed-design.md
- Additional data structures or entities
- Behaviors beyond what design.md specified
- Flag these — they may be legitimate discoveries during implementation, but they should be acknowledged

### 7b. Shipped promises
Read the diff for shipped text (docs, SKILL.md prose, CLI help, error messages) that cites a dev-only mechanism as *the* enforcement a user can rely on — per `skills/_shared/consumer-repo-rule.md`. In the three-pillars dev repo, also run `skills/_shared/devonly_citation.py` if present (run-if-present, framework repo only; its absence means no extra findings, never a failure). This dimension is a reviewer read of the diff and applies in any repo; only the script itself is dev-repo only. Per `skills/_shared/forge-parity-rule.md`, the same read flags a silent Gitea no-op or a github.com-only path in the diff as a shipped-promises finding.

**7c. Fragility.** Follow `skills/tp-implementation-audit/fragility-audit.md` (rule: `skills/_shared/test-fragility.md`): lint the diff, record the changed-tests run, write the blocking fragile-class findings as items.

**7d. Security.** Run `python3 "$TP_ROOT"/skills/_shared/trust_boundary.py --base <base> --head HEAD` (`<base>` = the design's base-branch merge-base — the same range the other steps read) and read the brief: `SECURITY.md` at the repo root when it is a file, else `skills/_shared/trust-boundary-checklist.md`. Apply the security bar: a security finding blocks only with a demonstrated exploit path — the attacker-controlled input, the trust boundary it crosses and the effect, with a reproducer; hardening ideas without one are notes. Exit 2 (git read failed) fails closed: review every touched file yourself. Record the result under `## Security`.
### 8. Compile findings

Write `three-pillars-docs/tp-designs/{design-name}/implementation-audit.md`:

```markdown
# <Design Name> — Implementation Audit

## Summary
<2-3 sentences: overall assessment, confidence that the design was faithfully implemented>

## Scope Coverage
| Design Item | Status | Notes |
|-------------|--------|-------|
| <item from design.md> | Done / Partial / Missing | {details} |

## Interface Fidelity
| Interface | Matches Design | Deviations |
|-----------|---------------|------------|
| <API/module from detailed-design.md> | Yes / Partial / No | <what differs> |

## Test Results
<test suite output summary — pass/fail counts>

## Gaps
- <things the design specified but the implementation missed>

## Unintended Additions
- <things implemented that weren't in the design — note if beneficial or accidental>

## Shipped Promises
- <shipped text citing a dev-only mechanism as enforcement — file, line, what it claims — or exactly `No findings.`>

## Security
- <trust-boundary surfaces and any finding with a demonstrated exploit path — file, line, input, effect — or exactly `No findings.`>

## Cross-Phase Drift
- <inconsistencies between phases, if any>

## Guards certified
<mandatory: one line per claim — `[cert:<id>]` guard, property, status — or exactly `No guard claims.`>

## Verdict
<One of: PASS — implementation faithfully matches design | PASS WITH NOTES — minor deviations documented above | NEEDS WORK — significant gaps listed above>

## Recommended Actions
- <concrete next steps if anything needs fixing>
```

### 8b. Certify guard claims
An audit that says a guard (test, check, lint, gate) *enforces* a property must prove it, per `skills/_shared/certification-protocol.md` (the single source; §Interactive surfaces). Write each such claim (`{id, guard, property, parameters, subjects}`, `subjects` being the repo-relative files the guard checks: the only files the certifier may perturb, so a claim without them certifies `unverified`) to `three-pillars-docs/tp-designs/{design-name}/certifications/impl-audit.claims.json` and tag its sentence `[cert:<id>]`. Resolve the CLI:
```bash
TOP="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$TOP" ] && [ -f "$TOP"/skills/_shared/resolve_script.py ]; then RS="$TOP"/skills/_shared/resolve_script.py; else RS="$TP_ROOT"/skills/_shared/resolve_script.py; fi
CERT="$(python3 "$RS" certify.py)" || exit 1
```
The artifact is always phrase-scanned. With no claims, `python3 "$CERT" scan --artifact <implementation-audit.md>` prints the `verdict` to join into `## Verdict`; with claims, steps 1–3:
1. Dispatch `Agent(subagent_type=agent_ref("tp-certifier"), model="opus") (`agent_ref("tp-certifier")` = the stdout of `python3 "$TP_ROOT"/skills/_shared/agent_ref.py tp-certifier`, the plugin-namespaced reference)` with `S` = the `HEAD` SHA, the resolved absolute `$CERT` path and the claims bytes fenced as untrusted data. Open its checkout first and pass `WORKTREE:` per certification-protocol.md §Certifier contract (`wt_root.py open --role cert` … `reap`).
2. Copy its `records_file` to scratch, run `python3 "$CERT" handoff --certifier-return <envelope> --records <copy>` (sha256 + count), then copy it to `certifications/records/impl-audit.json`. Exit ≠ 0: step 3 uses `--unverified records-handoff` in place of `--records`.
3. Run the caller's certification. Fill `## Guards certified` from its statuses; `## Verdict` is the worse of Step 8's and the printed `verdict` (protocol §Verdicts order):
```bash
python3 "$CERT" run --claims <claims.json> --records <records.json> --repo . --ref <S> --name impl-audit --artifact <implementation-audit.md>
```
Running as a subagent (no Agent tool), or `--auto` without a certifier result: every claim is `unverified` (`certifier-unavailable`) → BLOCKED, `Cause: certification-unverified`.

A known issue you file here uses a placeholder ID, numbered later (see `skills/_shared/issue-id-placeholders.md`).

### 9. Commit the artifact
Commit per `skills/_shared/commit-after-work.md`. Artifact paths to stage:
- `three-pillars-docs/tp-designs/{design-name}/implementation-audit.md`
- `three-pillars-docs/tp-designs/{design-name}/certifications/impl-audit.claims.json` and `certifications/records/impl-audit.json` (if Step 8b ran)
- `three-pillars-docs/tp-designs/{design-name}/lock.json` (if refreshed)

Commit message: `Audit: {design-name} implementation`.

### 10. Present findings and prompt to invoke `/tp-design-learn`
Walk through the audit with the user. If the verdict is PASS, keep it brief. If NEEDS WORK, prioritize the gaps by severity and suggest whether to fix them, update the design to match reality, or accept the deviation.

After presenting the audit verdict, **prompt the user to run `/tp-design-learn` immediately** rather than relying on a soft reminder:

> Run `/tp-design-learn {design-name}` now to keep project docs current? (yes / no — default yes)

- On **yes** (or empty response): invoke `/tp-design-learn {design-name}` via the Skill tool directly. The user doesn't have to context-switch; doc updates land in the same session while the audit's findings are fresh.
- On **no**: surface the existing required-next-step warning so the consequences are explicit:
  > **Required next step**: Run `/tp-design-learn {design-name}` to propagate implementation results into `product_roadmap.md`, `architecture.md`, and `known_issues.md`, update the Design Inventory status, and scan for affected sibling designs. Do this BEFORE `/tp-design-complete` — that skill will refuse to archive a design whose roadmap status hasn't been updated (override available via `--skip-learn` for legacy designs only). Skipping this step causes the roadmap to go stale and downstream designs to miss critical updates.

This prompt is **interactive-only**. In `--auto` mode it does not fire — the autonomous chain is `/tp-run-full-design` Tier 5's responsibility, which already calls `/tp-design-learn --auto` after a clean audit verdict.

### Certify-sweep mode (`--certify-sweep`)
A post-merge mode, run once a design that shipped sweep and self claims has been released and the plugin reinstalled. It certifies the design's committed `sweep-NN.claims.json` and `self.claims.json`, writes its `sweep-ledger.md`, files the misses as known issues, and closes the design's open "sweep ledger pending" entry. After the first-run preflight it replaces Steps 0–10 and the Prerequisites (the design dir may be archived) with the runbook in `skills/_shared/certification-protocol.md` §Certify-sweep; follow it exactly. It refuses `--auto` and subagent runs (it dispatches `tp-certifier` through the Agent tool), refuses "release + reinstall first" when a `tp-certifier` dispatch reports an unknown subagent, and commits only from a dedicated `tp/{design-name}-certify-sweep` worktree.

## Rules
- **Validate `{design-name}`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — the final audit should be written by the design's current owner. Pass `--force-takeover` to claim the design before auditing it.
- This is a final gate, not a phase-level review. Read EVERYTHING — both designs, the full plan, and all implemented code.
- The two design documents (design.md + detailed-design.md) are the source of truth. The implementation serves them.
- Deviations aren't automatically bad — implementations often discover things the design missed. But they must be acknowledged and documented.
- Don't re-review individual task quality (that's `/tp-phase-review`'s job). Focus on the big picture: did we build what we set out to build?
- If existing `review.md` files from phase reviews flagged issues, check whether those issues were resolved.
- Keep `implementation-audit.md` under 80 lines. Dense and specific.

## Auto Mode

`--auto` is **Shape C verdict-only** per `skills/_shared/auto-mode.md` — this skill produces an audit verdict in `--auto`, never edits code regardless of finding confidence. Steps 1–8b run unchanged (load artifacts, scope coverage, interface fidelity, test suite, drift, gap, addition, shipped-promises checks, write `implementation-audit.md`). Step 10's interactive walk-through **and the prompt-to-invoke-`/tp-design-learn`** are both skipped — the autonomous chain is `/tp-run-full-design` Tier 5's responsibility, which already calls `/tp-design-learn --auto` after a clean audit verdict. This skill must NOT invoke `/tp-design-learn` from inside `--auto` mode: that would double-fire learn on the autonomous path and would re-introduce the "audit also writes docs" coupling that Shape C verdict-only explicitly forbids.

In `--auto`:
- **Per-finding self-assessment.** While compiling findings in step 8, self-assess **Confidence: High | Medium | Low** for each finding per the auto-mode convention. Confidence drives the verdict, not severity. Record confidence alongside the finding in the Gaps / Unintended Additions / Cross-Phase Drift sections of `implementation-audit.md`.
- **Deterministic verdict rule.** Compute the verdict from the confidence mix via `"$TP_ROOT"/skills/_shared/auto_verdict.py::compute_verdict(confidences)`:
  - **PASS** — empty findings list. Exit 0.
  - **PASS WITH NOTES** — all findings are High confidence; no Medium or Low present. Exit 0.
  - **NEEDS WORK** — any Medium or Low finding present. Exit non-zero.
  - **Certification join** — then `combine_verdict(<that verdict>, <Step 8b claim statuses + one `unverified` per counted phrase hit>)` (same module): `not-binding`/`false-red` → NEEDS WORK; UNVERIFIED → BLOCKED, `Cause: certification-unverified`, exit non-zero; KNOWN BYPASS proceeds, the bypass recorded verbatim.
- **Never auto-edit code or design artifacts.** Even High-confidence findings are recorded as notes in `implementation-audit.md`; the human acts on them. This is the line between Shape C apply-fixes (`/tp-design-audit`) and Shape C verdict-only (this skill).
- **Decisions log.** Append a Decision Entry to `three-pillars-docs/tp-designs/{design-name}/decisions.md` with the verdict, finding count by confidence (e.g., `2 High, 0 Medium, 0 Low → PASS WITH NOTES`), and **Confidence: High** (the verdict rule is deterministic, so the *decision-to-emit-the-verdict* is always high-confidence even when the underlying findings are not). Use `[tp-implementation-audit]` as the bare skill-name prefix.
- **NEEDS WORK escalation.** On NEEDS WORK, append a BLOCKED entry instead with **Cause: medium-low-confidence-findings** and **Details:** the full finding list with confidence labels, then exit non-zero so the orchestrator escalates.
- Use the canonical init/append snippet in `skills/_shared/auto-mode.md` to write `decisions.md` (create with schema-v1 header if missing, otherwise append).
- **Lock conflict**: handled by the collaboration preflight per the shared rule — exits BLOCKED with a `decisions.md` entry. Do not re-document here.
- Stage `decisions.md` alongside `implementation-audit.md` in step 9's commit.

**Contract: in `--auto`, this skill writes a verdict and never edits code or design artifacts. The verdict-to-confidence-mix mapping is deterministic.**
