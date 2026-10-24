# Final Doc State

The living docs must be in their final shape **in the design PR itself**, so the merge needs no follow-up
docs PR and master never carries a pending token. This file is the one place the lifecycle is written down.
The code is `skills/_shared/final_doc_state.py`, built on `pending_flip.py`, `inventory_archive.py`,
`citation_liveness.py` and `reconcile_docs.py`.

## The lifecycle

| Step | Who | What lands in the living docs |
|---|---|---|
| Learn | `/tp-design-learn` | The inventory row, the Current State bullet and the Recent-completions entry, each carrying the one canonical token `Completion PR pending`. Learn writes the token; nothing else does. |
| Archive | `/tp-design-complete` 6f | `final_doc_state.py close` moves the slug's inventory rows to the roadmap archive, then flips the token to the number-free `Done (completion PR)` in the same call, so the archived copy is flipped too. 6f stages `paths[]`, commits, then runs `check`. |
| PR open | `/tp-design-complete` 6g, `/tp-run-full-design` Tier 6 | Right after `github_pr_author.py create` and before the review request, `reconcile_docs.py --slug {name} --pre-merge --pr N --apply --json` upgrades the text to `Done — PR #N`. A scoped add of `edits[].path`, the commit `docs({name}): completion PR #N in living docs`, then a fail-open push. |
| Merge | `/tp-post-merge` step 6 | Runs `check` only. It never edits or commits a living doc. |

The writeback runs only after a completion-PR create (`--base {default}`). On Tier 6's fold-conflict
legacy fallback (a candidate-to-`tp` PR) the design is not archived, so it does not run. If the create or
the push fails, the number-free `Done (completion PR)` stays; that is the default, not an error state.

## Fragment mode

When `three-pillars-docs/changes/{name}.md` exists the docs compile owns the final shape (`skills/_shared/living-doc-fragments.md`): `close` and the PR-number writeback are no-ops, and `check` reports `pending-compile` (exit 0). With `--base` it also runs the living-doc guard and reports it as `guard`; a refusal exits 1: `python3 "$TP_ROOT"/skills/_shared/final_doc_state.py check --slug {name} --base origin/{base} --json`. A design with no fragment keeps the lifecycle above.

## `close`

`python3 "$TP_ROOT"/skills/_shared/final_doc_state.py close --slug {name} --json` prints
`{"moved": n, "flipped": m, "skipped": [...], "paths": [...], "refused": null}`.

- `skipped` is the flipper's list verbatim: `{file, line_no, reason}` with reason `unattributable`,
  `ambiguous-multi-match` or `decode-failure`. Such a line is left unchanged and `check` reports it.
- `paths` holds only the six living-doc files (the keys and values of `living_doc_archive.ARCHIVES`).
- A mover verifier refusal exits 1 with `refused` set and writes nothing.
- A second run reports `moved` 0, `flipped` 0 and writes nothing. A repo with no roadmap is a clean no-op.

## `check`

`python3 "$TP_ROOT"/skills/_shared/final_doc_state.py check --slug {name} --json` prints
`{"verdict": "verified" | "drift", "rows": [...], "pending": [...], "cites": [...], "fix": [...]}`
and exits 0 for `verified`, 1 for `drift`.

- `rows`: the slug's inventory rows still in the live roadmap.
- `pending`: every pending token still naming the slug, as `{file, line, form, owner}`. `form` is
  `canonical` or the frozen `legacy` forms. `owner` is the slug, or `null` when the line cannot be
  attributed to one slug (never silent: it is drift, reported for every slug the line mentions as a
  whole token). A living doc that is not valid UTF-8 is reported as `form` `decode-failure`, line 0,
  for every slug: `check` never passes a file it could not read.
- `cites`: dead `tp-designs/{slug}/` cites in the living docs, the same scope as
  `reconcile_docs.py --archive-cites` (History sections and fenced blocks excluded). Code cites stay with
  the CI citation-liveness check.
- `fix`: the inventory move line when `rows` is non-empty, the `--pre-merge` line when a canonical,
  slug-owned token sits alone on its line, the `--archive-cites` line when `cites` is non-empty, and one
  `hand-edit <file>:<line>` per legacy, unattributable or same-line-duplicate token (`<file>:0` for an
  undecodable file).

## Drift recovery

Apply the printed `fix` lines, or make the `hand-edit <file>:<line>` edit, then re-run 6f's `close` and
`check` (both idempotent) and commit the result scoped. Interactive `/tp-design-complete` stops before
PR-open on drift, with the archival commit already landed. `--auto` logs the drift to the archived
`decisions.md`, commits that scoped, and continues.

The mechanical row move gets no new Roadmap History line: learn's History line records the completion.
