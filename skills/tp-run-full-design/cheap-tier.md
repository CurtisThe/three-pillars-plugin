# `--cheap-tier` — the run flag

design: cheap-tier-offload. `SKILL.md` points here from its flag list, ## Tier 1, ## Tier 3, ## Tier 5 and ## Tier 7 (held by the tier files `tier-1-pickup.md`, `tier-2-4-build.md`, `tier-5-closeout.md` and `tier-7-review.md`); this file holds the detail. The site protocol every adopting skill runs is [`skills/_shared/cheap-dispatch.md`](../_shared/cheap-dispatch.md); the eligibility table is `skills/_shared/cheap_tier.py` (`SLOTS`, `EXCLUDED`).

## The flag

- `--cheap-tier` is deprecated: every run is cheap, with `<mode>` = `on`; the flag still parses (bare means `on`; `--cheap-tier=ab` is deprecated and now runs as `on`). No other value is accepted. The launcher adds nothing; the shared resolver (`skills/_shared/cheap_tier_default.py`) still applies the deprecated `cheap_tier.default_run_flag` (`repo-config.md`) at `/tp-merge-from-main`, `/tp-post-merge` and the fleet launch lines.
- **One key, on by default.** A slot runs cheap in every run whenever it is configured — its shipped default rung, or an override `models.<slot>: "<rung>"`; `models.<slot>: "off"` opts that slot out. `handoff` ships off (it stays Opus). `classifier_judge` (its eval verdict file) and `pr_fix_reproducer` (its in-loop spawn site) keep their own runtime gates — default-on only means configured. An opted-out slot runs today's path byte for byte (`test_cheap_tier_golden.py`).
- **`--local` does not imply `--cheap-tier`, and `--cheap-tier` does not imply `--local` (D2).** `--local` keeps its own key (`local_implement.full_design`). When both are set, `--local` wins at Slot 7: its routed tier table is used unchanged and the task lever is inert. The other sites still take the flag.
- **Never a gate.** No `EXCLUDED` role is ever a cheap-tier slot. Review and audit judgments, certification, design, plan, merge and every merge-gate input stay on Opus. Review finders, council members and context scouts may run on Strata (`role_engines`); Opus judges their output (`role_engines`, a separate lever). This orchestrator holds no `<!-- cheap-tier:` stub of its own.

## Tier 1 — the slot preflight

In every run, right after the **Local preflight**:

```bash
python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py slots --root .
```

It reads `.three-pillars/config.json` **raw** (`json.loads`) and runs `cheap_tier.load_slots` once. It never goes through `repo_config_load.load_repo_config`, which prunes a schema-invalid `models` key before `load_slots` could refuse it (plan.md §Deviations 7).

