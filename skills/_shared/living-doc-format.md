# Living-doc line-format conventions

> Used by `tp-design-learn`, `tp-spike-learn`, `tp-docs-update`, and any skill
> that writes to `three-pillars-docs/*.md`.

## Rule: keep lines under 800 non-whitespace characters

A CI check in the three-pillars dev repo scans tracked `three-pillars-docs/*.md` files
(non-recursive, outside code fences) for lines exceeding 800 non-whitespace
characters. Since the `file-size-limits` design (2026-06-10) it is **fail-on-new**:
a violating line in a doc NOT listed in `.three-pillars/file-size-grandfather.txt`
**fails the check** (and the pre-commit hook blocks the commit); grandfathered docs
get an advisory `WARN:` only. A writer can no longer assume long lines merely warn —
an edit that pushes a line over the limit in a non-grandfathered doc hard-fails its
own commit.

**Every skill that writes to living docs must stay within this limit.** This is an authoring
rule, enforced (framework repo only): in your repo nothing checks it, so the writer keeps to it.

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

Keep the run at **15** live entries or fewer. After appending, the writer rolls
the older entries over **in the same commit**: run
`python3 "$TP_ROOT"/skills/_shared/history_rollover.py --doc <repo-relative doc>`
for each living doc touched (default keep 15; no History section or missing doc
→ it does nothing and says so; a missing archive is created with a header on the
first rollover) and stage the doc's archive in the same commit. New History
entries are one line with a link to the design's `decisions.md`. A Design
Inventory row that is not found live is looked up in
`product_roadmap_archive.md`.

## Status cells in tables (Design Inventory / Current Focus)

Status cells must use **short label + optional link**, not narrative prose:

| Label pattern | When to use |
|---|---|
| `Seeded` | seed exists, not yet designed |
| `Seeded — [seed](path/to/seed.md)` | with link |
| `Designing — [design](path)` | design.md in progress |
| `Implementing — PR open` | has an open PR |
| `Completion PR pending` | written by learn until the completion PR opens; the slug in backticks leads the line, sits inside the same parenthetical as the token, or directly precedes the token's parenthetical |
| `Done (completion PR)` | completion PR open, number unknown |
| `Done — [design](path)` | merged, no PR# known |
| `Done — PR #NN — [design](path)` | merged with PR number |
| `Done — PARTIAL — [results](path)` | spike with partial GO |
| `Parked` | deliberately deferred |
| `Blocked` | blocked on another design |

Narrative rationale belongs in the linked design or seed, not in the table cell.

## Pending token

There is one pending token, `Completion PR pending`, used in every non-History status spot that names the slug (inventory Status cell, Current State bullet, Recent-completions entry, queue line). Never write free "awaiting PR" prose. The three placements above (leads, parenthetical, directly precedes) are the only ones the flipper attributes, and only when they agree (a line led by one slug whose token parenthetical names or follows another is unattributable); any other placement is reported by `final_doc_state.py check` as drift needing a hand edit. `/tp-design-complete` flips the token to a done form.

## Condensed shape and caps

A living doc is an index of what is true now; the archive is the record. Writers keep the doc condensed:

- **One bullet or row per item** (one per issue, design or decision). No multi-paragraph entries.
- **History and evidence go to the archive**: `*_archive.md`, `known_issues_resolved.md` and `known_issues_low.md`. Link to the design's `decisions.md` instead of copying its evidence into the live doc.
- **Caps**: `skills/_shared/file_size_guard.py` is the source of the per-doc soft and hard caps. This file does not restate the numbers.
- **Rollover**: after writing, run `python3 "$TP_ROOT"/skills/_shared/doc_rollover.py --doc <repo-relative doc>`. It rolls the oldest History entries into the archive until the doc is under its soft cap; stage the doc's archive in the same commit. It prints `CONDENSE-NEEDED` when the doc is still over, and an over-cap doc in a consumer repo is warned, never blocked.
- **Readers skip archives**: `/tp-guide`, design and audits read only the live docs. Only ID-resolution and guard readers also read `known_issues_low.md`.
- **Promoting a Low** to Medium (or High) moves its entry out of `known_issues_low.md` back into `known_issues.md` in the same commit (D5b).
