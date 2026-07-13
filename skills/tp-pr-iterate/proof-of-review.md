# Proof-of-review per-round contract

Every `/tp-pr-iterate` round (and every Tier-7 Slot-11 iteration in
`tp-run-full-design`) must produce a **proof-of-review artifact** before
shelling `run_round.py`. This document is the normative prose; the Python
implementation lives in `skills/tp-pr-iterate/scripts/review_proof.py`.

## Per-round sequence (after ANGLES fan-out, before run_round.py)

1. **Resolve `base` and `head`** — the PR's base SHA and current head SHA.
2. **`capture_proof(base, head, angle_raw_responses, root=default_proof_root())`**
   — writes `<root>/<head>/{numstat.txt, transcripts.json, meta.json}` and returns
   `meta`. A degraded capture (empty/zero-line/failed diff, a write OSError, or
   **zero `angle_raw_responses` on a real diff** — reason `no-review-angles`: a
   non-empty diff alone is not evidence a review ran) returns
   `meta["degraded"] = True`.
3. **`post_codereview_comment(..., digest=format_proof_digest(meta, angle_counts))`**
   — the comment body gets a PII-light digest appended. On degraded meta the digest
   shows ⚠️ DEGRADED.
4. **Shell `run_round.py`** with `review_proof_root=<root>` (and `review_base=base`)
   on stdin so the gate enforces the proof conjunct independently.

## Fail-closed behaviour

- A degraded `meta` (empty-diff, git-failed, capture-write-failed, no-review-angles)
  → `proof_ok=False` inside `run_round.py` → `loop_driver.run_round` returns
  `blocked-no-independent-review`.
- `review_proof_root` **absent** on a convergence-eligible round (last_verdict=minor-only,
  CI all-success, unresolved_actionable=0) → CLI fails closed: `proof_ok=False`,
  `proof_enforced=False` in the envelope.
- `review_proof_root` **present** but artifact missing or degraded → `proof_ok=False`.

## Convergence requires proof

`run_round.py` does NOT converge without a proof artifact on a convergence-eligible
round. Drivers MUST always pass `review_proof_root`. The `proof_ok=None` legacy
permissive mode only applies to non-convergence rounds and direct `loop_driver.run_round`
unit-test call-sites (not to the CLI enforcement path).

## Convergence action contract (review-integrity-enforcement)