- **Exit 2** (an excluded slot, an unknown slot, a rung outside the slot's rungs, or an unreadable config): refuse before Tier 2, as the `--local` preflight does. Log its stderr line as `[tp-run-full-design/tier-1]` and exit non-zero.
- **Exit 0**: it prints the `{slot: rung}` map. Log `[tp-run-full-design/tier-1] cheap-tier <mode>: slots=<list>`, where `<mode>` is `on` and `<list>` is the comma-joined `<slot>=<rung>` pairs, or `none`.

Under `--local`, export `TP_LOCAL=on` in the environment of every dispatch this run makes, so a flagless caller (`round_scratch` → `finder_round` → `role_engine.run_local`, which reads `TP_LOCAL` through `cheap_tier_default.resolve_local`) follows the flag instead of defaulting to Sonnet. A `--local` run has already passed the `local_implement` gate the env value is checked against, so the export always lands.

Then archive the router log:

```bash
python3 "$TP_ROOT"/skills/_shared/router_archive.py archive
```

This line is fail-open: log its output as `[tp-run-full-design/tier-1]`; a non-zero exit or any error is logged and never gates the run.

Still under `--local`, immediately after the archive, read the resume number and mark the run's start:

```bash
python3 "$TP_ROOT"/skills/_shared/router_checks.py
```

- Log its one summary line as `[tp-run-full-design/tier-1] router_checks: <line>` (a missing log prints `no router log`), and **record the run start time** (the moment of this call) in `decisions.md` — Tier 5's run-end line needs it.
- Fail-open like the archive: an exit 1 is logged and never gates the run: its summary line carries `alarm=ratio` (classifier calls per Strata request over the `0.035` target, the line starts `ALARM`) and/or `alarm=main_thread_strata:<ids>` (a session whose main thread took Strata; one `ALARM main_thread_strata <sess>` line follows per session). No `--since` here — this line is the baseline the run-end line is read against.

## Tier 3 — the task lever (D7)

The lever applies in every run **without** `--local`, when the Tier 1 list holds `task`. There is no parallel task protocol: `tp-worker` runs `skills/_shared/local-dispatch.md` exactly as under `--local`, with no route. Before every Slot 7 dispatch (retries too), run:

```bash
python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py task-table --plan three-pillars-docs/tp-designs/{slug}/plan.md --phase <N> --root . --cheap-tier <mode>
```

- **Exit 0.** Log `[tp-run-full-design/tier-3] phase N tier table (cheap-tier)` with the printed table. Pass the table to `tp-worker` with a `CHEAP_TIER: <mode>` line and **no** `ROUTE:` line. No routing check runs, no `[routing]` entry is written and no lease is taken: the lever is unrouted.
- **Exit 1** (the lever is off: no `models.task`). Dispatch as today, with no tier table and no `CHEAP_TIER:` line.
- **Exit 2** (a config or plan error). Log its line as `[tp-run-full-design/tier-3]` and dispatch as today.

The table is `cheap_tier.task_table` over `task_eligibility`'s own rows. A cheap-eligible row starts at `sonnet-xhigh` (a clerical row at `sonnet-medium`). No row starts on Opus: a no-oracle row starts on its `sonnet-*` rung and lands only on an Opus diff review (`local-dispatch.md` §2 step 4), and Opus is reached only by ladder escalation, which spawns its own `opus-*` variant as under `--local` (`local-dispatch.md` §2; nothing runs inline). An excluded row (Done / Skipped / Blocked) is skipped. The worker's `local-dispatch.md` §1 takes two overrides under a `CHEAP_TIER:` line: its permission is `task-table`'s exit 0 (not `local_implement_config.py --check full_design`, so a repo with no `local_implement` block works), and its tier table **is** that output, never recomputed through `task_eligibility.py`. Steps 2–4 and §2–§3 are unchanged: `task_verify` is the oracle, the ladder escalates to `opus-xhigh`, and the records come back as `telemetry.task_tiers[]` for Tier 3.5, as under `--local`.

Under `--local` the worker prompt carries today's routed table and `ROUTE:` line, and never a `CHEAP_TIER:` line.

## Other sites

Each adopting skill takes `--cheap-tier[=ab]` itself (its `argument-hint` says so) and runs the `cheap-dispatch.md` loop at its stub. The orchestrator forwards the flag on the dispatches that reach those skills; no marker file carries it.

## Tier 5 — the design-learn forward

Tier 5 Step 3 and Slot 9 always dispatch `/tp-design-learn {slug} --auto --cheap-tier`: bare `--cheap-tier`, mode `on` (the flag still parses in `tp-design-learn`).

- `tp-design-learn`'s step-7 stubs (`history_line`, `docs_draft`) then run the `cheap-dispatch.md` loop. The Slot 9 subagent builds each facts payload; the drafter never sees the run's context.
- Every draft there is stored with `--reviewed false`. An `--auto` draft is reviewed at the PR, not by an operator, so it never counts as 0-edit evidence in `cheap_ab.py report`.
- `/tp-design-learn --auto` still never edits `vision.md`, and its stubs never draft for it.
- The tier-summary Decision Entry is not a slot (plan.md §Deviations 3), so this orchestrator still holds no stub of its own.
- **Depth 2.** When the Slot 9 `tp-generator` spawns `tp-drafter` at those stubs, that is a second sanctioned subagent level (orchestrator → `tp-generator` → `tp-drafter`). It sits beside Slot 7's `tp-worker` → `tp-task-worker` (`SKILL.md`, "The orchestrator runs in the main conversation"). The drafter writes one file and spawns nothing, so there is never a third level. Tier 5 Step 3 runs the skill inline, so its drafter is depth 1.
- **Depth 2, the retro reviewer.** Step 10b of that skill spawns one `Agent(subagent_type=agent_ref("tp-readonly-auditor"), model="opus")`, only when `run_retro.py draft` printed `review_needed`. It is a second sanctioned level beside `tp-drafter`'s (orchestrator → `tp-generator` → reviewer); it reads and spawns nothing, so there is never a third level.
- **Run-end resume line (under `--local`).** After Slot 9 — where the run's Strata task work has ended, so Tier 7 rounds fall outside the window — read the run's own number:

  ```bash
  python3 "$TP_ROOT"/skills/_shared/router_checks.py --since <run start>
  ```

  `<run start>` is the time Tier 1 recorded. Log the one line as `[tp-run-full-design/tier-5] router_checks: <line>`. Fail-open exactly as at Tier 1: an exit 1 (`alarm=ratio` or `alarm=main_thread_strata:<ids>`) is logged, never a gate, and a missing log prints `no router log`.

## Tier 7 — the loop forward

The Tier 7 round loop (`tier-7-review.md` ## Tier 7) runs [`skills/tp-pr-iterate/cheap-tier.md`](../tp-pr-iterate/cheap-tier.md) every round with the run's mode (`on`), exactly as a top-level `/tp-pr-iterate` does. The orchestrator is the loop driver, so every drafter there is depth 1. That file holds the prep slots, the scaffold, the round-tail lines and the A/B; nothing here repeats it.

## Reach

Two limits hold today (design-audit note 5):

- **`tp-pr-fix` takes the flag only from its own argument** (`/tp-pr-fix {design} --pr-url <url> --cheap-tier[=ab]`). Inside `tp-pr-iterate` (a #188 file), the forward reaches the loop's fixes only as the round tail's `CHEAP_TIER:` line, a log line: the loop's fixes run in the round tail, which cannot spawn, so it runs today's generation and logs that once per fix round (`skills/tp-pr-iterate/cheap-tier.md` §Tail lines). So its `pr_fix_reproducer` stub is inert in-loop and standalone: only `tp-pr-iterate`'s review angles attach a `reproducer` to a finding, so a standalone round's reviewer comments are never eligible and every one runs today's generation. Its `classifier_judge` stub is null for the reason below.
- **The classifier slot stays null until two things hold.** `spec --slot classifier_judge` gives a null rung unless `skills/tp-pr-iterate/eval/classifier-rung.json` exists with `thresholds_met: true`, and its `local_model` and `route` match the current `local_implement.model` and the route the site passes. No site passes a route today, so today's Sonnet `model_for("classifier")` stays in effect until both the verdict file and a route hold (plan.md §Deviations 5). The eval directory is dev-only, so a consumer repo never has the file.
