---
name: tp-pr-fix
description: "One-shot PR-fix worker — classify review comments, gate by reviewer identity, generate ONE structural-fix commit per round, push, and label. Composes into the `tp-pr-iterate` loop or runs standalone."
argument-hint: "{design} [--pr-url <url>] [--iteration N]"
---

# tp-pr-fix — Single-Round Worker

A round-shaped worker over a single `<design>` PR. It receives reviewer comments,
classifies them (structural / minor / unclear), filters to **collaborator-authored
structural** issues, generates ONE fix commit, pushes, and applies the
`tp:do-not-merge-yet` label. The result is a `fix-envelope.v1.json` dict the
caller can persist or feed into the loop driver.

Two callers:

1. **`tp-pr-iterate` loop driver** — polls the PR, hands a fresh `classified[]`
   to `tp-pr-fix` each iteration until termination.
2. **Standalone, human-invoked** — `/tp-pr-fix my-design --pr-url <url> --iteration N`.
   You ran a review, want to apply one targeted fix round, and stop. The worker
   makes no assumption about being inside a loop — it produces exactly one commit
   per invocation (or none, with `verdict="no-applicable-fixes"`) and exits.

## Arguments

- `{design}` — kebab-case design name, validated per `skills/_shared/validate-name.md`.
  Resolves the active branch (`tp/{design}`) and the design directory under
  `three-pillars-docs/tp-designs/`.
- `--pr-url <url>` — full `https://github.com/<owner>/<repo>/pull/<n>` URL. Required.
  The shipped run-state `state.v1.json` schema does not carry a `pr_url` field;
  the loop driver passes the URL into `fix_round.run_round` from its own
  arguments, and standalone callers must supply it on the CLI.
- `--iteration N` — the iteration index recorded in the envelope and the commit
  prefix. Defaults to `1` when invoked standalone; the loop driver passes its
  current counter.

## Prerequisites

