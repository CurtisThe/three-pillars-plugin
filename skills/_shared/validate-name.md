# Name Validation

The `<design-name>` or `<spike-name>` argument must match `[a-z0-9-]+` only. Reject any value containing `/`, `..`, spaces, or characters outside `[a-z0-9-]`. This prevents path traversal — all TDD skills interpolate this value into file paths.

After successful validation, track the active design as the most-recently-used entry:
```bash
mkdir -p .claude
name="<validated-name>"
{ echo "$name"; grep -vx "$name" .claude/last-design 2>/dev/null; } | head -n 10 > .claude/last-design.tmp
mv .claude/last-design.tmp .claude/last-design
```
This prepends the name, removes any prior occurrence (dedup), and caps at 10 entries. The first line is always the currently active design.

Before writing `.claude/last-design`, ensure the project's `.gitignore` contains `.claude/last-design` (per-developer MRU state — should never be shared). If `.gitignore` does not contain that line, append it under a `# three-pillars session artifacts` comment, creating the comment only if it is not already present (other `_shared/` docs may have added it first).

**Never `git add .claude/last-design`** — it is gitignored, and staging it would require `-f` and produce a noisy "paths are ignored" hint. Write the file and stop.
