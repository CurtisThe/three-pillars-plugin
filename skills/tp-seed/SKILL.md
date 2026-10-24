---
name: tp-seed
description: Capture an idea as a seed (seed.md) with its weight class settled up front. Checks the open seeds first and offers to add the idea to a close match as a new Part, scores the four axes, asks for the lightest class that fits with a rough token cost beside each class, writes the seed through seed_write.py and commits it on a seed branch. No design work.
argument-hint: "{slug} [text]"
---

# /tp-seed \<slug\> [text]

Write an idea down for later as `three-pillars-docs/tp-designs/<slug>/seed.md`, with the
weight class already chosen, so the later `/tp-promote` or `/tp-design` does not pay for more
ceremony than the work needs. This skill **only writes and commits a seed**: no `design.md`,
no plan, no lock, no launch.

Ask the operator **one question per `AskUserQuestion` card**, never a batch. Give each option
plain-words context (what it means, what happens if picked) and put the recommended option
first, marked "(Recommended)". A question with an obvious default is not asked: take the
default and say so.

## Arguments

- `<slug>` (required): kebab-case seed name matching `[a-z0-9-]+`.
- `[text]` (optional): the idea in the operator's words. When absent, ask for it (one card)
  in step 2.

## Steps

1. **Run first-run preflight** per `skills/_shared/first-run.md`, then **validate `<slug>`**
   per `skills/_shared/validate-name.md`: reject any value with `/`, `..`, spaces or
   characters outside `[a-z0-9-]`. The slug names a directory, so a bad value never reaches
   a path.

