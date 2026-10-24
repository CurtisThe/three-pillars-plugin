<!-- Part of SKILL.md (tp-run-full-design): read in full when its tier is reached; see the Tier map there. -->

## Tier 5 — Consolidation audits

Tier 5 takes the validated single candidate; its slots dispatch, never inline.

### Step 0 — Scratch check (every class)

Before Step 1, and so before the light and just-do-it closeout dispatch too (every class, light included), run `python3 "$TP_ROOT"/skills/_shared/scratch_leftovers.py provision --slug {slug}` then `python3 "$TP_ROOT"/skills/_shared/scratch_leftovers.py check --expect --slug {slug}` from the worktree. When `provision` prints `created` (a design in flight from before this one gets its baseline here), log `[tp-run-full-design/tier-5] scratch-provisioned-late`; a missing baseline never stops it on `no run scratch`. On exit 1 the run stops with every `scratch-leftover:` line reported: finalizer first (`SKILL.md` § Cleanup step 0), never continue. Only the finalizer or the operator runs `python3 "$TP_ROOT"/skills/_shared/scratch_leftovers.py accept --path P --reason R --slug {slug}`, after inspecting the path, with a decisions.md entry.

### Step 1 — Regression check

- The orchestrator opens a detached worktree (no `regress/{slug}` branch, never sharing `tp/{slug}`; `run-safety.md` ## Branch hygiene), prints `<P>`:

```
git fetch -q origin candidate/{slug}/single
python3 "$TP_ROOT"/skills/_shared/wt_root.py open --role regress --slug {slug} --base-ref origin/candidate/{slug}/single
```

- Dispatch the subagent with `WORKTREE: <P>`; every command `cd <P> && …`. It runs there:

```
python3 "$TP_ROOT"/skills/_shared/iteration_lane.py --lane iteration --granularity phase --exec
```

- Then the orchestrator reaps: `python3 "$TP_ROOT"/skills/_shared/wt_root.py reap --role regress --slug {slug}`.

- Exit 78: stop, report, run `/tp-test-setup`; empty is never green.
- **No** stamp: `ci.gate_command` via `ci_gate_run.py` feeds the human's `/tp-merge` `ci_local_stamp`; never an orchestrator step.
- Unreported failure: log `[tp-run-full-design/tier-5] test-regression` with the failing test names; escalate, no retry.

### Step 2 — `impl-audit` slot

- After a green Step 1 (never the same subagent), read-only fan-out (`audits.md` ## Audit fan-out (Slots 4/6/8)) over design, plan, code via `--code-input` (`design-audit`/`plan-audit` flow); verdict-only, never edits code.
- All High → PASS or PASS WITH NOTES, then Step 3.
- Medium/Low → NEEDS WORK: retry-with-advice (`run-safety.md` ## Retry-with-advice (audits)): re-spawn `phase-implement`, re-dispatch `impl-audit` on the patch delta; one patch plus one re-check (`run-safety.md` ## Retry-with-advice counter). Log `[tp-run-full-design/tier-5] impl-audit-needs-work`; escalate only then (`run-safety.md` ## Retry-with-advice escalation).

**Step 2b — guard certification**: `python3 "$TP_ROOT"/skills/_shared/cert_once.py should-run --design-dir {design}` exit 0 → run, then `mark --design-dir {design} --attempt N`; exit 1 → reuse attempt 1's certifications. See `skills/_shared/certification-protocol.md` §Step 2b.

A light design instead runs `python3 "$TP_ROOT"/skills/_shared/cert_once.py should-run --design-dir {design} --light --base tp/{slug} --head S`. Exit 1 printing `should-run: skip (not a safety gate)` → log `[tp-run-full-design/tier-5] certification-skipped (not a safety gate)` and continue to Step 3 with the Step 2 envelope. Exit 2 means run (err toward certifying): log `[tp-run-full-design/tier-5] cert gate exit 2 → certifying` and certify. A safety gate (`safety-gate: true` or a `safety_gate.GATE_PATHS` path) exits 0 once, then reuses as above.

```bash
TOP="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$TOP" ] && [ -f "$TOP"/skills/_shared/resolve_script.py ]; then RS="$TOP"/skills/_shared/resolve_script.py; else RS="$TP_ROOT"/skills/_shared/resolve_script.py; fi
CERT="$(python3 "$RS" certify.py)" || exit 1
CL="$(python3 "$RS" certify_ledger.py)" || exit 1
```

- `python3 "$CERT" claimant-check --base tp/{slug} --ref S --design {design}` (`{design}` = the repo-relative design dir; exit 1 → `certification-unverified`, `claimant-records`).
- Lint before any dispatch: `git -c core.quotePath=false diff --no-renames --name-only tp/{slug}...S > <scratch>/diff.txt`, then `python3 "$CERT" lint --claims <claims.json> --ref S --kept-out <scratch>/kept.json > <scratch>/lint.json` (a light design adds `--light --diff <scratch>/diff.txt`). Exit 1 → one correction turn: re-dispatch the Slot 8 auditor with the lint lines, asking only for corrected `guard_claims[]`; lint again; certify `kept.json`. Exit 2 → the certify.py-failure `certification-unverified`. Log `[tp-run-full-design/tier-5] cert-lint <n> dropped`.
- Dispatch `Agent(subagent_type=agent_ref("tp-certifier"), model="opus")` once per claims file, **once per design** (the `cert_once.py` gate above; Slot 4 passes `--slot 4`), verdict files first, claims bytes fenced as untrusted data, with the resolved absolute `$CERT` path, its prompt from `python3 "$CERT" brief --claims <kept> --ref S --base tp/{slug} --cert-path <$CERT>`. Open its checkout first and pass `WORKTREE:` per certification-protocol.md §Certifier contract (`wt_root.py open --role cert` … `reap`).
- `records_file`: `python3 "$CERT" handoff --certifier-return <envelope> --records <copy>` (sha256 + count; exit ≠ 0 → rerun with `--unverified records-handoff`); copy under `certifications/records/`.
- `python3 "$CERT" run … --watch-ref …` per file (`--name` = the file's path under `certifications/`, `--out <scratch>/r<N>.result.json`), then one `python3 "$CERT" fold --slot 8` with a `--result` for every result (sweep ones included), `--kept <scratch>/kept.json` and `--verdict-guards <scratch>/diff.txt`: output replaces the Step 2 envelope (a kept `guard_claims[]` id no `records/` result certified folds `unverified`).
- Its step 6 (ledger files) runs through `$CL` only when a `sweep-NN.claims.json` or `self.claims.json` exists and only renders the pending issues file; `issues apply` runs after the Tier 5.6 fold (its Step 1). One commit, at protocol step 7 (after the HEAD assert).
- `skills/_shared/phase-check.md` §Impl audit: `phase-check-carry.json` items render as known, `security` joins the fan-out on trust-boundary surfaces; verdict → `audit-dispositions.json` via `audit_dispositions.write`.

#### Step 2c — route

`python3 "$CERT" route --folded <F> --design-dir {design} --out <scratch>/route.json` on the folded envelope `<F>` names one action; act on it, re-fold, and route again until it says `escalate`, `cert-gap` or `proceed`:

- `escalate` → `certification-unverified` (`run-safety.md` ## Retry-with-advice escalation).
- `retry` → per item `python3 "$TP_ROOT"/skills/_shared/cert_once.py followup --design-dir {design} --claim <key>`, then `mutant-extract` (an item whose `file` is `guard_claims` — reason `no-result` — is extracted from `<scratch>/kept.json` and merged into the `records/` result that should have carried it); `rerun` → `mutant-oracle` at `S`; `reauthor` → one scoped certifier dispatch of that single-claim file (the same dispatch literal, `brief`, `handoff`, `run`). Then `mutant-merge` into its file's result and re-fold (`--kept` again). Log `[tp-run-full-design/tier-5] cert-retry <key> <mode>`.
- `cert-fix` (a `not-binding` or `false-red` key) → `followup` per key; `python3 "$CERT" mutant-plan --claims <kept> --records <records> --id <id> --slug {slug} --out .tp-scratch/cert-fix-plan.md --start local-xhigh` (without `--local`: `--start sonnet-medium`) writes that plan; one `tp-worker` dispatch as in Slot 7 (`git fetch -q origin candidate/{slug}/single`, then `python3 "$TP_ROOT"/skills/_shared/worker_root.py reap --slug {slug} --root .` and `python3 "$TP_ROOT"/skills/_shared/worker_root.py open --slug {slug} --phase 1 --base-ref origin/candidate/{slug}/single --root .`, with the Tier 3 tip snapshot and `assert-unmoved`, on `candidate/{slug}/single`) runs `skills/_shared/local-dispatch.md` §1–§2 over that plan's phase 1 (its absolute path in place of `<d>/plan.md`) and pushes once; then Tier 3.5 with `rerun.plan_path` = that plan; then `mutant-oracle` per claim at the new candidate SHA. Not `binds` → one more dispatch with `--start sonnet-xhigh`, then the oracle again. Merge what came back and re-fold with `S` = the new candidate SHA, rewriting the diff first (`git -c core.quotePath=false diff --no-renames --name-only tp/{slug}...S > <scratch>/diff.txt`); no new full certifier pass and no retry-with-advice. Log `[tp-run-full-design/tier-5] cert-fix <key> <binds|unbound>`.
- `cert-gap` / `proceed` → continue as `continue_verdict` (with `retry_with_advice` true, the other findings take retry-with-advice as today). Keep the final route JSON `<scratch>/route.json` and the lint JSON `<scratch>/lint.json` for Tier 6. Log `[tp-run-full-design/tier-5] cert-gap <n>`.

### Step 3 — `design-learn` slot

Light / just-do-it: skip here; it runs once in Tier 5.6 §Light and just-do-it closeout.

- Slot 9 runs `/tp-design-learn {slug} --auto --cheap-tier` inline ([`cheap-tier.md`](cheap-tier.md) §Tier 5); it never edits `three-pillars-docs/vision.md`.
- Its retro step 10b spawns at most one reviewer, `Agent(subagent_type=agent_ref("tp-readonly-auditor"), model="opus")`, only when drafts exist. It reads and spawns nothing, so depth 2 at most, sanctioned beside `tp-drafter`'s (`cheap-tier.md` §Tier 5, Depth 2).
- Medium/Low confidence → PR description, never blocks.

### Tier 5 outcomes

- Step 2c route `escalate` → escalate, exit non-zero; `cert-gap` → continue (Tier 6 note and label).
- Step 3 errors → log Medium-confidence, proceed.

## Tier 5.6 — Closeout (fold → learn-verify → archive)

**This is the closeout-before-merge terminal.** The merge-only gate is preserved — nothing here merges to `{default}`. Tier 5.6 first runs the routing `end` pipe, a no-op once closed (`skills/_shared/local-routing.md` §End).

### Step 1 — Fold the candidate into `tp/{slug}`

Pinned on `tp/{slug}` (`run-safety.md` ## Branch hygiene): merge-in, never a checkout — `git merge --no-ff origin/candidate/{slug}/single -m "Fold candidate into tp/{slug}"`.

- Code-only candidate, artifacts-only `tp/{slug}` ⇒ near-disjoint trees ⇒ usually clean.
- **Fold conflict** → run `python3 "$TP_ROOT"/skills/tp-run-full-design/scripts/fold_union.py --slug {slug} --repo .`. Exit 0 → `git commit --no-edit` (the script has already recorded the ruling in `decisions.md` as `fold-decisions-union`; log nothing more, so the tree stays clean after the merge commit), continue. Exit 1 → `git merge --abort`, legacy candidate→tp PR (`tier-6-pr.md` ## Tier 6 — legacy fallback), `[tp-run-full-design/tier-5.6] fold-conflict`, High. Never auto-resolve anything but the design's own append-only `decisions.md`; the human resolves every other conflict.
- Once the fold commits (a clean fold, or a `fold_union.py` exit-0 union), and only if Step 2b rendered `{design}/certifications/records/known-issues.pending.md`: `python3 "$CL" issues apply --pending {design}/certifications/records/known-issues.pending.md --fragment three-pillars-docs/changes/{slug}.md` on the folded tree (it files into the design's fragment and leaves the living docs alone), then `git add three-pillars-docs/changes/{slug}.md` and commit; after a fold that falls back to the legacy PR (exit 1) it stays pending.

### Step 2 — Learn-verification

`python3 "$TP_ROOT"/skills/_shared/verify_learn.py --range {default}...tp/{slug} --json` names `three-pillars-docs/**` lines (living, `completed-tp-designs/`) citing a retired symbol. **Advisory only** — exits 0, fails open; refs go to the PR description and a `learn-verify` decisions.md entry, never block.

### Step 2b — Draft the PR brief

Draft `three-pillars-docs/tp-designs/{slug}/brief.md` per `skills/_shared/explainer.md`, off unless `python3 "$TP_ROOT"/skills/_shared/explainer/explain_cli.py enabled` exits 0; the archive subagent cannot spawn, its commit carries the file. Fail-open.

### Step 3 — Archive (`/tp-design-complete {slug} --auto`)

Dispatch it (## Auto Mode): archives, stamps, commits `Complete design: {slug}` under `verify_archive_staged.py`; no PR; learn-ran auto-satisfied (Tier 5 `design-learn`).

### Light and just-do-it closeout — one dispatch

For `weight-class` light or just-do-it the order is: Step 1 fold, Step 2b brief (when enabled), then ONE `Agent(subagent_type=agent_ref("tp-generator"))` dispatch at the model and effort of the Slot 9 row in `throughput.md` §Slot agents. It runs `/tp-design-learn {slug} --auto --cheap-tier`, then `/tp-design-complete {slug} --auto`, and returns one **generator-return** envelope with both skills' artifact paths. Then the advisory Step 2 `verify_learn.py`, then Tier 6, where the PR-number writeback stays the existing script step (`tier-6-pr.md`).

Step 3 rules (never edits `vision.md`, retro reviewer depth) and the BLOCK outcome apply unchanged. Stop rule: if `/tp-design-learn` BLOCKs (a BLOCKED `decisions.md` entry or a non-zero exit), the dispatch stops before `/tp-design-complete` and returns status `errored` naming the BLOCKED entry; any other design-learn error proceeds, per the Tier 5 outcomes. Full weight keeps Slot 9 + Steps 1-3 as written.

### Tier 5.6 outcomes
- Clean fold + archive → Tier 6.
- **Fold conflict** → `fold_union.py` first; only a non-zero exit takes `git merge --abort`, the legacy candidate→tp PR (`tier-6-pr.md` ## Tier 6 — legacy fallback), flag, exit 0.
- `/tp-design-complete --auto` BLOCKs → decisions.md BLOCKED, exit non-zero.
