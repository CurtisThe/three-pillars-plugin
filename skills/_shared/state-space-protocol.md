# State-space protocol

One template, two modes. Kickoff skills (`/tp-design`, `/tp-promote`) **build** a map of the option
space before asking the operator anything; audit skills (`/tp-design-audit`, `/tp-plan-audit`)
**check** it. Purpose: questions come from an explicit map of where the fix could live and what the
real alternatives are, not from the seed's own wording and blind spots.

**Who builds it:** the map is built in the top-level session, never a subagent (it is interactive),
and on Opus only — never a local model.

**Size cap:** ~40 lines for the whole section; ≤4 dimensions, 2-4 alternatives each; one line per
assumption. Confidence is a High/Med/Low judgment, never a number.

## Map template

Persisted as a `## State space` section in design.md for every class above just-do-it. It is not
floor-required (`validate_design_floor.py` ignores it), and it does not count toward design.md's
80-line guidance.

```markdown
## State space
### Loci
- <place the fix could live> — <why it could work here>
- <another place> — <why>
### Dimensions
- **<name>**: a <alt> · b <alt> · c <alt> → leading a (High|Med|Low)
### Assumptions
- <load-bearing assumption> — check: <how to verify it>
### Flip evidence
- <what would overturn a leading option, per dimension>
### Questions
- Q1 [<dimension>] <short question> — flips: <leading option it could overturn>
- Defaults (no flip): <dimension> = <option>; …
```

Each persisted question is a one-line digest ending in `flips:`; the problem paragraph belongs in the
prompt actually asked, not here (an indented continuation line is still read as the same question).

- **Loci** — every place the problem could be fixed (at least 2): the launching side vs the receiving
  side, the producer vs the consumer, the skill vs the shared helper, and so on.
- **Dimensions** — a morphological analysis: list the independent choices, give each 2-4
  alternatives, mark the leading one with its confidence.
- **Assumptions** — only the load-bearing ones, each with how it would be checked.
- **Flip evidence** — what the operator or codebase could reveal that would change a leading option.

## Build mode

Used by `/tp-design` (step 6, before the conversation) and `/tp-promote` (step 5, before the batched
confirm), for every weight class above just-do-it. When the class is still undecided (a seed without
`weight-class`), build against the `weight_class.py recommend` default and re-trim to the answered class
when persisting (drop the map entirely if the answer is just-do-it).

1. **Self-resolve first.** Settle whatever the repo, `vision.md` and the seed already settle; do not ask
   the operator for facts the codebase can answer.
2. **Enumerate loci, then dimensions** (the morphological analysis above).
3. **Flip test.** A dimension becomes an operator question only if some plausible answer would flip its
   leading option. Dimensions no answer can flip are settled by the drafter and listed on the
   `Defaults (no flip)` line.
4. **Uncovered loci.** Any locus the map cannot rule in or out becomes an explicit question.
5. **Question format and order.** Each question names its dimension, opens with a one-paragraph
   plain-language statement of the problem, then gives the options with the default marked. Goal and
   locus questions come first, constraint questions last. The `/tp-promote` HTML briefing uses the
   same format.
6. **Persist** the map as `## State space` in design.md, with each asked question's `flips:` target.

## Check mode

Used by `/tp-design-audit` and `/tp-plan-audit`. The audit brief carries (or points to) the design's
`## State space` section plus one extra angle for the reviewers:

> Was a better locus or alternative dismissed without evidence?

An alternative or locus dismissed without evidence is a finding in the consumer's own non-vision category
(MEDIUM in `/tp-design-audit`, INCONSISTENT in `/tp-plan-audit`), never MISALIGNMENT, which is reserved for
vision conflicts. It questions design.md's own framing, so it is recorded and escalated to the operator —
never auto-applied to plan.md or detailed-design.md (design.md is authoritative; a framing fix means
revising design.md). When design.md has no `## State space` section, the angle instead checks the Scope and
Constraints for an unconsidered locus; under `--auto` that fallback is skipped (no map, no map check).

## Weight-class gating

| Class | Map |
|---|---|
| `just-do-it` | skipped |
| `light` | compact map (below) |
| `spike` / `full` | full map (template above) |

**Compact light-class map:** the same sub-headings, reduced to `### Loci` (≥2), exactly one
`### Dimensions` bullet, and `### Flip evidence` (plus `### Questions` when any were asked). No
`### Assumptions`. Target ≤12 lines.

```markdown
## State space
### Loci
- Launching side — the caller knows it is spawning a subagent
- Receiving side — the design run detects it is inside a subagent
### Dimensions
- **Guard point**: a launcher refuses · b receiver refuses · c both → leading a (Med)
### Flip evidence
- A launch path that bypasses the launcher would flip a → c.
### Questions
- Q1 [Guard point] Where should the refusal live? — flips: a
```

## Lint

`python3 "$TP_ROOT"/skills/_shared/state_space_lint.py <design_dir>` is an advisory, warn-only check:
it warns when the map has fewer than 2 loci or a `### Questions` bullet lacks its `flips:` target. It
prints `WARN state-space: …` lines and exits 0 on every read and parse path (an unreadable or
non-UTF-8 file is itself a WARN), so it never blocks a commit or a skill step; only CLI misuse (wrong
argument count) exits non-zero.
A design.md with no `## State space` section is clean to the lint (the section is not floor-validated;
the kickoff skills still persist it for every class above just-do-it).
