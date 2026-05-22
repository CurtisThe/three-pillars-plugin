# Auto Mode Convention

When a skill supports `--auto`, it replaces human interaction with self-assessment and logs every decision to `decisions.md` in the design directory.

This convention covers spike skills (`/tp-spike-*`) and the seven design-pipeline skills retrofitted by design `design-pipeline-auto-mode` (`/tp-design`, `/tp-design-detail`, `/tp-design-audit`, `/tp-plan`, `/tp-phase-implement`, `/tp-implementation-audit`, `/tp-design-learn`). Both pipelines share the `decisions.md` format and rules below.

## Skill shapes

`--auto` skills come in three shapes. Each `## Auto Mode` section in a SKILL.md should declare which shape it follows.

### Shape A — Validator gate
The skill runs a deterministic check and either passes or blocks; it never generates content in `--auto`. Canonical example: `/tp-design --auto` delegates to `skills/_shared/validate_design_floor.py`, which exits 0 on PASS or 1 on BLOCKED with a JSON verdict on stderr. Shape A consumers log "accepted at floor schema vN" + High confidence on PASS, or the verdict JSON on BLOCKED.

### Shape B — Generator
The skill derives its output from existing artifacts (design.md, code, prior plan/audit) without user Q&A. Every judgment call is self-assessed (Confidence: High/Medium/Low) and logged. Used by `/tp-design-detail`, `/tp-plan`, `/tp-design-learn`, `/tp-phase-implement`, and all spike skills. `/tp-phase-implement` adds a retry-and-simplify failure mode — see Rule 6.

### Shape C — Audit with confidence-based dispatch
The skill produces audit findings (interactive mode runs `/council`, walks through findings with the user, applies approved fixes). In `--auto`, every finding is self-assessed for Confidence. **Confidence drives dispatch, not severity.** High ⇒ auto-resolve (design-audit applies the fix; impl-audit logs the verdict). Medium/Low ⇒ escalate BLOCKED with the finding list. Severity informs typical confidence (MINOR with an obvious fix → usually High; CRITICAL → usually Low) but the dispatch is by confidence. **MISALIGNMENT findings get High only when `design.md`'s Vision-alignment section already names and justifies the exact tension**; otherwise they're Low and escalate. `/tp-design-audit` applies fixes; `/tp-implementation-audit` writes a verdict only (PASS / PASS WITH NOTES / NEEDS WORK) — never edits code regardless of confidence.

The verdict mapping for the verdict-only variant is deterministic — empty findings ⇒ `PASS`, all-High ⇒ `PASS WITH NOTES`, any Medium/Low ⇒ `NEEDS WORK` (non-zero exit). It is extracted to `skills/_shared/auto_verdict.py::compute_verdict(confidences: list[str]) -> tuple[str, int]` so that consumers (e.g., `/tp-implementation-audit`) call one canonical implementation rather than restating the table.

## decisions.md Format

`decisions.md` lives at `three-pillars-docs/tp-designs/{name}/decisions.md` and is committed (not gitignored — it is the permanent audit trail for an autonomous run). `handoff.md` in the same directory is the only ephemeral file; the project's `.gitignore` should contain `three-pillars-docs/tp-designs/*/handoff.md` (with a `# three-pillars session artifacts` comment).

### Schema version

The file starts with `# Decisions log — schema v1` on line 1. The current schema version is 1; future changes bump the integer and update consumers accordingly.

### Initialization + append (canonical snippet)

The first `--auto` skill invoked within a design directory creates the file with the schema-v1 header; subsequent invocations append. The init/append protocol is stdlib-only and should appear inline in each SKILL.md's `## Auto Mode` section (or be invoked from a thin `skills/_shared/auto_decisions.py` helper if a future change consolidates it):

```python
from pathlib import Path
SCHEMA_HEADER = "# Decisions log — schema v1\n"
def append_decision(design_dir: Path, entry: str) -> None:
    log = design_dir / "decisions.md"
    if not log.exists():
        log.write_text(SCHEMA_HEADER)
    with log.open("a") as f:
        f.write("\n" + entry.rstrip() + "\n")
```

### Decision Entry framing

Each entry is prefixed with `[{skill-name}]` using the plain skill name (`[tp-design-audit]`, `[tp-spike-implement]`, etc.). There is intentionally **no `[spike]` or `[design]` pipeline tag** — the skill name uniquely identifies the caller, and a parallel tag would only duplicate that information. Tooling that needs to filter by pipeline can match the `tp-spike-` vs `tp-` prefix on the skill name.

### Decision Entry (appended by each skill)

```markdown
### [{skill-name}] <short title>
**Question**: What would have been asked of the user
**Decided**: What was chosen
**Reasoning**: Why this choice was made
**Confidence**: High | Medium | Low
```

### Simplification Entry (phase/spike-implement on retry)

```markdown
### [{skill-name}] {task-id} — simplification (attempt N/3)
**Problem**: What failed and why
**Simplification**: How the approach was reduced. (TDD: simpler implementation only — never modify the test.)
**Outcome**: Success | Failed — will retry | Abandoned (max retries)
```

### Phase Boundary Entry (phase/spike-implement)

```markdown
### [{skill-name}] Phase N boundary
**Tasks completed**: X/Y
**Tasks blocked**: list with reasons
**Decision**: Continue | Stop (all blocked)
**Evidence**: Brief summary of what was built/learned
```

### BLOCKED Entry (Shape A/C escalation, lock conflict)

```markdown
### [{skill-name}] BLOCKED — <reason>
**Cause**: lock-conflict | floor-validator | medium-low-confidence-findings
**Details**: <json verdict or finding list>
```

## Rules for Auto Mode in Skills

1. **Never block on user input** — make the best available decision and log it.
2. **Always append to decisions.md** — never overwrite. Each entry is chronological.
3. **If decisions.md doesn't exist, create it** with the schema-v1 header using the canonical snippet above.
4. **Confidence levels**:
   - **High**: Clear from design/context, only one reasonable choice.
   - **Medium**: Multiple reasonable options, picked the most aligned with design.md.
   - **Low**: Genuinely uncertain, went with best guess. User should review.
5. **Lock conflict in `--auto` is BLOCKED, not a prompt**. When `lock.json` is owned by another user, append a BLOCKED entry and exit non-zero. Never prompt for `--force-takeover`.
6. **On failure**: Log the failure, attempt to simplify if applicable (`/tp-phase-implement` and `/tp-spike-implement` retry up to N=3; TDD-constrained means swap implementation for a simpler equivalent that still satisfies the test — never edit the test), continue. Don't stop the pipeline unless truly stuck.
