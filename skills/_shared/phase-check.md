# Per-phase check — one cheap finder, one Opus checker, one fix pass

design: review-convergence (Part A). The check runs **once per phase**, right after that
phase's Tier 3.5 returns `ok`, and never loops: the finder is cheap, the checker is one Opus
pass, findings go back to the phase's worker **once**, and everything the worker did not fix
or dispute is carried into the impl audit as *known* rather than re-found. `SH` =
`skills/_shared`. Every command below runs from the repo root; `<TP>` is the substrate root
(`local-dispatch.md` §Terms).

## Terms

- `<d>` = the in-flight design dir (`three-pillars-docs/tp-designs/<slug>`), `<N>` = the
  phase number, `<scratch>` = the out-of-tree scratch dir `prepare` prints.
- **Carry** = `<d>/phase-check-carry.json` — one entry per phase
  (`skip` / `resume` / `ready` states below) plus `items[]`, the findings that survived the
  phase. It is committed, so a cold resume and the impl audit both read it.
- The CLI is `python3 <TP>/skills/_shared/phase_check.py` with subcommands `prepare`, `put`,
  `close`, `known`, `jdi-warn`.

## Steps (Slot 7)

1. **Prepare** — after the Tier 3.5 `ok` envelope (it carries `sha`, the phase head):
   `phase_check.py prepare --design-dir <d> --phase <N> --base <phase_base_sha> --head <sha>`.
   Three statuses: `skip` (the phase is already `closed` — never re-check a phase), `resume`
   (an `open` entry from a crashed session: re-dispatch the slots with the returned prompts),
   `ready` (the deterministic half ran — fragility lint, invariance, targets-frozen,
   trust-boundary surfaces — and the two prompts are in `<scratch>`).
2. **Finder** — the cheap class `review_finder`: under `--local` resolve it with
   `cheap_engine.py resolve review_finder --local` (Strata), else the plain
   `cheap_engine.py resolve review_finder` (Sonnet). On `--local` dispatch it as the
   `agent_ref` printed by `strata_effort.py spawn tp-review-confirmer`; the Sonnet path is
   unchanged. Dispatch it with `<scratch>/finder.prompt.md`, and pipe its one JSON reply through
   `phase_check.py put --scratch <scratch> --slot finder`.
3. **Checker** — one `tp-phase-checker` dispatch (model `opus`, effort `medium` —
   `model_policy.floor("phase-check")`) with `<scratch>/checker.prompt.md`, which adds the
   finder's reply and the security lens when surfaces are present. Its reply goes through
   `phase_check.py put --scratch <scratch> --slot checker`.
4. **Worker once** — findings go back to the **SAME phase worker** once, in a fresh worktree (Tier 3.5 removed the phase's own): `git fetch -q origin candidate/{slug}/single`, `worker_root.py reap`, then `worker_root.py open --base-ref origin/candidate/{slug}/single` (`--phase` is the phase number, `1` for the jdi check), as `skills/tp-run-full-design/tier-2-4-build.md` Tier 3 (tip snapshot and `assert-unmoved` included): the fix worker must start from the candidate commits it fixes. `SendMessage` to the Tier 3.5 `agent_meta.agentId` carries the new `WORKTREE:` line; if it cannot be resumed, one fresh `tp-worker` for that phase with the findings as its task and that `WORKTREE:` line. Under `--local`, one fix task to the rung that ran the phase's last task. One pass, then the reply (§Worker reply shape) — never a loop.
5. **Tier 3.5** — when the worker produced a follow-up commit, re-run `run_tier_3_5.py` on it
   (same phase, same base). A failure uses the existing retry table (`tier_ladder.py`), not a
   new one. A **disputed** finding never blocks the phase.
6. **Close** — `phase_check.py close --design-dir <d> --phase <N> --scratch <scratch>
   --worker-reply <file>`: every checker finding the worker did not fix becomes a carry item
   (`unfixed`, or `disputed` with its reason). It prints `{"carried": n, "fixed": m}`.
7. **Commit** — `git add <d>/phase-check-carry.json` (scoped add, never `-A`) and commit it
   **before the next phase dispatch**, so a crash between phases resumes from the carry.

## Caps

The finder is a cheap agent, so it is capped like every other cheap dispatch
(`agent_caps.py`, ruling 23):

- After the finder spawn: `python3 <TP>/skills/_shared/agent_caps.py spawned --slot-root
  <scratch> --slot finder --agent-id <id> --started <iso>`.
- One background `python3 <TP>/skills/_shared/agent_caps.py watch --slot-root <scratch>` for
  the check's slot root; it prints one JSON verdict line per change. A `stop` verdict is
  handled per `local-reaper.md` / `cheap-dispatch.md` §3 step 5 — the reply it never wrote
  simply counts as absent and the checker judges the diff alone.

## Worker reply shape

The worker's one reply is one strict JSON object, put through `close --worker-reply`:

```json
{"fixed": [ids], "disputed": [{"id", "reason"}]}
```

An id in neither list is **not-fixed** and lands in the carry as `unfixed`. A dispute needs
a reason — the reason is what the impl audit and the PR body show.

## Impl audit

Tier 5's synth call passes the design dir: `build_synth_prompt(artifact_paths, round1,
round2, "impl-audit", code_input=…, design_dir=<d>, repo=<repo>)`. The prompt then carries a
`## Known items (per-phase check)` block built from `phase-check-carry.json` (`phase_check.py
known --design-dir <d>` reads the same file), so the synth lists each carried finding as
**known**, not a new find, and never counts it against the verdict unless it is still open in
the code. The final verdict writes `<d>/audit-dispositions.json` through
`audit_dispositions.write`.

## Just-do-it

When `weight_class.py read <d>` is `just-do-it`, `/tp-design-complete` step 6g
runs the **same steps** with phase `jdi`: base = `git merge-base origin/<base> HEAD`, head =
`HEAD`, through `phase_check.py prepare --jdi --design-dir <d> --phase jdi --base <mb> --head
HEAD` (`--jdi` skips invariance and targets-frozen; the criteria come from `design.md`
Scope). There is no separate worker: the window itself fixes or disputes each finding, then
`close --phase jdi`. As the backstop for the prose trigger, step 6g and Tier 6 run
`phase_check.py jdi-warn --design-dir <d>` right before PR creation: for a just-do-it design
whose carry has no `jdi` entry it prints one loud line; it is advisory — `exit 0` either way.

## Never

- **Never a second pass on a phase**: `prepare` answers `skip` for a closed phase and `close`
  never re-reviews — the check is once per phase whatever head is passed to it.
- **Never a worker loop**: one fix pass, then carry. An unfixed finding is a carry item, not a
  retry, and a disputed one is recorded with its reason and stays non-blocking.
- **Never inline in a slot**: the finder, the checker and the fix pass are dispatched; the
  orchestrator only runs the deterministic CLI calls and the Tier 3.5 re-run.
- **Never an uncommitted carry**: step 7 commits `phase-check-carry.json` before the next
  phase dispatch, so a crash between phases loses nothing.
