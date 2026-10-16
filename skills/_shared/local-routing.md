# Local Routing Protocol

Who runs `local_route_check.py`, when, and where the result is logged via
`local_route_log.py append`. Prose form of the detailed design's "who checks, and where the
result goes" table (dd `:171-206`); `<d>` is the design's own directory. Every `check --decisions`
and `end` invocation below is piped, on one line, into `local_route_log.py append --decisions
<d>/decisions.md`; `summary` never is (read-only, quoted back at report time, not written).

## Direct runs

In a **direct run** — the launcher's effective backend `CLAUDE_LAUNCHER_BACKEND` is `direct`
and the session carries no router base URL (`ANTHROPIC_BASE_URL`), the case for a seat or run
session — every `check` here probes the **children's route**: the launcher's plan for the
folder, resolved by `children_route.py`, never the session's own env. That holds only when this
run's `child_spawn.py probe` answers `child` (`children_route.effective_env` asks it itself, so
the first `check` of a run may run the probe, and the first in a repo its one-per-repo smoke:
give the `check` the same 300000 ms Bash timeout as `probe`). An `in-process` answer leaves the
session's env as it is, so the `check` says `unrouted/no-base-url` and every `local-*` rung
floors to Sonnet as before — a direct run never spawns a `local-*` `Agent(...)` in-process.

## Interactive

- **Row 1 — `/tp-phase-implement --local`, main thread.** On the invocation's first phase, step 4b
  (`local-dispatch.md` §1), **after** the step 1 lock:

  ```
  python3 "$TP_ROOT"/skills/_shared/local_route_check.py check --decisions <d>/decisions.md --scope run-start | python3 "$TP_ROOT"/skills/_shared/local_route_log.py append --decisions <d>/decisions.md
  ```

  Every `tier_ladder.py start` on this thread reads `--route-from <d>/decisions.md`; no route is
  carried in memory.

- **Row 2 — standalone `--auto --local`.** Each auto-advanced phase re-enters step 4b and runs the
  same pipe with `--scope "phase <N>"` in place of `run-start`.

- **Row 3 — interactive run end.** **Once per invocation**: the last phase, or an env-error halt
  (§4), just before step 9's wrap-up commit — never between auto-advanced phases:

  ```
  python3 "$TP_ROOT"/skills/_shared/local_route_check.py end --decisions <d>/decisions.md | python3 "$TP_ROOT"/skills/_shared/local_route_log.py append --decisions <d>/decisions.md
  ```

  Step 10 prints the `end` line read back from `<d>/decisions.md`.

## Orchestrator

- **Row 4 — full-design, Tier 1.** The local preflight after `--check full_design`, every
  invocation (resumes too), runs a bare `check` with **no** `--decisions`:

  ```
  python3 "$TP_ROOT"/skills/_shared/local_route_check.py check
  ```

  The result is **printed and never logged**: it opens no window.

- **Row 5 — full-design, every Slot 7 dispatch.** Immediately before each `tp-worker` dispatch —
  **Tier 3 retries and impl-audit re-dispatches included**, every Slot 7 dispatch checks:

  ```
  python3 "$TP_ROOT"/skills/_shared/local_route_check.py check --decisions <d>/decisions.md --scope "phase <N>" | python3 "$TP_ROOT"/skills/_shared/local_route_log.py append --decisions <d>/decisions.md
  ```

  then `task_eligibility.py … --route '<route>'`, where `<route>` = the `route` value `append`
  printed (null: no ROUTE: line): that row's line carries the projected `ROUTE: <route>` JSON
  (five keys, quote-free) into the dispatch prompt, and the worker's own `tier_ladder.py start`
  takes it as `--route '<route>'`.

- **Row 7 — the exit report.** Every non-Tier-7 exit (the Cleanup list, an escalation, SIGTERM)
  reads (before or after Tier 5.6's `end`, the same command):

  ```
  python3 "$TP_ROOT"/skills/_shared/local_route_check.py summary --decisions <d>/decisions.md
  ```

  This is **always one command** — `summary --decisions`, never `end` — against the design's
  current dir (`completed-tp-designs` once archived), with no before/after-`end` branch: when no
  check has opened this window, the fallback is the last recorded routing line, not a re-derived
  ladder suffix.

## End

- **Row 6 — full-design, run end.** **Tier 5.6** entry, first thing, on every path to the archive
  (a Tier 5 pass, or the design-learn proceed):

  ```
  python3 "$TP_ROOT"/skills/_shared/local_route_check.py end --decisions <d>/decisions.md | python3 "$TP_ROOT"/skills/_shared/local_route_log.py append --decisions <d>/decisions.md
  ```

  Idempotent: a resumed repeat over an already-closed window is a **no-op** — nothing is appended.

- **Read back, never memory.** The `end` entry lands before Step 3 archives `decisions.md`, so the
  Tier 6 PR description and the final report quote every `### [routing] end:` line **read back**
  from the design's decisions.md at compose time — `three-pillars-docs/tp-designs/{slug}/` while
  in flight, `completed-tp-designs/{slug}/` once archived. No routing line is held in context
  across a tier.

- **`--mode design|plan` note.** Those modes dispatch no Slot 7 `tp-worker`, so they open no window
  and their Tier 5.6-less runs write no `end`; likewise a resume landing after the `end` opens
  nothing.

- **Every run, no condition.** Tier 5.6's `end` runs on **every run** — there is no `--local`
  qualifier here, unlike Row 3 or the Cleanup entry — because `--local` is not persisted across a
  cold resume: the orchestrator cannot tell, from a bare resume, whether the window it might be
  closing was ever opened under `--local`. Running `end` unconditionally and relying on its
  idempotence (a **no-op** when no window is open) is simpler and safer than re-deriving the flag.

- **Fold-conflict and BLOCK exits.** Tier 5.6's "Fold conflict" legacy candidate→tp PR (exit 0) and
  `/tp-design-complete --auto` BLOCKs (exit non-zero) skip the archive and `## Cleanup`, but their
  report — and, for Fold conflict, the legacy PR body — still quotes the routing line from
  `summary --decisions` read back from `tp-designs/{slug}/decisions.md` (the `end` line just
  written); the `end` entry is committed together with the fallback's decisions.md entry.

- **Interactive run end, for reference.** The interactive pipeline's own `end` is Row 3's pipe
  under §Interactive — run **once per invocation**, before step 9's last wrap-up commit — not a
  second invocation described here.
