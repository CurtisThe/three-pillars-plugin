# File-size caps

The shipped source of the framework's file-size caps. A file violates when
it exceeds **either** axis (lines or chars). These are not suggestions: the
limits exist because the agent's own tools degrade on large files — the
Read tool returns only ~2000 lines per call (a longer file must be paged,
so no agent takes it in at a glance); the Edit tool requires a unique string
match (anchors get ambiguous and fragile in long files); and a
multi-thousand-line file costs ~25–30k tokens to ingest, taxing every
review / audit / council pass.

| File type | Soft-warn | Hard cap (blocks commit) |
|---|---|---|
| Code — `.py` `.sh` `.js` `.ts` | 350 lines | 500 lines |
| Markdown / `SKILL.md` | 300 lines | 500 lines |
| Tests — `test_*.py` | 300 lines | 500 lines |
| Chars — every class above | 35,000 | 50,000 |
| `three-pillars-docs/vision.md` | 8,000 chars | **12,000 chars** |
| `three-pillars-docs/architecture.md` | 15,000 chars | **25,000 chars** |
| `three-pillars-docs/product_roadmap.md` | 10,000 chars | **15,000 chars** |
| `three-pillars-docs/known_issues.md` | 12,000 chars | **20,000 chars** |
| `skills/*/SKILL.md` | 20,000 chars | **35,000 chars** |
| `skills/_shared/*.md` | 15,000 chars | **25,000 chars** |

The per-doc rows override the chars row for those paths (the lines axis is
unchanged). `SKILL.md` and `_shared/*.md` rows apply in the framework tree
only. In a consumer repo an over-cap living doc is WARNed, never blocked; the
next framework writer rolls it over to the archive. Cold files
(`*_archive.md`, `known_issues_resolved.md`, `known_issues_low.md`) are exempt.

Nothing exceeds 500 lines or 50,000 chars — tests included. When a file
nears the soft-warn, split it by responsibility (one cohesive module or
behaviour per file; a test module splits by the unit or scenario under
test). Code generators must emit split files, not monoliths.

## Rationale per cap

- **350 / 500 lines (code)** — the soft threshold is where a file starts
  needing `offset`/`limit` paging to read whole; the hard cap is where
  the unique-match Edit contract and the token cost become untenable.
- **300 / 500 lines (Markdown / `SKILL.md`)** — instructions are read at
  the start of every skill invocation, so a long file taxes every run, not
  just the edits.
- **300 / 500 lines (tests)** — a long test file hides the unit under test;
  the cap keeps one scenario per file so a failure points at one behaviour.
- **35,000 / 50,000 chars** — the per-call token budget a file costs to
  ingest, independent of line count (a wide line is as expensive as a tall
  one).

## Enforcement

`file_size_guard.py` is the single shared predicate — one source of truth
for the caps above, run by the commit guard's `pre-commit` step. Soft thresholds **warn**; the hard caps
**block the commit**. A file exceeds the soft threshold at exactly the
soft value (warn), and exceeds the hard cap strictly above it (block).

**Advisory unless the guard is installed with file-size on.** The caps are
enforced at commit only when the commit guard is installed with the
file-size sub-ask on (`commit_guard.file_size` true — see
[`consumer-offers.md`](consumer-offers.md)); otherwise the table is
advisory. Pre-existing offenders are grandfathered in
`.three-pillars/file-size-grandfather.txt` (warn-only; the list only
shrinks, and `file_size_guard.py --all-tracked` reports a stale entry as
`STALE` and exits 1).

For existing large files, `file_size_guard.py --emit-grandfather` prints
the current qualifiers (allowlist ignored), sorted, so a grandfather list
can be seeded without hand-typing paths.

## Exemptions

`three-pillars-docs/completed-tp-designs/**`, in-flight
`three-pillars-docs/tp-designs/**` (append-only design logs cannot split),
`three-pillars-docs/known_issues_resolved.md`,
`three-pillars-docs/product_roadmap_archive.md`, and
`three-pillars-docs/architecture_archive.md`.
