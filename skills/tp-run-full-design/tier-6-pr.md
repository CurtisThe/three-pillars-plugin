<!-- Part of SKILL.md (tp-run-full-design): read in full when its tier is reached; see the Tier map there. -->

## Tier 6 — Completion PR open + fail-open

### Step 1 — Ensure pushed

Push `tp/{slug}`: `git push origin tp/{slug}`.

#### Tier 6 — legacy fallback

- Fold conflict only: open the legacy candidate→tp PR (`--base tp/{slug} --head candidate/{slug}/single`) for the human to resolve there; the design is **not** archived, it stays in-flight.
- Its PR body tells the human, after resolving the conflict, to run `python3 "$CL" issues apply --pending {design}/certifications/records/known-issues.pending.md --known-issues three-pillars-docs/known_issues.md` (`$CL` per `tier-5-closeout.md` ## Tier 5 Step 2b), since Tier 5.6 applies only on a clean fold.

### Step 2 — `gh pr create`

- `--pr-reviewers` defaults to `copilot-pull-request-reviewer[bot]`; `--no-review` suppresses requests. Tier 6 is the sole completion-PR review requester in the autonomous path (`/tp-design-complete` `## Auto Mode` defers the request here and logs `review-request-deferred-to-tier-6`); `tp-pr-iterate` re-requests per round.
- Partition the reviewer list before requesting: unless `--no-review`, split `--pr-reviewers` on `,` and match each name case-insensitively against `copilot-pull-request-reviewer[bot]` / `copilot` / `copilot[bot]` — matches go to bots, the rest to humans.
- Append `--reviewer "<comma-joined humans>"` to the `pr-create` line ONLY when humans is non-empty: `gh pr create --reviewer ""` errors.
- Request the Copilot bot through the REST `requested_reviewers` call ONLY when bots is non-empty.
- Resolve scripts git-toplevel-first per `first-run.md` §Resolve a FREE _shared script (`github_pr_author.py`). GitHub runs `github_pr_author.py` and the same `gh pr create` underneath:

```
TOP="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$TOP" ] && [ -f "$TOP"/skills/_shared/resolve_script.py ]; then RS="$TOP"/skills/_shared/resolve_script.py; else RS="$TP_ROOT"/skills/_shared/resolve_script.py; fi
FORGE="$(python3 "$RS" forge.py)" || exit 1
[ -n "$FORGE" ] || exit 1
HEADLINE=$(python3 "$TP_ROOT"/skills/_shared/explainer/explain_cli.py headline --slug {slug} || true
)
[ -z "$HEADLINE" ] || HEADLINE="$HEADLINE"$'\n\n'
python3 "$FORGE" pr-create --context autonomous -- --base {default} --head tp/{slug} --title "{slug}: {task_metadata.title}" --body "${HEADLINE}$(structured PR description)"
```

- Before `pr-create`: `phase_check.py jdi-warn --design-dir <d>` (advisory); `review_time.py --design-dir <d> --phase impl` in the PR body.

### Step 2b — PR-number writeback

- Completion path only: the legacy fallback never runs it. After create succeeds, resolve `{n}` from the PR URL and, per `skills/_shared/final-doc-state.md`, run the writeback, commit and push, before the Copilot request:

```
python3 "$TP_ROOT"/skills/_shared/reconcile_docs.py --slug {slug} --pre-merge --pr {n} --apply --json
git add <edits[].path>
git commit -m "docs({slug}): completion PR #{n} in living docs"
git push origin tp/{slug}
```

- A writeback or push failure logs `[tp-run-full-design/tier-6] doc-writeback-failed` (Medium) and continues; the head keeps `Done (completion PR)`.
- After the push, the certification gap label (one line, fail-open; `$CERT` resolved as in `tier-5-closeout.md` ## Tier 5 Step 2b, `<final route>` the route JSON Step 2c kept):

```
python3 "$CERT" gap-label --route <final route> --pr {n} || true
```

  A non-zero exit or a forge without label support logs `[tp-run-full-design/tier-6] cert-gap-label <line>` and continues — the PR-body note stands alone.
- With the explainer on, post the brief, then sync rulings (a no-op on an empty ledger); both fail-open:

```
python3 "$TP_ROOT"/skills/_shared/explainer/explain_cli.py post --slug {slug} --pr {n} --context autonomous || true
python3 "$TP_ROOT"/skills/_shared/explainer/explain_cli.py rulings-sync --slug {slug} --pr {n} --context autonomous || true
```

- Request the Copilot bot via REST, after the push (never `gh pr edit` for reviewers — classic-Projects repos error `deprecated` first):

```
gh api repos/{owner}/{repo}/pulls/{n}/requested_reviewers -f 'reviewers[]=copilot-pull-request-reviewer[bot]'
```

- Fail-open (load-bearing): a non-zero exit from either review add must not fail the run — the PR already exists; log one block to `decisions.md` and continue:

```
[tp-run-full-design/tier-6] review-request-failed
**Reviewers attempted**: <list>
**Cause**: <gh stderr>
**Confidence**: Medium
```

- PR description: link to the task source (`pickup_contract.task_metadata.external_ref`).
- Candidate `summary` from the parsed response.
- `test_results.{passed,failed,skipped}` counts + a fenced excerpt of `raw`.
- Tier 5 verdict (PASS or PASS WITH NOTES; the notes inline if present).
- Certification block: `python3 "$CERT" gap-block --route <final route> --lint <lint json>` (the route and lint JSONs `tier-5-closeout.md` #### Step 2c kept).
- Tier 5 design-learn synopsis (one-paragraph what-changed).
- **Closeout status**: design archived to `completed-tp-designs/{slug}/`, plus the Tier 5.6 learn-verify result (any stale-ref flags inline, advisory); routing `end` lines read back from it.
- Explicit label: "produced by orchestrator MVP — single candidate, closed before merge".
- `gh pr view {n} --json mergeStateStatus` checks conflict-freeness; `/tp-merge {slug}` handles semantic conflicts.

### Step 3 — Fail-open semantics

Mirrors `skills/tp-design-complete/SKILL.md` step 6g.

1. Medium-confidence `decisions.md` entry `[tp-run-full-design/tier-6] gh-pr-create-failed`; print the compare URL: `python3 "$FORGE" compare-url --base {default} --head tp/{slug}`.
2. **Exit 0** — the orchestrator's exit code MUST reflect "delivered, awaiting manual PR" not "failed". **Do NOT exit non-zero on a `gh` failure**; do NOT retry `gh pr create` (only Tier 3+3.5 retries via `--max-attempts`); do NOT fall through to `SKILL.md` ## Cleanup's abnormal-exit branch.
3. Helper exit **3** (`BotAuthUnavailable` — `github.pr_author_account` unavailable in the keyring): own token `bot-auth-unavailable`, distinct from `gh-pr-create-failed`.

The grep anchor `exit 0` here is testable; do not remove the literal phrasing.

### Step 4 — Vision deviation

Auto-merge is never in scope: a human must merge.

### Tier 6 outcomes

- Success → `[tp-run-full-design/tier-6] pr-opened {pr-url}`, writeback + `git push origin tp/{slug}`, then Tier 7 (unless `--no-iterate`/`--no-review`).
- `gh pr create` fails → exit 0, compare URL printed; Tier 7 skipped.
- Push fails → exit non-zero, abnormal cleanup.
