---
name: tp-merge-from-main
description: "Sync a base branch INTO a design's worktree (base-sync) and auto-resolve the safe living-doc conflict classes behind a zero-drop verifier, deferring everything semantic to the human. Re-runs tests, re-pushes only when green, updates the PR. This is the reversible base-into-branch operation — landing the PR is the separate /tp-merge land gate."
argument-hint: "{design-name} [--base <branch>] [--dry-run] [--no-push] [--force-takeover]"
---

# tp-merge-from-main — worktree-aware base-sync + living-doc conflict resolution

When parallel designs run in their own worktrees, the base branch moves under them and a
merge conflict on the shared living docs (`known_issues.md`, `product_roadmap.md`,
`architecture.md`, `vision.md`) is the *expected* case at `/tp-design-complete` time. Manual
resolution is slow and — as the parent spike proved on real PR-#28 history — a silent
**content-drop** risk: a careful human merge dropped a known-issue entry outright.

`/tp-merge-from-main` merges the base into the design's worktree branch and auto-resolves only the
**provably-mechanical** living-doc conflict classes behind an independent zero-drop verifier.
Everything semantic is left as conflict markers for the human. It is the conflict-handling
step the merge-back flow never had; it composes with `/tp-pr-iterate` for the post-merge
re-review loop.

> **Base-sync, not land.** `/tp-merge-from-main` is the *reversible* base-into-branch
> operation (it merges `{base}` into the design branch and re-pushes the branch). It is
> **not** the irreversible `gh pr merge` that lands the PR to `{default}` — that is the
> separate `/tp-merge` land skill, which enforces the deterministic merge gate (including
> the human-approval predicate) before crossing the boundary. Keep them distinct: this
> skill syncs the base in; `/tp-merge` lands the PR out.

**The boundary** (from the `worktree-merge-conflict-flow` spike, verdict GO; log classes un-gated by `basesync-prepend-log`):
- **AUTO-SAFE** (auto-resolved + verified): `design-inventory-row-merge`, `log-entry-insertion`, `append-only-log`, `decision-entry-insertion`.
- **GATED** (classified, always deferred — `classify.GATED`): `id-renumber-collision`, withheld since round 20 because its renumber sees only the one conflicted file (not the IDs other living docs cite or have already spent) and it renumbers the base branch's already-landed entry.
- **ALWAYS-HUMAN** (deferred): `preamble`/`Last updated`, `current-focus-reprioritization`, `generic-prose`.