2. **Collect the idea.** Use `[text]`, or ask for it. Keep the operator's words: they become
   the seed's `## Problem`. Draft a one-paragraph `## Direction` (the likely fix, no design
   work), the `## Open questions` the idea leaves, and a `## Consumer-repo behaviour` line
   (what a user's repo sees if this lands, or "none").

3. **Merge first.** A second seed on the same idea costs more than a new Part on the first.
   Seed text reaches the writer through files only, never through argv: inside a double-quoted
   argument a backtick is command substitution, so never put seed text in double-quoted argv.
   Each file is written with a quoted heredoc whose delimiter no line of the text equals:
   `SEED_TEXT_END` by default, never `EOF` (seed text can hold an `EOF` line); when a line of
   the text is `SEED_TEXT_END`, use `SEED_TEXT_END_2` (then `_3`, …) for that file. Before the
   first file, keep the scratch dir out of `git status` (fail-open: `False` only means
   `.tp-scratch/` may show there):
   ```bash
   python3 -c "import sys; sys.path.insert(0, '$TP_ROOT/skills/_shared'); import scratch_root; scratch_root.ensure_excluded('.')"
   ```
   - List every seed by name:
     `python3 "$TP_ROOT"/skills/_shared/run_retro.py known-items --repo . --out "$(mktemp -d)/known-items.json"`
     and read the file (one `{id, kind: "seed", retro_key, text}` row per `seed.md`), so a
     seed on the same idea under another slug is seen.
   - Rank the open seeds against the idea: write the idea to a file, then run `similar` on it:
     ```bash
     mkdir -p .tp-scratch/seed/<slug> && cat > .tp-scratch/seed/<slug>/text.md <<'SEED_TEXT_END'
     <the idea, in the operator's words>
     SEED_TEXT_END
     python3 "$TP_ROOT"/skills/_shared/seed_write.py similar --text-file .tp-scratch/seed/<slug>/text.md --repo .
     ```
     It prints up to 3 `<slug> <shared-word count>` lines, best first; nothing printed means no
     open seed shares a word. A word count is a hint, not a verdict: read the `## Problem` of
     each listed seed (and of any `known-items` slug that looks related) before calling it close.
   - On a close match, ask one card: add the idea to `<match>` as a new Part
     **(Recommended)**, or keep it as its own seed `<slug>`. On add, write the Part text the
     same way, under `<match>`, and run `amend` on it:
     ```bash
     mkdir -p .tp-scratch/seed/<match> && cat > .tp-scratch/seed/<match>/text.md <<'SEED_TEXT_END'
     <the Part text>
     SEED_TEXT_END
     python3 "$TP_ROOT"/skills/_shared/seed_write.py amend <match> --text-file .tp-scratch/seed/<match>/text.md --repo .
     ```
     It prints `amended <match>: Part <N>`. Then `rm -rf .tp-scratch/seed/<slug> .tp-scratch/seed/<match>`
     and go to step 7 with `<match>`'s `seed.md` as the only path. The match keeps its own
     class; `/tp-promote` re-checks it.
   - If `<slug>` is already a seed, an active design or an archived design, step 6 refuses
     it. Offer the amend path to that slug, or a new slug, on one card.

4. **Score the four axes** from the idea: `risk`, `blast-radius`, `reversibility`,
   `novelty`, each `low`, `medium` or `high` (rubric: `skills/_shared/weight-class.md`). Show
   the proposed score for each with a one-line reason and ask **one** card: accept the set
   (Recommended) or adjust it.

5. **Ask the class question.** Run both helpers with the confirmed axes:
   ```bash
   python3 "$TP_ROOT"/skills/_shared/weight_class.py lighten "three-pillars-docs/tp-designs/<slug>" \
     --risk <r> --blast-radius <b> --reversibility <v> --novelty <n>
   python3 "$TP_ROOT"/skills/_shared/weight_class.py cost
   ```
   `lighten` prints `suggest <class> because <axis>` or `keep <class>`; a directory that does
   not exist yet reads as no declared class. `cost` prints one line per class with its rough
   token cost (the spike line reads `no figure (experiment)`). Ask one card with the four
   classes, the `lighten` class first as **(Recommended)**, and the `cost` figure beside each
   option. The class chosen here is the seed's default, not a floor: `/tp-promote` and
   `/tp-design` run `lighten` again on the written seed, with its paths, before a `design.md`
   commits the class.

   For a `just-do-it` class, ask one more card for a rough estimate of the lines the change
   adds; step 6 passes it as `--estimated-lines`. Any other class has no estimate.

6. **Write the seed** with the one writer, never by hand. Write each section to its own
   file (one file per field, same heredoc as step 3), then run `new` on the files:
   ```bash
   mkdir -p .tp-scratch/seed/<slug> && cat > .tp-scratch/seed/<slug>/problem.md <<'SEED_TEXT_END'
   <problem>
   SEED_TEXT_END
   cat > .tp-scratch/seed/<slug>/direction.md <<'SEED_TEXT_END'
   <direction>
   SEED_TEXT_END
   cat > .tp-scratch/seed/<slug>/open-questions.md <<'SEED_TEXT_END'
   <open questions>
   SEED_TEXT_END
   cat > .tp-scratch/seed/<slug>/consumer.md <<'SEED_TEXT_END'
   <consumer-repo behaviour>
   SEED_TEXT_END
   python3 "$TP_ROOT"/skills/_shared/seed_write.py new "<slug>" --class <class> \
     --risk <r> --blast-radius <b> --reversibility <v> --novelty <n> --source "/tp-seed" \
     --problem-file .tp-scratch/seed/<slug>/problem.md \
     --direction-file .tp-scratch/seed/<slug>/direction.md \
     --open-questions-file .tp-scratch/seed/<slug>/open-questions.md \
     --consumer-file .tp-scratch/seed/<slug>/consumer.md --estimated-lines <n> --repo .
   ```
   Drop `--estimated-lines <n>` unless the class is `just-do-it`.
   The writer stamps `slug`, `weight-class`, the four axes, `status: seed`, `seeded` and
   `source` (and `estimated-lines` when given), and writes `## Problem`, `## Direction`,
   `## Open questions` and `## Consumer-repo behaviour`. It prints the path, or exits 1 with
   one `seed_write:` line on a refusal (taken slug, bad slug, class or axis). Report that line
   and fix the input; never write the file by hand. Re-read the written file once, then
   `rm -rf .tp-scratch/seed/<slug>`.

7. **Commit** per `skills/_shared/commit-after-work.md`, the seed path only.
   - Branch: a seed never commits on the default branch. On `master`/`main`, create a seed
     branch (`git switch -c seed/<slug>`; one seed branch may batch several seeds). Where the
     repo keeps design work in worktrees (`skills/_shared/collaboration.md`), make that branch
     in a worktree rather than switching the base checkout. On any other branch, stay on it.
   - Run `git status --short`; unrelated changes outside the seed path stop the skill, as the
     protocol says.
   - `git add three-pillars-docs/tp-designs/<slug>/seed.md` (never `-A`, never `.`).
   - Message in the protocol's `{Verb}: {design-name} {detail}` shape (its table has no row
     for this skill): `Seed: <slug> new`, or `Seed: <match> part <N>` after an amend. No
     `Co-Authored-By` trailer, no `--no-verify`; a hook failure stops the skill with its output.
   - Push fail-open: `git push -u origin <branch>` when an `origin` remote exists; on failure
     print one line and keep the commit. With no remote the commit stays local. Never
     `--force`. A PR is optional and can batch several seeds.

8. **Report** the seed path, the class with its `cost` line, the branch and commit, and the
   next step: `/tp-promote <slug>` turns the seed into a design.

## Rules

- Writes and commits one seed (or one new Part) and nothing else: no design work.
- Merge before writing: read `known-items` and `similar` first; file a new slug only when no
  open seed covers the idea.
- One question per card; the recommended option first.
- The seed's class is a default, never a floor. Do not add `pin-class: true` unless the
  operator asks to fix the class.
