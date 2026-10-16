# Implementation audit: the fragility steps

Step 7c of `/tp-implementation-audit` runs these steps. The rule they enforce is
`skills/_shared/test-fragility.md`: an open-ended check, a change-detector or a blocklist
is a fragile test, and the audit finds them before the merge gate does. Run every command
from the design's worktree. `<base>` is the repo's resolved default branch (see
`skills/_shared/default_branch.py`) and `{design-name}` is the audited design.

## 1. Lint the diff

```bash
FORK="$(git merge-base "origin/<base>" HEAD)"
python3 "$TP_ROOT"/skills/_shared/fragility_lint.py check --base "$FORK" --json
```

`FORK` is the fork point, so the lint sees every line the design added and nothing the base
moved. Exit 0 = no gating hit. Exit 1 = at least one gating hit on an added line that no
inline waiver silences; each entry of `hits` with `gating: true` and an empty or null
`waiver` is a finding. Exit 2 = a file could not be judged: list it under `## Gaps` as
could-not-evaluate and continue. Never re-run with a weaker rule set to get a clean exit.

## 2. Record the changed-tests run

```bash
HEAD="$(git rev-parse HEAD)"
python3 "$TP_ROOT"/skills/_shared/changed_tests_runs.py record --base "$FORK" --head "$HEAD"
```

The `fragility_clear` merge predicate reads this record for the PR head. Exit 0 = pass,
1 = a changed test failed one of its repeated runs (a flaky test is a fragile test: report
it under `## Gaps` as a blocking finding), 2 = unverified or not written (report the reason
printed, no finding). The record is about `HEAD`; a push after the audit makes it stale, and
`/tp-merge` and `/tp-merge-from-main` record again for the head they land.

## 3. Write the fragile-class findings as items

From the lint hits and from your own read of the diff's tests, collect each fragile test
or check you are reporting. Write one JSON object per finding to a scratch file
(`FINDINGS_FILE="$(mktemp)"`):

```json
[{"path": "skills/<skill>/test_<name>.py", "line": 12, "rule_id": "golden-hash",
  "origin": "original", "fragility_class": "change-detector", "blocking": true,
  "summary": "asserts the sha256 of a file read, not computed in the test"}]
```

- `fragility_class` is one of `open-ended`, `change-detector`, `blocklist`: pick the kind
  from `skills/_shared/test-fragility.md` §1. Anything you cannot place is not written.
- `origin` is `original` or `regression` (the finding predates the diff, or the diff
  introduced it); both fields are the `skills/_shared/finding_fields.py` registries
  (`ORIGINS` / `FRAGILITY_CLASSES`) and a missing or unknown value is never guessed —
  `finding_fields.normalize` leaves it `unclassified`.
- `blocking: true` goes on each finding that drives `NEEDS WORK` (the ones you would not
  let through to the merge). A non-blocking note, or a finding with no fragile class,
  never becomes an item.
- `rule_id` is set on a lint-sourced finding so its item id stays stable across re-reports;
  the `summary` is display-only and is never hashed.

### Mutation testing (optional, diff-scoped, advisory)

If you run mutation testing, it is scoped to the diff, advisory only: it produces no score and
there is no mutation-hunting angle (`round-topology.md` class `T` reads "test fragility
(test-fragility.md)", not "test quality / mutation"). A surviving mutant is a finding only when
it breaks a stated spec sentence — report it the same way as any other fragile-class finding,
never as a raw mutation-kill count. Mutation-derived and exploratory tests written to probe a
survivor are never committed; they are scratch, discarded once the finding is written.

### Non-Python files (`judge_dimension_required`)

When step 1's `--json` lint sets `judge_dimension_required` (a code file outside the AST-lintable
set was skipped), the Part A questions from `skills/_shared/test-fragility.md` become a
**required** judge dimension for those files: read each skipped file against Part A yourself and
report what you find, rather than treating the skip as clean.

Then replace this source's list for the design branch, bound to the audited head:

```bash
python3 "$TP_ROOT"/skills/_shared/fragility_items.py replace \
  --branch "tp/{design-name}" --source impl-audit --head "$HEAD" --findings "$FINDINGS_FILE"
```

`replace` swaps the whole `impl-audit` list, so re-running the audit on a fixed tree clears
the items the fix resolved; an empty list (`[]`) clears them all. Open items block the
`fragility_clear` predicate in `/tp-merge` until they are fixed or waived by id with
`fragility_items.py waive`. A PR review round at a later head supersedes this list.

## 4. Fail-open on tooling

A missing helper, a non-git directory or any error from these commands is reported under
`## Gaps` in one line and the audit continues: a broken tool never writes a verdict. The
merge gate is the backstop that reads the same state.

## 5. Run the skill evals (dev-scoped)

In the three-pillars dev repo only, when `evals/` exists, run the skill evals the audit
owns. In the three-pillars dev repo only:
```bash
python3 "$TP_ROOT"/skills/_shared/skill_evals.py plan
```

Spawn each planned scenario on the Opus review model in a scratch copy of the repo and
collect the runs into a results file. In the three-pillars dev repo only:
```bash
python3 "$TP_ROOT"/skills/_shared/skill_evals.py grade --results "$RESULTS_FILE"
python3 "$TP_ROOT"/skills/_shared/skill_evals.py stamp --results "$RESULTS_FILE"
```

A grader that fails is a finding under `## Gaps`; `stamp` moves the stamp only on a
completed run. In the three-pillars dev repo only: nothing here runs per commit, in
`ci-local` or in `framework-check.sh` — it runs only from this audit step.
