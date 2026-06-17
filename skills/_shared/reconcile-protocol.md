# Reconcile Protocol — Amendment Obligation

When a commit changes behavior owned by an **archived** design, the author must
append a dated amendment to that design's `decisions.md`. The obligation keys to
the _change_, not the ceremony class — `light` and `just-do-it` weight-class
commits are included exactly as `full`-class ones.

## Finding the owning design

Use the reverse walk in `three-pillars-docs/architecture.md §"Finding the
spawning design"` to identify the archived design.

## Obligation

Append a dated amendment block to
`three-pillars-docs/completed-tp-designs/{slug}/decisions.md`:

```markdown
### [amendment YYYY-MM-DD] <one-line: what changed>
**Supersedes**: <the artifact section/claim now stale>
**Change**: <the behavior as of this commit>
**Commit**: <sha> / PR #NN
**Why**: <1–2 lines>
```

The amendment block is **append-only** — the original text above it is never
edited. The dated heading and the four fields are the full template; no other
ceremony is required.

## Append-only rule

Never edit existing content in `decisions.md`. The historical record is
preserved exactly as written; new truth is appended below it. Exemplar: the
`### [AMENDMENT 2026-06-10] D3b SUPERSEDED` block in
`three-pillars-docs/completed-tp-designs/deterministic-merge-gate/decisions.md`
(commit `0e55c76`) preserves the original D3b text above and appends the
SKIPPED/NEUTRAL correction below. That pattern is the canonical form.

## Who runs what when

1. **Commit author** — append at commit time whenever the commit touches behavior
   owned by an archived design.
2. **`/tp-design-learn` step 9** — when an affected sibling is an archived design
   whose documented behavior this design changed, propose the dated amendment.
   In `--auto`: apply the amendment and log to `decisions.md` with
   `Confidence` per `auto-mode.md` rules.
3. **`/tp-post-merge` step 6 reconcile report** — advisory reminder when the
   scan finds stale rows or dead cites; the author still does the writing.

## New-code citation convention

New code cites its spawning design with a path-free `design: {slug}` line in
the docstring or header comment — resolved via the reverse walk, never as a
`three-pillars-docs/tp-designs/{slug}/` path (it rots at archive time). Existing
path cites are rewritten by `/tp-design-complete` at archive time via
`reconcile_docs.py --archive-cites`.

## Archive carve-out (citation liveness in append-only files)

Append-only archives (`known_issues_resolved.md`, `completed-tp-designs/**`, History
sections) promise *verbatim* content — no rewording after the fact. Mechanical
citation-liveness repoints are the **one sanctioned edit class** inside that promise:
when a design archives, `reconcile_docs.py` rewrites its `tp-designs/{slug}` path cites
to `completed-tp-designs/{slug}` wherever they appear, archives included, so the trail
stays *followable* — a dead path serves the reader worse than a mechanically-updated
one. "Verbatim" governs prose, judgments, and dates; it does not freeze path spellings.
(History *sections* inside living docs remain fully excluded from rewriting — the
detector's `History`-heading exclusion is unchanged; this carve-out is about archive
*files* whose body is entry text, not ledger lines.)
