# Known-issue ID placeholders

Two branches that each file a known issue pick the same next number. To avoid that, a
branch never picks one: it files the issue under a **placeholder** and the number is
assigned later, once, against the base.

## The form

`<S>-new-<slug>` where `<S>` is the issue letter (the series prefix the file already
uses) and `<slug>` is a short kebab-case name, e.g. `<S>-new-driver-defers-preamble`.

## Where it counts

A placeholder counts only as a `###` heading in the two issue files:
`three-pillars-docs/known_issues.md` and `three-pillars-docs/known_issues_resolved.md`.
Cite it anywhere else (roadmap, architecture, decisions, other docs) by the same
placeholder text; the numbering pass rewrites every occurrence of the placeholder
in every committed `.md` file across the tree, heading and citations alike.

## When the numbering runs

The CLI is `python3 "$TP_ROOT"/skills/_shared/number_issues.py --base <base> --commit`.
Run `git fetch origin <base>` first: `--base <base>` numbers against `origin/<base>`
whenever that remote-tracking ref exists, and falls back to the local `<base>` only
when it does not (a stale local base would reissue a teammate's just-landed ID).
It reads committed `HEAD` only, assigns the next free number per letter, renumbers a
branch ID that truly collides with one the base added, and commits the result. With
nothing to number it is a no-op. Without `--commit`/`--write` it only prints the plan
(JSON) and changes nothing. Exit `3` = dirty tree (nothing written); exit `4` = the
commit failed (e.g. a pre-commit hook) and the rewrite was rolled back.
It skips an inherited placeholder the base has since numbered: one headed in the issue files
at the merge-base but no longer at the base. The merge brings the base's number in. One the base
still holds unnumbered is numbered as usual.

- `/tp-design-complete` runs it before the archive move.
- `/tp-merge-from-main` runs it before the driver merges the base in.

Both fetch the base, then pass `--base <base> --commit`. The numbering commit is pushed
with the branch, and the approval/proof chain crosses it because `numbering_carry`
rebuilds it byte for byte from its parent and its `Numbered-against:` base. That is
what lets it carry: an ordinary branch commit stales the approval.

## The `/tp-merge` refusal

`/tp-merge` refuses a PR head that still holds unnumbered issue IDs (a `### <S>-new-<slug>`
heading in either issue file) and prints `unnumbered issue IDs: run number_issues.py`.
Run the CLI, push, and re-run `/tp-merge`. If the CLI reports the IDs as inherited (the base
already numbered them), it leaves them alone: run `/tp-merge-from-main` instead, which merges
the base's numbers in. Branch text citing such a placeholder keeps the placeholder text.
A merge started from the HTML briefing runs the same check before it calls `land()`.
