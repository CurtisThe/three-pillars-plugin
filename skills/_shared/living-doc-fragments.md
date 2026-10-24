# Living-doc fragments

A design branch never edits a shared living doc (`architecture.md`, `product_roadmap.md`,
`known_issues.md`, their archives and Low parts). Its doc changes live in one file,
`three-pillars-docs/changes/<slug>.md`. After the PR merges, `/tp-post-merge` folds every pending fragment
into the docs in one commit on the rolling `tp/docs-compile` branch (`skills/_shared/docs_compile.py`),
numbers the issue IDs and rolls History and caps over. Two design PRs therefore never conflict on a doc.
Readers see a merged-but-uncompiled design through `pending_changes.py summary`
(`skills/_shared/read-project-docs.md`). `vision.md` is never folded.

## The grammar

`python3 "$TP_ROOT"/skills/_shared/changes_fragment.py validate <path> [--repo-root R] [--require-learned]`
checks a fragment: exit 0 ok, 1 problems (each printed `changes_fragment: <section>: <reason>`; a missing
file is `file: missing`), 2 usage. With `--repo-root` it also checks that every `###` heading and every `-`
line exists in the live doc, after the other pending fragments are folded onto it in `(date, slug)` order.

**Frontmatter** (required; these keys only):

- `slug` is the file stem, `[a-z0-9-]+`, never `docs-compile`.
- `kind` is `design` or `spike`.
- `date` is `YYYY-MM-DD`, the day the last writer wrote. The compile uses it for `*Last updated:*` and
  History, never the clock, so the same fragments give the same text on any day.
- `learned` is `YYYY-MM-DD`, optional. Only `/tp-design-learn` and `/tp-spike-learn` set it (see below).

Frontmatter with no section is a valid fragment. Then only these `##` headings, each at most once, in any
order:

| Section | Holds |
|---|---|
| `## Roadmap` | `### <exact heading in product_roadmap.md>` blocks of `+ <line>` and `- <line>` |
| `## Architecture` | the same, against `architecture.md` |
| `## Known issues — add` | verbatim `### <H\|M\|L>-new-<slug>: title` blocks (placeholder IDs) |
| `## Known issues — resolve` | `- <ID>: <note>` lines with a numbered ID |
| `## Vision` | prose; never folded |

- `+ <line>` inserts and `- <line>` removes one existing line, which must match exactly (the doc line
  `- old row` is written `- - old row`). A `-` followed by `+` replaces in place. A lone `+` appends at the
  end of the section, or prepends (newest-first) under `Recent completions` and any History heading.
- `{pr}` in a line expands to `PR #N`, or to `completion PR` when the number is unknown. Until the
  completion PR opens, a status cell reads `Completion PR pending` per `skills/_shared/living-doc-format.md`.
- A known issue is filed under a placeholder ID (`skills/_shared/issue-id-placeholders.md`); the compile
  numbers it. An H block lands under `## Critical / High`, an M block under `## Medium`, an L block in the
  Low part with room. A resolve line moves the entry verbatim to the resolved-issues archive under its
  original section, headed `### <ID> (RESOLVED <date>): …`, with the note appended.
- `## Vision` stays in the file until the operator applies it with `/tp-docs-update` (which deletes it).
- A line stays under 800 non-whitespace characters.

## Examples

Each fenced example labelled `fragment` is parsed and validated by `test_living_doc_fragments_md.py`.

A learn fragment with every section:

```fragment full
---
slug: demo
kind: design
date: 2026-10-22
learned: 2026-10-22
---

## Roadmap

### Design Inventory
+ | `demo` | One-line what | Completion PR pending |

### Recent completions
+ - **`demo`** — Done — {pr}; one-line summary

### Roadmap History
+ - 2026-10-22 — `demo` shipped; see its decisions.md.

## Architecture

### Key Components
+ - `demo.py` does one thing and ships to a user repo with the plugin.

## Known issues — add

### M-new-demo-edge: one-line title

The entry exactly as it will read in the known-issues doc.

## Known issues — resolve

- M34: fixed by the demo design

## Vision

The demo shows a principle is too narrow; apply it with the docs-update skill.
```

A `+ | …` row folds after the last row of the LAST table under its `###` heading (subsections included), so
the `### Design Inventory` row above lands in the inventory's last table; to file it in another table, head
the block with that subsection instead (`### Active (canon-reframe arc)`). A heading with no table is a
conflict.

A learn fragment for a design with no doc change (the learn skill always writes the file):

```fragment frontmatter-only
---
slug: demo
kind: design
date: 2026-10-22
learned: 2026-10-22
---
```

What `/tp-design` writes at registration (no `learned`, so it never reads as "learn ran"):

```fragment registration
---
slug: demo
kind: design
date: 2026-10-20
---

## Roadmap

### Design Inventory
+ | `demo` | One-line what | Designing |
```

## Rules for every writer

1. **Create the fragment when absent** (frontmatter `slug`, `kind`, today's `date`) and **edit it in place
   when present**: a `+` row for something the docs do not hold yet (the `/tp-design` inventory row, say) is
   rewritten, never followed by a `-` of it.
2. **Set `date` to the day you write.** Stage the fragment by its exact path and **no shared living doc**.
   `skills/_shared/living_doc_guard.py` refuses a design branch that edits one (at `/tp-design-complete`
   and `final_doc_state.py check --base`) and names the fragment to write instead.
3. **Run `validate` after writing**; fix every problem it names before the commit.
4. Writers: `/tp-design` and `/tp-spike` put the Design Inventory row and Current Focus lines under
   `## Roadmap`; the Tier 5.6 cert `issues apply --fragment` and the certification sweep file
   `## Known issues — add` blocks and a `## Known issues — resolve` line; `/tp-design-complete` step 6e
   removes the design's own Current Focus row (the compile renumbers priorities after the fold);
   `/tp-spike-auto` writes only through `/tp-spike-learn --auto`.

## Rules for the learn skills

- `/tp-design-learn` and `/tp-spike-learn` **always write the fragment**, frontmatter-only when there is no
  doc change, so fragment mode never depends on learn finding an edit. Each of their proposed edits goes
  into a section above, never into a living doc.
- They set `date` and `learned` to today and run `validate ... --require-learned`. Registration, Tier 5.6,
  the sweep and `/tp-design-complete` never set `learned`: `/tp-design-complete` accepts a fragment that
  validates with `--require-learned` as "learn ran", so a registration-only fragment does not count.
- The compile, not learn, bumps `*Last updated:*`, rolls History and doc caps over, files an L block into
  the Low part and stages the archives.
- A `## Vision` section is rare; learn flags it for the operator and never edits `vision.md`.

## Legacy designs

`.three-pillars/living-doc-legacy.txt` lists the slugs whose `tp/` branch was in flight when fragments
landed. The guard exempts them: their PR keeps the living-doc edits it already holds and merges as before,
and their learn edits the docs as before. They still write the frontmatter-only fragment so the learn-ran
check holds. A slug may be listed only if its branch was already in flight when the repo upgraded; the list only
shrinks afterwards (delete a line when its branch merges). Everything else
writes fragments only.
