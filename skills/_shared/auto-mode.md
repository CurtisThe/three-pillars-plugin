# Auto Mode Convention

When a skill supports `--auto`, it replaces human interaction with self-assessment and logs every decision to `decisions.md` in the spike's design directory.

## decisions.md Format

### Initialization (done once by the orchestrator or the first auto skill)

```markdown
# Autonomous Spike — Decision Log

## Run Metadata
**Started**: <ISO timestamp>
**Spike**: <spike-name>
**Design**: docs/tdd-designs/<spike-name>/design.md
```

### Decision Entry (appended by each skill)

```markdown
### [<skill-name>] <short title>
**Question**: What would have been asked of the user
**Decided**: What was chosen
**Reasoning**: Why this choice was made
**Confidence**: High | Medium | Low
```

### Simplification Entry (appended by spike-implement on retry)

```markdown
### [spike-implement] <task-id> — simplification (attempt N/3)
**Problem**: What failed and why
**Simplification**: How the approach was reduced
**Outcome**: Success | Failed — will retry | Abandoned (max retries)
```

### Phase Boundary Entry (appended by spike-implement)

```markdown
### [spike-implement] Phase N boundary
**Tasks completed**: X/Y
**Tasks blocked**: list with reasons
**Decision**: Continue | Stop (all blocked)
**Evidence**: Brief summary of what was built/learned
```

## Rules for Auto Mode in Skills

1. **Never block on user input** — make the best available decision and log it.
2. **Always append to decisions.md** — never overwrite. Each entry is chronological.
3. **If decisions.md doesn't exist, create it** with the Run Metadata header.
4. **Confidence levels**:
   - **High**: Clear from design/context, only one reasonable choice.
   - **Medium**: Multiple reasonable options, picked the most aligned with design.md.
   - **Low**: Genuinely uncertain, went with best guess. User should review.
5. **On failure**: Log the failure, attempt to simplify (if applicable), continue. Don't stop the pipeline unless truly stuck.