The autonomous-convergence declaration is **proof-bound**, exactly as the merge gate is —
one shared predicate, `convergence_proof.non_degraded_proof_on_head`, which **delegates to
`proof_predicate.pred_review_proof_on_head`** (the merge gate's own predicate; True only on
`GateVerdict.PASS`). There is **no second implementation** of the digest format or the
on-head predicate. Convergence is made STRICTER than the gate: on a convergence-eligible
round `run_round.py` folds the local-artifact/ground arm AND that posted-digest predicate AND
`not review_merge.is_degraded_review(codereview_findings)` (an UNPARSEABLE / NO-ANGLES angle —
which `capture_proof`'s numstat-only degraded flag can NOT see — blocks). So **convergence ⟹
the merge gate would PASS the same head.**

- **Byproduct-only.** The "reviewed-stable / converged" claim is emitted **only** as a
  byproduct of `run_round.py` returning a two-stable `terminal` (envelope `converged=true`) —
  never as independent free text in `decisions.md`, the handoff, or the PR narration. A
  degraded / absent proof on head, or an unparseable angle, makes `run_round.py` return
  `blocked-no-independent-review` with a `not_converged_reason`
  (`degraded-or-absent-proof-on-head` / `unparseable-review-angle`); the orchestrator cannot
  narrate past it.
- **Bounded re-run.** On a `blocked-no-independent-review` carrying a `not_converged_reason`,
  the orchestrator re-runs the review fan-out on head, re-`capture_proof`,
  re-`post_codereview_comment` with a fresh `format_proof_digest`, and re-shells
  `run_round.py` — **bounded by the mechanical `degraded_review_retries` counter** (committed
  iterate-state; default bound 1). `_apply_guards` (cap-exhausted / wall-clock) bounds it
  absolutely, so the counter is a tightening, not the only backstop.
- **Record + escalate.** Once the counter reaches the bound (or on the terminal), the state is
  recorded `not-converged` and escalated — but **record + escalate are the terminal's own
  mechanical effects**: the code-written `NEEDS REVIEW — no proof` decisions line + the
  `tp:needs-human-attention` label. Under `--auto` the PR is left explicitly
  not-reviewed-stable and logged; there is no narration escape hatch.

### Canonical clean-round finisher — `converge.py`

`skills/tp-pr-iterate/scripts/converge.py` is the **canonical convergence-only
finisher** for a structurally-clean round (the Tier-7 reviewed-stable finish). It
**composes** the primitives above in a load-bearing order: read the angle files →
`merge_codereview_angles` (refusing any non-clean / no-angles round) → `capture_proof`
→ `format_proof_digest` → **post the trusted-authored proof comment via
`post_codereview_comment` BEFORE shelling `run_round.py`**. That posted comment is the
**last head-binding action**: the digest embeds the exact full head SHA, so no commit
may land after it (a later commit moves HEAD and stales the head-bound proof, flipping
the merge gate to INDETERMINATE). converge.py then seeds the untracked
`iterate-state.v1.json`, shells `run_round.py` (paths `str()`-ed, `decisions_path`
omitted, `config` explicit), and asserts `convergence_proof.non_degraded_proof_on_head`
is PASS before emitting `two-stable [code-review-only]`; HEAD is invariant across the
whole call. This is the correct ordering — post the digest **before** `run_round.py`,
never after it.

## Artifact layout

```
.three-pillars/review-proof/      # gitignored; local provenance only
  <head-sha>/
    meta.json       # load-bearing: base, head, files_changed, degraded, reason, ...
    numstat.txt     # raw git diff --numstat base...head output
    transcripts.json  # per-angle raw responses (truncated to 20000 chars each)
```

`meta.json` is the gate record. `proof_present_and_nonempty(head)` returns True iff
meta.json exists, parses, `meta["head"] == head`, `meta["degraded"] is not True`, and
`meta["files_changed"] > 0`.

## Posted-comment detector (fresh-checkout-safe)

The local artifact is gitignored, so a clean clone (where the merge gate runs)
cannot read it. The **posted digest comment** is the durable, checkout-independent
proof. `review_proof.py` exposes two detectors:

- **`proof_comment_on_head(pr_url, head, *, comments_fn=None, config=None,
  self_login_fn=None)`** — True iff a **TRUSTED-authored** posted PR comment carries
  a **non-degraded** `format_proof_digest` whose parsed head equals the query head
  **exactly** (the digest carries the FULL head SHA — a 7-char prefix would be
  grindable via SHA-prefix collision). **Authenticity rule (load-bearing):**
  `comments_fn` items are
  `{"author", "body"}` dicts (the live default pulls `author.login` alongside each
  body); a digest counts ONLY when its comment's author is in the narrow trusted set
  — the **gh self login** (`self_login_fn`, live default `gh api user`) **plus config
  `review.automation_identities` extras**. A bare-string item carries no author and
  is IGNORED (never trusted by shape); the Copilot/native-bot automation floor is
  deliberately NOT digest-trusted (a prompt-injected Copilot comment must not mint
  proof). A ⚠️ DEGRADED digest is **NOT proof**. Currency is the same full-SHA
  equality rule as `proof_present_and_nonempty`'s `meta["head"]==head` — a digest
  for a **moved head** does not match. Fresh-checkout safe; fail-closed (any
  miss/error/raise/untrusted-author → False); never raises. `comments_fn` is
  injectable (the live default is `gh pr view <pr_url> --json comments`); tests
  always inject it (and inject `self_login_fn` so the self lookup never goes live).
- **`proof_ok(head, *, pr_url=None, root=None, comments_fn=None, config=None,
  self_login_fn=None)`** — the single shared head-bound predicate BOTH enforced call
  sites reuse. True iff the **local artifact** proves it
  (`proof_present_and_nonempty`, the loop's arm) **OR** the **posted comment** proves
  it (`proof_comment_on_head`, the gate's arm; `config`/`self_login_fn` feed its
  trusted-author set). Both absent → False. Never raises.

## The two enforced call sites

Proof is enforced at **both** the loop terminal and the merge gate — a single proof
source read at two points; the shared convergence predicate
(`convergence_proof.non_degraded_proof_on_head`, delegating to
`proof_predicate.pred_review_proof_on_head`) is the ONE definition both the
convergence gate and the merge gate consume:

1. **Loop terminal** — the live loop-terminal is **`run_round.py`** (shelled from both
   `tp-pr-iterate/SKILL.md` and `tp-run-full-design/SKILL.md` §Tier-7), with
   `loop_driver.run_loop` as its **tested in-process twin** (`run_loop` has no live/non-test
   caller). Each iteration computes `proof_ok` against the freshly-polled head (never a cached
   SHA) and passes the bound True/False to `loop_driver.run_round`. The proof conjunct applies
   to **both**
   arms of `_independent_review_ran` — `proof_ok=False` blocks convergence even when
   Copilot reviewed successfully (a Copilot-reviewed round with no proof on head must
   not two-stable while gate p7 refuses the same head). An un-proofed
   convergence-eligible round reaches `blocked-no-independent-review`; the
   decisions.md line and transition reason read **`NEEDS REVIEW — no proof`** and the
   run carries the `tp:needs-human-attention` label so `fleet_watch.classify_run`
   surfaces it as trouble (label-aware: an EXITED supervisor with the PR still OPEN
   + that label classifies `trouble`, not `awaiting-merge`).
2. **Merge gate** (`gate_roster.build_predicates_and_roster` →
   `proof_predicate.pred_review_proof_on_head`) — reads the **posted comment** on the
   gate-resolved `head_oid`. PASS iff a head-bound non-degraded digest comment from a
   **trusted automation author** exists; otherwise **INDETERMINATE** (never FAIL): a
   later proof-bearing review on the current head + re-evaluation flips it to PASS.
   Required by default; only an explicit `review.require_review_proof: false` OMITs
   it from the fold. Activation mirrors the stamp/balloon hermetic discipline: the
   predicate runs when `comments_fn` is injected (non-None) OR the gate runs pure
   live; a hermetic run that omits it gets an `OMITTED (inactive)` roster note, never
   a silent live `gh pr view`.

The CLI (`run_round.py`) and the in-process loop block **identically** on an
un-proofed convergence — parity is asserted by the test suite.

## Notes

- Transcripts may contain PII (code snippets, author names). Only the PII-light
  `format_proof_digest` output is posted to the PR.
- Artifact retention/pruning is out of scope for MVP (tracked as known-issue).
- For a standalone `/tp-pr-iterate` run without a PR, the digest is printed to the
  terminal; the Python `format_proof_digest` returns the same string regardless of sink.