**The resolver rule (`skills/tp-merge-from-main/scripts/resolve_totality.py`).** *A mechanical resolver never discards a line it does not understand — it preserves every input line, or it defers.* Stated over LINES, not atoms: the verifier can only see a lost line if that line parses as an atom, so an atom-level rule would leave ordinary prose free to vanish under a RESOLVED verdict — a silent content loss on the one lane that certifies byte-safety without a human. Three consequences at the boundary above: a hunk mixing an AUTO-SAFE shape with foreign content is **not** that class (every AUTO-SAFE class carries a purity predicate: the two insertion classes each require every side to START at an entry of the class and open no foreign section — a heading in any form, indented ATX and setext included, is foreign — `append-only-log` holds two differing tails to the log-insertion predicate, those three need the first line after the region to start an entry or be EOF whenever they emit both sides' lines, and those three hold every line of each inserted block (of each differing `append-only-log` tail that is not whitespace only) to an allowlist (`scripts/line_shapes.py`): the class's entry start, or a line that — read past its leading whitespace and list markers — is not heading-shaped at any step of that reading (an ATX `#`–`######` or a bare `---` / `===` underline, at any indentation, since a heading nested in a list item sits four or more columns in; an underline shape directly below a blank line of the same side is admitted, since no paragraph is open there for it to underline, and one on a side's first line is refused), does not begin with `<` (HTML block), three or more `` ` `` or `~` (code fence), `>` (block quote) or `$$` (math block) and is not a link or footnote definition (`]:`), with a carriage return allowed only as a line's last character — it refuses by first token, not by parsing, so a balanced fence, a one-line `<!-- … -->` comment or a `> ` reply inside an inserted entry defers the file although it cannot swallow anything (27 of the repository's 1814 decision entries, 1.5%, carry such a line); its heading and block-opener tests read only a line's START (past indentation and list markers), so an unclosed inline raw HTML element later in a line (`… wrap long evidence in <details> blocks`, an unclosed `<s>`, `<b>` or `<a href>`) is admitted: an accepted residual that can visually wrap the other side's following entry on GitHub's renderer, left unrefused because mid-line `<placeholder>` text is common; and the inventory arm admits table lines only, and only as rows of ONE table: no blank or whitespace-only line, no line of pipes only and no carriage return inside a line on either side, no header or `| --- |` except one identical frame both sides open with, and no row appended directly above a delimiter row or above a line with a carriage return inside it — so a keep-both merge never moves a line from one side's entry to the other's, nor puts one side's entry inside an HTML block, code fence or heading section the other side opened, nor moves a row into another table or out of its table); a hunk whose sides contain a conflict marker is not well-formed input for any class and defers; and any mechanical result that does not account for its own input lines is discarded in favour of a deferral, whatever the resolver believed. The lane is therefore **narrower** than the class list alone implies — a mixed hunk costs a human resolve rather than silently losing a line.

**The index is the oracle for the text parse (`scripts/stage_oracle.py`).** All three rules above read the conflict TEXT, and the text is the one thing that can lie: git's marker grammar is ordinary markdown (`|||||||` is a table row of empty cells, `=======` a setext underline), so any rule that reconstructs a region's structure by shape-matching can be defeated by content that imitates it — and a region cut in the wrong place routes real content onto a side no resolver reads. The merge **index** carries the same structure with no such ambiguity: stage 1 is the base blob, stage 2 ours, stage 3 theirs, marker-free and authoritative. So before the driver accepts any mechanical result, it checks the parse against the stages — every line the parse put on the ours side must be a line of stage 2, and so on — and **defers the file untouched on any disagreement**. This is a validation gate only: it changes no bytes, and the RME-certified `resolve_conflict_bytes` path is untouched. It runs where the index exists (`merge_driver.resolve_living_doc`); callers without one (the `resolve.py` CLI, unit tests on synthetic blobs) cannot run it and keep only the three text-side rules.

**Markers are bound to `git merge-file`'s own labels (round 17).** The byte path (`skills/_shared/auto_safe_resolution.py`) runs `merge-file` with per-call nonce labels that no input contains, and the parse accepts only marker lines EQUAL to those labelled markers — so a document that quotes conflict syntax, or a content line that merely begins `>>>>>>>`, stays content instead of being read as a region. The parse must also find exactly as many regions as `merge-file`'s exit status reports, or the file defers. Unlabelled callers (the CLI, synthetic-blob tests) still use the prefix scan.

`log-entry-insertion` is the real base-sync shape for newest-first ADR logs (architecture.md's `## History`): `git merge-file --diff3` minimizes the conflict to an **empty base** between two divergent insertion blocks, so detection keys off empty-base (⇒ no deletions) **and** both sides being bold-lead log bullets (`- **YYYY-MM-DD** —` or `- **`slug`** —`) — keep-both, zero-drop, fail-closed on any deletion or foreign structure. (The classifier's `GATED` lever, empty after `basesync-prepend-log` un-gated the log classes, holds `id-renumber-collision` since round 20 — see the boundary above.)

**Approval-carry consequence.** When a base-sync is **fully AUTO-SAFE** (every conflict mechanical, certified byte-for-byte), the `approval-survives-safe-base-sync` carry keeps your existing PR approval + review proof **current** — no re-approval. A sync that **hand-resolves** any ALWAYS-HUMAN hunk cannot be certified byte-for-byte mechanical (the hand-edit is a real content change). **Exception — living-doc hand-resolution carry (default-ON within an already-carry-enabled repo):** the `livingdoc-handres-preserves-approval` relaxed certifier still carries the approval across a base-sync whose only files differing from a clean mechanical merge are **carry-set living-doc `.md`s** proven **code-unchanged** (carry-set predicate + cond4 containment + zero-drop, byte-*reproduction* relaxed) — so a hand-resolved living-doc hunk no longer forces a re-approval; only a hand-resolved **code** (non-carry) hunk, or a living-doc hand-res that **drops** a content atom, still **stales** the approval and you must re-approve. Serial fleet PRs sharing a living doc do **not** each re-approve by default — verify the merge-tree **empirically** (`--dry-run`) before assuming a re-approval tax: a later PR can sync cleanly when its merge-base already holds the earlier PR's entry (different insertion line → no collision). See `skills/_shared/human-approval-howto.md` §"Does a base-sync cost me a re-approval?".

## Arguments

- `{design-name}` (required) — must match an existing directory under `three-pillars-docs/tp-designs/` and an active `tp/{design-name}` worktree branch.
- `--base <branch>` (optional, default `master`) — the base branch to merge in (uses `origin/<branch>`).
- `--dry-run` (optional) — run the merge + resolution, print the report, then `git merge --abort`. Changes nothing, pushes nothing.
- `--no-push` (optional) — resolve and re-run tests, but stop before pushing (human pushes).
- `--force-takeover` (optional) — claim the design lock per `skills/_shared/collaboration.md`.

## Prerequisites

- `gh` CLI installed and authenticated (PR update + re-review).
- The project test command must run from the repo root.
- You are inside the design's worktree (the merge happens here, never in a sibling worktree).

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

0a. **Run cwd preflight** per `skills/_shared/cwd-preflight.md`: `python3 "$TP_ROOT"/skills/_shared/cwd_preflight.py {design-name}`. Exit 3 → stop and show the `cd` fix. Exit 0 → continue.

1. **Validate `{design-name}`** per `skills/_shared/validate-name.md` (must match `[a-z0-9-]+`; reject `/`, `..`, spaces). Then run the collaboration preflight per `skills/_shared/collaboration.md` with `phase: "implement"` (the merge-back rewrites tracked files like an implementation step; `phase` is constrained to the schema's fixed set, which has no `merge` value). `/tp-merge-from-main` rewrites tracked files and pushes, so the lock must be held by the rightful owner. Honor `--force-takeover` if passed.

2. **Fetch the base**: `git fetch origin <base>` (default `master`). The base ref being fetched here is synced from the **seat** — the base checkout / worktree host that hosts the design worktrees. If you are unsure which checkout is the seat, run `seat_resolve.sh --where` from the repo root; this skill already runs inside the design's own worktree, so the seat is the sibling base checkout. See `skills/_shared/topology.md` for the canonical seat and worktree layout definitions.

3. **Run the merge driver** from the repo root of the design worktree:
   ```bash
   python3 "$TP_ROOT"/skills/tp-merge-from-main/scripts/merge_driver.py "$(git rev-parse --show-toplevel)" "origin/<base>"
   ```
   The driver:
   - runs `git merge --no-commit --no-ff origin/<base>` inside the worktree;
   - for each conflicted **living-doc** file, reconstructs `(base, ours, theirs)` from the index stages, then runs `classify → resolve → verify` **per hunk**;
   - applies the staging policy and prints a JSON report with three per-file outcomes:
     - **auto-resolved** — every hunk mechanical, verifier zero-drop, no markers → written + `git add`ed.
     - **partially-resolved** — mechanical hunks pre-resolved in place, semantic hunks left as markers (file *not* staged). This is the common case: every real living-doc conflict also conflicts on the `*Last updated:*` preamble, which is semantic.
     - **deferred** — all-semantic, a verifier-flagged drop, a **still-conflicted blob the verifier could not clear**, an **unverifiable shape**, an add/delete conflict, or any non-living-doc (code) conflict → left untouched.

     > The verifier removes **no** line before digesting a `### [tag] title` body — conflict markers included — because every version of that strip eventually hid real content from a signature (see `verify_atoms.py`'s header). So a `decisions.md` whose remaining markers land *inside* an entry's body verifies as a drop even though every entry is present, and the file is **deferred rather than partially-resolved**: same "a human must finish this file", one less convenience. The report reads *"could not verify a still-conflicted blob (merge markers remain) AND {n} atom(s) appear missing from it — the markers may account for some or all, so check for lost content"*: **both** facts, because the driver cannot tell them apart — `_still_conflicted` is shape-only, so prose that merely *quotes* conflict syntax is indistinguishable from a real region. Read it as "the markers are the likely explanation, but confirm no content is missing." A blob with **no** markers at all reports the drop unhedged (*"verifier flagged content drop"*). Docs without `### [tag]` entries (`known_issues.md`, `product_roadmap.md`) are unaffected: their atoms are per-line.
   - exit `0` = fully resolved/clean; exit `2` = human attention needed; exit **`3` = `git merge` itself failed for a non-conflict reason** (unknown base ref, dirty worktree, a merge already in progress) — nothing was merged and nothing was attempted, so the report carries `merge_failed: true` and a `merge_error`. `3` is distinct from `2` because there is no conflict to finish: fix the repo state and re-run. (Before this, that case fell through an empty file loop and exited `0` — indistinguishable from a clean merge.)

   `verify.py` run standalone takes `<ours> <theirs> <resolved> [--mechanical-applied]` and exits `0` = ZERO-DROP, `1` = drops detected, **`2` = UNVERIFIABLE** — it parsed zero atoms from ours∪theirs on a file the resolver had actually mechanically resolved, so this file's shape is unknown to the verifier and "no drops" would mean "nothing examined" — and **`3` = usage or I/O error** (bad invocation, or an input path that could not be read/decoded). `3` exists because argparse's own usage exit is `2`, which would otherwise be indistinguishable from UNVERIFIABLE; a `3` means the verifier never ran, not that the merge is unsafe. Pass `--mechanical-applied` only when a mechanical resolution really was applied; without it a deferred or hand-resolved prose file is not blocked.

4. **Surface what the human must finish.** From the report's `partially_resolved` + `deferred` lists, tell the user exactly which files still carry conflict markers and which hunks remain (e.g. "`product_roadmap.md`: preamble + current-focus need you"). **Never stage or commit a file that still contains conflict markers** — the driver enforces this; do not work around it. Wait for the human to finish the deferred hunks before continuing (in `--dry-run`, stop here and `git merge --abort`).

5. **Re-run the project test suite** in the worktree once all conflicts are resolved (auto + human). If tests fail, stop and surface the failure — do not push.

6. **Commit the merge** once the tree is conflict-free and green: `git commit --no-edit` (preserves the merge message). With `--dry-run` or `--no-push`, stop before this.

6.5. **Closeout check (warn, never block)**: before pushing, run `python3 "$TP_ROOT"/skills/_shared/detect_unarchived.py --repo . --slugs-only` and check whether `{design-name}` appears — i.e., its `three-pillars-docs/tp-designs/{design-name}/` dir carries implementation evidence (`implementation-audit.md` / `spike-results.md`) but has **not** been archived to `completed-tp-designs/`. If it does, **warn** (do not block): the design has shipped but is not closed out — run `/tp-design-learn {design-name}` (or `/tp-spike-learn`) **then** `/tp-design-complete {design-name}` before the human merges, or the framework's CI check will hard-fail once the dir lands on `{default}` unarchived. `/tp-merge-from-main` is a conflict resolver, **not** a closeout gate — it surfaces the gap and proceeds; the CI check is the hard backstop, this is only the soft in-context nudge. **Fail-open**: a detector error is ignored (the helper always exits 0).

6.6. **Readiness advisory (warn-never-block)**: call `merge_gate.merge_readiness_warning(pr_url)` (from `skills/tp-merge-from-main/scripts/merge_gate.py`). If the return value is non-None, **print it as a WARNING** and **proceed** — never block. This mirrors the step-6.5 `detect_unarchived` warn-never-block contract: `/tp-merge-from-main` is a conflict resolver, not a readiness gate. The warning names the failing readiness sub-state from `classify_readiness` (`copilot-errored`, `review-stale`, `awaiting-copilot`, `unreviewed`) so the human can decide whether to remediate before merging. **Fail-open**: a detector error (fail to fetch, network issue) returns `None` and is silently ignored — a failing readiness check must never nag or block.

6.7. **Mandatory blocking pre-merge gate (fail-closed)**: before pushing the merge, run the deterministic gate. **Dispatch-from-seat invocation** (load-bearing for the base-sync approval carry — see below):
   ```bash
   SEAT="$(bash "$TP_ROOT"/skills/_shared/seat_resolve.sh --where)"
   if [ -n "$SEAT" ] && [ "$SEAT" != "NONE" ] && [ -f "$SEAT"/skills/_shared/resolve_root.sh ]; then
     TP_SEAT_ROOT="$(bash "$SEAT"/skills/_shared/resolve_root.sh --skill-dir "$SEAT"/skills/tp-merge-from-main)"
   else
     TP_SEAT_ROOT="$TP_ROOT"
   fi
   python3 "$TP_SEAT_ROOT"/skills/tp-merge-from-main/scripts/gate_cli.py --repo "$(git rev-parse --show-toplevel)" <pr_url>
   ```
   **Existence-guarded hop 2**: on a consumer repo the seat (the base checkout)
   does not contain the framework code (`"$SEAT"/skills/_shared/resolve_root.sh`
   does not exist there — only the dev repo is its own seat) — the guard falls
   back to the naive `$TP_SEAT_ROOT="$TP_ROOT"` automatically instead of hop 2
   failing loud and leaving the agent to improvise. This fallback is the
   documented-safe path (see the note below): the independent-oracle guard
   still fails CLOSED, just without the base-sync approval-carry capability.
   Or equivalently calls `merge_gate.merge_gate_blocking(pr_url, repo_root=<worktree toplevel>)` from `skills/tp-merge-from-main/scripts/merge_gate.py`, loaded FROM the seat's copy. **Exit 0 (PASS) is required before proceeding**; any non-zero exit (1 = FAIL, 2 = INDETERMINATE) means merge is refused. The gate output always shows the label `mechanical predicates hold — semantics UNVERIFIED — your review is the only semantic check`. The label is shown even on PASS — the gate never asserts the branch is ready-to-merge without caveats.

   **Why the two-hop `$TP_SEAT_ROOT` resolution, not `$TP_ROOT` directly**: this skill already runs with cwd inside the design worktree, and the step-0 bootstrap's `$TP_ROOT` resolves relative to whatever checkout loaded the code — naively, that is the worktree under verification, not the seat. The approval-survives-safe-base-sync carry's independent-oracle guard (`base_sync_cert.oracle_independent`) is DISJOINT-CODE-gated: it checks where the *executing* gate code physically lives, and a worktree-resolved `$TP_ROOT`/`$TP_SEAT_ROOT` is **detected and refused** by that guard (an "unknown-worktree" / provenance-indeterminate refusal), not silently trusted. `seat_resolve.sh --where` (repo-global via `git worktree list --porcelain`, prints the seat path or `NONE`) plus `resolve_root.sh --skill-dir "$SEAT"/skills/tp-merge-from-main` (probe-2 grandparent, anchored at the SEAT's own skill directory — **not** the worktree's, and **not** probe-4's cwd-derived dev-checkout fallback) is the concrete, non-circular recipe that resolves the seat's code root from the worktree cwd. Skipping this note and running the naive `$TP_ROOT` invocation does not produce an unsound certificate — the guard fails CLOSED — but it silently loses the carry capability: an otherwise-valid base-sync-carried approval reports INDETERMINATE instead of PASS. `--repo "$(git rev-parse --show-toplevel)"` supplies the SUBJECT repo (the worktree) explicitly, independent of which checkout's code is executing.

   Predicates checked:
   - **threads_resolved**: all review threads resolved (fail-closed: fetch failure → INDETERMINATE, not PASS)
   - **mergeable**: PR is in MERGEABLE state (CONFLICTING → FAIL; UNKNOWN → INDETERMINATE)
   - **checks_success**: all CI checks settled and concluded SUCCESS (empty rollup → INDETERMINATE, not PASS; INFRA_BLOCK → INDETERMINATE)
   - **copilot_on_head**: Copilot has reviewed the current head SHA (not reviewed → INDETERMINATE, not PASS)
   - **human_approved**: a current APPROVED human review from a non-automation human is present on the head SHA — enforced transparently via `evaluate_gate`'s `pred_human_approved` (no code edit here: `evaluate_gate` carries the fifth predicate when `review.require_human_approval` is true, the strict default). Absent/stale/automation-authored review → INDETERMINATE (never FAIL). See `skills/_shared/human-approval-howto.md` for how to authorize. The irreversible `gh pr merge` land step lives in the separate `/tp-merge` skill, which enforces the same gate at the boundary.

   This step is **DISTINCT** from the advisory step 6.6 (`merge_readiness_warning`, warn-never-block). That step proceeds regardless. This step 6.7 **refuses** on non-zero exit.

   **Honest GitHub-UI bypass note**: A merge performed via the GitHub UI (clicking "Merge pull request") outside the tooling **bypasses** this gate. The branch-protection backstop (requiring a CI status check from `gate_cli.py` in a required workflow) is deferred to the `self-hosted-ci-runner` design (council verdict #6: branch-protection setup is deferred). Until that ships, the tooling-path gate is the only enforcement; operators should use `/tp-merge-from-main` to sync and the `/tp-merge` land skill to land the PR (not the GitHub UI) for merge operations on guarded branches.


7. **Push only when green**, then **update the PR**: push the branch, refresh the PR body with a short merge note (base SHA merged, which files auto-resolved, which the human finished), and **re-request review** so branch protection re-triggers — compose with `/tp-pr-iterate` / `pr-fix-targeting-and-auto-review` for the Copilot loop. Pushing happens only here, at the irreversible boundary, and only on a green suite.

   **Producer breadcrumb (audit-only, ZERO gate authority)**: when the merge driver's report shows the sync was **fully auto-resolved** (no `partially_resolved` / `deferred` entries — every conflicted living-doc file resolved mechanically), post the `basesync-cert.v1` comment via `cert_comment.format_cert_comment(pre_sha, post_sha, resolved_classes)` + `cert_comment.post_cert_comment(pr_url, body)` (`skills/tp-merge-from-main/scripts/cert_comment.py`) — the pre/post merge SHAs and the resolved conflict classes (e.g. `design-inventory-row-merge`). **Failure to post is logged and ignored** — `post_cert_comment` is best-effort and never raises. **The deterministic gate NEVER reads this comment**: the `approval-survives-safe-base-sync` carry re-derives certified links from git objects alone (the first-parent walk + per-link RME re-proof), never from a PR comment — see `three-pillars-docs/completed-tp-designs/approval-survives-safe-base-sync/detailed-design.md` (Producer breadcrumb section). **Deferred living-doc hand-resolutions (`livingdoc-handres-preserves-approval`)**: when the sync instead **deferred ≥1 living-doc file** to the human (the deferred set the driver already tracks, filtered through `living_doc_carry.is_living_doc_carry_path`), post `cert_comment.format_handres_cert_comment(pre_sha, post_sha, handres_files)` + `cert_comment.post_cert_comment(pr_url, body)` — same audit-only, **ZERO gate authority** boundary: the deterministic gate re-derives the carried K from git objects (the first-parent walk + relaxed per-link re-proof, `is_living_doc_carry_path` + cond4 + zero-drop) and **never reads this comment**, so a forged/absent/wrong-author copy changes no verdict.

   The native-review approval path (`review-as-human-approval`) is **self-cleaning for real content changes**: a review carries an immutable server-set `commit_id`, so a genuine content change makes `commit_id != head` and the gate fails closed automatically at evaluation time. The `approval-survives-safe-base-sync` carry is the one narrow, opt-in exception: it extends an approval's currency **only** across a chain of *certified mechanical base-sync merges* — each link independently re-proven from git objects (merge shape, allowlist, byte-equality outside the conflict set, resolver byte-reproduction), never trusted from a comment or config claim. A real (non-mechanical) content change is never certified, so the gate still fails closed exactly as before — the carry narrows **when** self-cleaning fires, it never weakens it. No strip hook is needed — the gate's currency re-check in step 6.7 / the `/tp-merge` land gate is the fail-closed backstop.

   **Operational precondition (full clone)**: the carry's chain walk requires a full (non-shallow) clone to re-derive certified links. On a shallow clone the guard reports a **distinct INDETERMINATE detail** ("shallow/incomplete history — cannot walk chain; carry requires a full clone") rather than a verdict indistinguishable from "no certified chain" — a documented implementation precondition, not a soundness gap (the guard fails closed either way).

8. **Post-merge auto-chain** (fires only when the design's completion PR has actually landed on `{base}`): after the step-7 push, check whether the archive is now present on `{base}` — guard: run `python3 "$TP_ROOT"/skills/tp-post-merge/scripts/verify_merged.py --repo . --design {design-name} --base {base} --json`; `merged == true` confirms the completion PR was merged to base. **`/tp-merge-from-main` itself does not land the completion PR** — it merges `{base}` *into* the design branch and updates the PR; the human (via the `/tp-merge` land skill, or a later `gh pr merge`) lands it. So in the ordinary base-sync invocation this guard is **false** and the step silently skips (see the last bullet). Only when `verify_merged.py` reports `merged == true` does this chain `/tp-post-merge {design-name}`.

   - **Fail-open**: a teardown error from `/tp-post-merge` **never** undoes the merge. If `/tp-post-merge` fails, log the error and report it to the user — do not roll back anything. The merge already landed; cleanup can be retried manually with `/tp-post-merge {design-name}`.
   - **Skip under `--dry-run` or `--no-push`**: if either flag was passed, skip the auto-chain entirely (the merge did not actually happen or was not pushed).
   - **Additive and silent on non-completion merges**: if `verify_merged.py` reports `merged == false` (offline, unfetched refs, or this was just a base-sync merge, not a completion-PR merge), skip this step silently with no error.

## Rules

- **Validate `{design-name}`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — `/tp-merge-from-main` rewrites tracked files and pushes.
- **Zero content drops is the hard gate.** The verifier is the backstop for *mechanical* drops; it is **necessary but not sufficient** (a semantic mis-merge can survive it), so semantic safety is carried by **deferral**, never by the verifier. Auto-resolution fires only when **mechanical-class ∧ classifier-confident ∧ verifier-passes**.
- **Merge, not rebase.** Rebase force-pushes the branch and strands parallel worktree agents that forked from the old HEAD. `/tp-merge-from-main` always merges.
- **Never disturb sibling worktrees.** The merge runs inside the design's own worktree.
- **Never auto-resolve code or prose.** Only the structured living-doc classes are touched; everything else is surfaced untouched.
- **Optimize for zero-drop over reproducing past hand-merges** — the ground-truth human merge can itself be lossy (the spike's L4 case); a keep-both union that *diverges* from a lossy human result by preserving content is the correct answer.
- Use `mktemp` for any scratch files; the driver uses Python `tempfile` internally.
