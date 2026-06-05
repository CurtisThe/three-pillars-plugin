# Name Validation

## Regex check

The `{design-name}` or `{spike-name}` argument must match `[a-z0-9-]+` only. Reject any value containing `/`, `..`, spaces, or characters outside `[a-z0-9-]`. This prevents path traversal — all TDD skills interpolate this value into file paths.

## MRU update

After successful validation **and** after the lock/branch are claimed (i.e. inside the SKILL.md step that runs right after the collaboration preflight, not at name-validation time), track the active design as the most-recently-used entry:

```bash
mkdir -p .claude
name="{validated-name}"
{ echo "$name"; grep -vx "$name" .claude/last-design 2>/dev/null; } | head -n 10 > .claude/last-design.tmp
mv .claude/last-design.tmp .claude/last-design
# Ensure .gitignore has the MRU file under the shared comment header
if ! grep -qxF ".claude/last-design" .gitignore 2>/dev/null; then
  grep -qxF "# three-pillars session artifacts" .gitignore 2>/dev/null \
    || printf "\n# three-pillars session artifacts\n" >> .gitignore
  printf ".claude/last-design\n" >> .gitignore
fi
```

This prepends the name, removes any prior occurrence (dedup), and caps at 10 entries. The first line is always the currently active design.

**Never `git add .claude/last-design`** — it is gitignored, and staging it would require `-f` and produce a noisy "paths are ignored" hint. Write the file and stop.
