# Living-doc line-format conventions

> Used by `tp-design-learn`, `tp-spike-learn`, `tp-docs-update`, and any skill
> that writes to `three-pillars-docs/*.md`.

## Rule: keep lines under 800 non-whitespace characters

In the three-pillars dev repo, a CI check scans tracked `three-pillars-docs/*.md` files
(non-recursive, outside code fences) for lines exceeding 800 non-whitespace
characters. Since the `file-size-limits` design (2026-06-10) it is **fail-on-new**:
a violating line in a doc NOT listed in `.three-pillars/file-size-grandfather.txt`
**fails the check** (and the pre-commit hook blocks the commit); grandfathered docs
get an advisory `WARN:` only. A writer can no longer assume long lines merely warn —
an edit that pushes a line over the limit in a non-grandfathered doc hard-fails its
own commit.

**Every skill that writes to living docs must stay within this limit.**

## `*Last updated:` marker

Keep a single short marker on line 2 or 3 of each living doc:

```
*Last updated: YYYY-MM-DD — see [History](#history) for the full changelog.*
```

Update the date on every write. Do **not** expand this line with a prose summary —
put the summary in `## History` instead.

## `## History` section

A `## History` section lives at the **end** of the file. Each update adds exactly
**one new line at the top** of the list (newest-first). Format:

```
- YYYY-MM-DD — one-sentence summary of what changed.
```

Lines must stay under 800 non-whitespace chars. If a summary would be long, trim
it to a label and link: `- 2026-06-04 — collapsed Design Inventory to label+link format.`

## Status cells in tables (Design Inventory / Current Focus)

Status cells must use **short label + optional link**, not narrative prose:

| Label pattern | When to use |
|---|---|
| `Seeded` | seed exists, not yet designed |
| `Seeded — [seed](path/to/seed.md)` | with link |
| `Designing — [design](path)` | design.md in progress |
| `Implementing — PR open` | has an open PR |
| `Done — [design](path)` | merged, no PR# known |
| `Done — PR #NN — [design](path)` | merged with PR number |
| `Done — PARTIAL — [results](path)` | spike with partial GO |
| `Parked` | deliberately deferred |
| `Blocked` | blocked on another design |

Narrative rationale belongs in the linked design or seed, not in the table cell.
