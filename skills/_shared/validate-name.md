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