- `gh` CLI installed and authenticated. The worker uses it for:
  - `gh pr view <url> --json labels` — label idempotency check.
  - `gh pr view <url> --json headRefName` — resolve the PR head ref the commit
    must land on (F1; see ## Run sequence step 6).
  - `gh api repos/{owner}/{repo}/issues/{n}/labels` and `gh label create <label>` —
    label application via REST (delegated to `label_manager.ensure_pr_label`; the
    REST endpoint is used instead of `gh pr edit --add-label`, which fails on a
    classic-Projects repo with a GraphQL `projectCards` deprecation error).
  - `gh api repos/{owner}/{repo}/collaborators/{user}` — identity gate (with a
    trusted-reviewer-bot short-circuit; see step 6).
  - `gh pr diff <url>` — diff context for the classifier.
- A clean enough working tree on the **PR head ref** to commit and push. The head
  is resolved from the PR, not assumed to be `tp/{design}` — an orchestrator PR's
  head is the worker's candidate branch (`candidate/{slug}/single`), not the
  design branch (F1).
- The repo's `.three-pillars/config.json` is populated. The only config
  surface the worker honors today is **`pdw.comment_url_allowlist`** — extra
  netlocs (beyond `github.com` and the repo origin host) that reviewer comments
  may reference. The `tp:do-not-merge-yet` label name and the
  `claude-sonnet-4-6` model are hardcoded; there is no `pr_fix` config block.

## Run sequence

The dispatch is linear — no subcommands, one body.

0. **Run first-run preflight** per `skills/_shared/first-run.md`.

### 1. Load inputs

- Read `three-pillars-docs/tp-designs/{design}/design.md` (and `detailed-design.md`
  if present) for context to embed in the classifier prompt.
- Resolve `--pr-url` from the CLI argument; refuse with a clear error if absent.
  (The merged `state.v1.json` schema does not carry a `pr_url` field today.)
- Fetch the latest PR diff: `gh pr diff <pr_url>` → keep raw for the prompt and
  as `diff_hunk` material.
- Fetch unresolved review comments via `gh pr view <pr_url> --json reviewComments`
  (or `gh api /repos/.../pulls/.../comments`).

### 2. First-pass classification (deterministic)

Call `_shared/classifier_heuristic.py:classify(comment, diff_hunk)` for every
comment. The heuristic returns `{"verdict": "structural"|"minor"|"unclear", "reason": ...}`
from keyword + file-scope rules and never touches the network. Split into:

- **decided** — `verdict ∈ {"structural", "minor"}` from the heuristic.
- **borderline** — `verdict == "unclear"` (the heuristic abstained).

### 3. Borderline classification via Sonnet (Agent invocation)

For the borderline subset only, call the Sonnet judge — **this is the only
LLM call in the round, and it lives in this prose, not in any helper**, per
audit C1 (no `import anthropic` in helpers, no `subprocess.run(["claude", ...])`
in helpers; the model invocation is one orchestration step the SKILL owns).

```
build_prompt  = scripts.classifier_judge.build_prompt(borderline, diff_context)
response_text = Agent(
    subagent_type="general-purpose",
    prompt=build_prompt,
    description="classify-borderline-pr-comments",
)
classified_borderline = scripts.classifier_judge.parse_response(response_text)
```

`classifier_judge` lives under `tp-pr-iterate/scripts/` (built in Phase 5)
and exposes ONLY prompt construction + schema-validated response parsing.
The Sonnet model `claude-sonnet-4-6` is hardcoded in this prose; the
`pdw.runner_backend.type` config field (currently constrained to `"claude"`)
exists as the future routing seam — `local-run-auto-sessions` will broaden
it. No environment variable selects the model today.

Merge `decided + classified_borderline` into a single `classified[]` list.
Each element matches `classified-comment.v1.json`.

### 4. Structured-extraction

For each comment that is going to be acted on (verdict `"structural"` and
gated as a collaborator), normalize via `structured_extract.extract(comment,
diff_hunk, verdict)`. This **structured-extraction** step sanitizes the
free-text `issue_phrase` (strips code fences, shell metacharacters, URLs;
truncates to 80 chars) so it can safely flow into commit messages and tool
arguments downstream. URLs that survive are only followed when on the
`pdw.comment_url_allowlist` per `url_allowlist.is_allowed`.

### 5. Generate the fix

For each structural+gated comment, the SKILL prose calls Agent() again to
generate the actual file changes (one Agent invocation per comment or one
combined call — the worker is flexible; the only contract is that the
working tree contains all the proposed edits before `run_round` is invoked).
Use `subagent_type="general-purpose"` **with `model="opus"` pinned explicitly**
and brief the agent with: the comment, its diff hunk, the surrounding file
contents, the injected `{project_context_block}`, and an instruction to ONLY
modify files and not commit, push, or interact with `gh`. **Pin the model** —
fix generation is implementation/write work (the tiered opus-by-default rule),
and this dispatch can run standalone (outside the loop driver); without an
explicit pin it would silently inherit whatever ambient model is in effect,
including a stale local override.

Fill `{project_context_block}` from `skills/_shared/project_context.py`
(`load_context_block()`, resolved at `"$TP_ROOT"/skills/_shared/project_context.py`) so this write-capable fix worker matches the project's
conventions/stack/domain-rules instead of re-deriving (or hallucinating) them —
the same injection council Round 1 and the `tp-phase-implement` worker already
carry. **Omit the block when it is empty** (absent `project-context.md`) so the
fix prompt degrades to today's exact behavior byte-for-byte.

### 6. Commit, push, label

Hand off to the helper for the deterministic git plumbing:

```
envelope = fix_round.run_round(
    design=design,
    pr_url=pr_url,
    iteration=iteration,
    classified=classified,
    head_ref=None,        # standalone: self-resolved + refuse on mismatch
    loop_mode=False,      # loop driver passes head_ref=<head>, loop_mode=True
)
```

What `run_round` does, in order:

- Identity-gates each commenter via `gh api repos/.../collaborators/{user}`, with a
  **trusted-reviewer-bot short-circuit**:
  - **Trusted requested-reviewer bot** (e.g. GitHub Copilot — `Copilot`,
    `copilot-pull-request-reviewer[bot]`) → **gated through**, *not* deferred.
    A bot reviewer is not a repo collaborator, so `gh api .../collaborators/{bot}`
    404s ("Copilot is not a user") — but the orchestrator *requested* that review,
    so its comments are legitimate input, not untrusted drive-by (F3). The
    allowlist (`fix_round._TRUSTED_REVIEWER_BOTS`) short-circuits the collaborators
    call for these logins; extend it per-repo via the comma-separated
    `TP_PR_FIX_TRUSTED_BOTS` environment variable.
  - **404 for a non-bot login** → defer with `reason="non-collaborator"` (genuine
    drive-by protection is preserved).
  - Transient 5xx → defer with `reason="identity-gate-unreachable"` and **carry on
    without raising**. The loop retries on the next poll cycle. This is the
    "identity-gate failure aborts the round, not the loop" design rule.
- Filters gated comments to `verdict="structural"`; defers `minor` and `unclear`.
- **Targets the PR head ref (F1).** The fix must land on the actual PR head, not on
  `tp/{design}` — an orchestrator PR's head is `candidate/{slug}/single`. `head_ref`
  is resolved from `gh pr view <pr_url> --json headRefName` when not supplied. On a
  mismatch with the checked-out branch: under the loop driver / `--auto`
  (`loop_mode=True`) the head is **auto-checked-out**; **standalone the worker
  refuses** with `HeadRefMismatch` rather than silently committing to the wrong
  branch. The standalone SKILL catches `HeadRefMismatch` and prints its actionable
  message (`git checkout <head_ref> and re-run, or invoke via /tp-pr-iterate which
  checks it out automatically`). The check sits **after** the no-applicable-fixes
  early-exit, so a deferred-only round never touches the branch or makes the
  `headRefName` call.
- Commits the working tree as **ONE commit** with subject prefix `[tp-pr-fix iter-N]`
  followed by a summary derived from the structural issue phrases. The commit's
  `GIT_COMMITTER_EMAIL` is overridden to `orchestrator+{user-localpart}@{user-domain}`
  (read from `git config user.email`), so auditors can distinguish bot commits
  from the human author in `git log --format=%ce`.
- Pushes the branch upstream.
- The native-review approval path (Path B) is **self-cleaning** after a push: a
  review carries an immutable server-set `commit_id`, so a real content push makes
  `commit_id != head` and the gate fails closed automatically — no strip hook needed.
  The gate-time currency re-check (`pred_human_approved` via `review_path_satisfied`,
  `commit_id == headRefOid`) is the always-on fail-closed backstop.
- Calls `label_manager.ensure_pr_label(pr_url, "tp:do-not-merge-yet")`. Idempotent
  by virtue of the `gh pr view --json labels` pre-check. Creates the label via
  `gh label create` if missing, then retries the add.
- Returns a `fix-envelope.v1.json`-shaped dict.

### 7. Persist + return

Write the envelope under `<worktree>/.three-pillars/run/fix-envelope.iter-N.json`
(atomic write) so the loop driver and post-hoc audits can re-read it. The skill
prints the envelope's `verdict` and a one-line summary, then exits.

## Architectural constraints (C1)

- **No `import anthropic` in any `_shared/` or `tp-pr-fix/scripts/` helper.**
  The Sonnet judge call and any fix-generation Agent calls live here in the
  SKILL.md prose. Helpers compute, parse, gate, commit, push — never invoke
  the model. The plan-audit asserts this via `ast.parse` (Phase 5 Task 5.7).
- **One commit per round.** `run_round` runs `git add -A` and one `git commit`.
  Multi-comment rounds collapse into a single commit so `git log` reads as
  "one PR-fix iteration, one commit". The Sonnet pass that produces the
  changes may modify N files; they all land in one commit.
- **`GIT_COMMITTER_EMAIL` override is mandatory.** Without it, the orchestrator
  and the human author share a `git log --format=%ce`, which breaks the
  "non-loop commit means human intervention" detector in `tp-pr-iterate`'s
  loop driver (Phase 5 Task 5.5).
- **The label `tp:do-not-merge-yet` is applied every round.** Removing it is a
  human action; the worker never removes it. Pair with `tp:needs-human-attention`
  on terminal cap-exhausted / convergence-failure transitions in the loop driver.

## Standalone usage

```
/tp-pr-fix my-design --pr-url https://github.com/me/repo/pull/42
```

Runs steps 1–7 exactly once. Useful when you've manually triggered a review
(e.g., asked a reviewer to weigh in on a PR), want one targeted fix round,
and prefer not to spin up the full `tp-pr-iterate` loop. The envelope is
printed and persisted; subsequent invocations bump the iteration counter
manually (`--iteration 2`, etc.) or are skipped in favor of `/tp-pr-iterate`
once the workflow goes hands-off.

## Failure modes worth knowing

- **Empty working tree after step 5.** `run_round` detects no changes via
  `git status --porcelain` and returns `verdict="no-applicable-fixes"` without
  committing or pushing. This is the right behavior when every comment was
  deferred (non-collaborator, minor, unclear) or when the Sonnet pass declined
  to propose changes.
- **Push rejected (non-fast-forward).** Surface the `git push` error directly.
  The loop driver's human-intervention detector (Task 5.5) will likely fire
  on the next poll — there is a competing push the worker did not generate.
- **`gh` auth missing.** First `gh api collaborators` call exits non-zero with
  `auth required` in stderr. The worker treats this as `unreachable` for every
  comment (defers the whole round). Fix by `gh auth login` and re-run.

## See also

- `_shared/classifier_heuristic.py` — pure-deterministic first-pass classifier.
- `tp-pr-iterate/scripts/classifier_judge.py` (Phase 5) — Sonnet prompt
  construction + response parsing.
- `tp-pr-fix/scripts/structured_extract.py` — `issue_phrase` sanitizer + envelope shaper.
- `tp-pr-fix/scripts/url_allowlist.py` — exact-netloc HEAD-probe URL gate.
- `tp-pr-fix/scripts/label_manager.py` — idempotent `gh` label apply.
- `tp-pr-fix/scripts/fix_round.py` — the deterministic git+gh plumbing.
- `tp-pr-fix/schemas/fix-envelope.v1.json` — envelope schema.
