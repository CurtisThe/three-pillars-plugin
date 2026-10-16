# STE-80 writing guide for explain envelopes

The explainer drafter writes every explain envelope to this guide. The rules
follow Simplified Technical English (STE) at about 80 % strictness. The
deterministic lint `skills/_shared/explainer/ste_lint.py` checks the numbers
and the banned list below. A test pins this guide to the lint, so the two
cannot drift.

The reader is an operator who switches in cold. Write for one quick read.

## Core rules

1. Write short sentences.
2. Use the active voice. Name the actor first: "The gate drops the item", not
   "The item is dropped".
3. Put one idea in each sentence.
4. Use one word for one thing. Do not change the term for variety.
5. Use simple, common words. Prefer "use" to a longer synonym.
6. Write numbers as digits and give their units.
7. Put code, file paths, commands and ids in backticks.
8. State facts. Do not guess, and do not add an opinion that the evidence
   does not hold.

## Thresholds

The lint counts words per sentence. A sentence ends at `.`, `!`, `?`, `;` or
`:` before whitespace, and at a newline. A code span counts as one word. Text
in parentheses does not count. The lint strips `**` markup first.

| Rule | Limit | Lint constant |
|---|---|---|
| Description sentence | at most 25 words | `DESCRIPTION_MAX_WORDS` = 25 |
| List-item sentence | at most 20 words | `LIST_ITEM_MAX_WORDS` = 20 |
| Any sentence (hard fail) | more than 30 words fails | `HARD_MAX_WORDS` = 30 |
| Passive sentences | at most 20 % of all sentences | `MAX_PASSIVE_PCT` = 20 |
| Soft length misses | at most 10 % of all sentences | `MAX_SOFT_MISS_PCT` = 10 |

A soft miss is a sentence over its field limit but not over 30 words. A hard
fail is a sentence over 30 words. One hard fail fails the lint.

Field forms:

- `ste_summary` and `confidence_note` are description prose.
- A section item is a list item. It is description prose only when it carries
  `"form": "description"`.
- Section titles are headings. The lint does not check them.

Passive voice: the lint flags a be-verb, then an optional word, then a word
that ends in `-ed` or `-en`. This is a heuristic. Some active sentences match
it, so keep the passive ratio low, not only under the limit.

## Banned words

Do not use these idioms and filler words. The lint matches any case. A
one-word entry also matches its inflections (`leverage` matches
"leveraging"). Words inside a code span do not count.

- `leverage`
- `utilize`
- `utilise`
- `seamless`
- `robust`
- `simply`
- `obviously`
- `basically`
- `essentially`
- `under the hood`
- `out of the box`
- `low-hanging fruit`
- `game changer`
- `cutting-edge`
- `best-in-class`

Use a plain word in its place: "use", "works without setup", "easy first
step".

## Evidence refs

Every claim cites evidence. Each sentence-bearing field (`ste_summary`, each
section item, `confidence_note`) has a `refs` list.

- Cite only ref ids that the explain request supplies. Never invent an id.
- Give each item at least one ref.
- An unknown ref fails the gate.
- An item with no ref, or with an unknown ref, is unsupported. The final
  envelope drops it.
- If `ste_summary` is unsupported, the envelope becomes a facts-only envelope,
  labelled `facts_only`.

A ref proves where a claim comes from. It does not prove that the claim is
true. Restate the evidence. Do not extend it.

## Honesty rule

The envelope explains. It does not certify, and it does not gate the merge.

- Every claim cites evidence from the request.
- Never say "safe to merge", and never imply it. The operator decides the
  merge.
- State a risk or a residual when the evidence shows one. Do not hide it.
- Use `confidence_note` to say what the evidence does not cover.

## pr-brief sections

A pr-brief envelope has these sections, in this order:

1. `what-merging`: what the PR changes.
2. `whole-system`: where the change sits in the system.
3. `defaults-switches`: new defaults, config keys and switches.
4. `risks-residuals`: known risks and open residuals.
5. `review-outcome`: what review and audit found.
6. `rulings-without-you`: the rulings made without the operator.

Each section needs at least one supported item.

## One rewrite, then a style note

The gate checks every draft: schema, evidence refs, this lint, and the
diagram specs.

1. If the draft fails, the drafter gets one rewrite. There is no second
   rewrite.
2. If the rewrite still fails the lint, the envelope ships with a visible
   `style_note`. The lint never blocks delivery.
3. The final envelope drops unsupported items and omits an unusable diagram.

Get it right on the first draft. Fix the issues that the rewrite prompt names
and change nothing else.

## Diagrams

Write a diagram as a spec in `diagram_specs`. Never write raw SVG, mermaid or
HTML, and never put a code fence in a text field.
