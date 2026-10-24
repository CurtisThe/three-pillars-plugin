# Run retro — a run's own framework friction

design: design-learn-retro. Step 10b of `/tp-design-learn` and `/tp-spike-learn` runs this loop, in every repo, with or without a fleet or a seat. It reads what the run left behind (`decisions.md`, the finalizer and escape ledgers, dispatch telemetry, a ladder `stops.ndjson`, junit under `CI_LOCAL_MANIFEST_DIR`), groups it by root cause, drops what is not a reusable mechanism, has one Opus reviewer re-check what is left, and files the survivors. It proposes; it never edits a skill. The CLI is `python3 "$TP_ROOT"/skills/_shared/run_retro.py`; the modules behind it are stdlib only and import nothing from notion-ops (the board is reached by calling its skill, never by importing it).

## The protocol

`D` is the design (or spike) directory: active, or archived under `completed-tp-designs/`.

1. `known-items --repo . --out <scratch>/known-items.json` lists the repo's open seeds, so a finding already covered is matched, not re-filed.
2. `draft --design-dir D --known-items <scratch>/known-items.json` writes `D/retro-findings.json` (drafts, observations, evidence lines, and the `filed` list a re-run carries over) and prints `{"drafts": n, "observations": m, "review_needed": bool}`. Anything below the bar goes to one `### [run-retro] observations` entry in `decisions.md`; the CLI writes it, never the skill.
3. The reviewer runs only when `review_needed`: `review-prompt --design-dir D --known-items <scratch>/known-items.json` prints the brief path; spawn `Agent(subagent_type=agent_ref("tp-readonly-auditor"), model="opus")` on it. It replies with a last fenced json block: a list of `{slug, verdict, reason}` (`verdict` is `accept`, `reject` or `merge-with`, and `merge-with` adds `target`, a known item's id). Save the reply as the verdicts file; `file` reads the last fenced block of it, or plain JSON.
4. `file --design-dir D --verdicts <V> --board <key|none> --notion-skill <present|absent>`. With zero drafts there is no reviewer and no verdicts file: call `file` without `--verdicts`; only the filter's evidence lines are applied. A draft with no verdict is rejected, never filed.
5. The board path prints `{"outbox": path, "entries": n}` and posts nothing. With `entries` above zero, post (see Consent): call `/notion-file-upgrade-request` once per `retro-outbox.json` entry, keep each reply line, write them as `[{slug, reply}]`, then run `record --design-dir D --filed <reply file>`. `record` refuses the whole file when it holds a slug that is not in the outbox.
6. The seed path prints every seed path it wrote or changed, one per line, including a seed that only gained an evidence line. Stage exactly those paths in the learn commit, never a glob, with `retro-findings.json`, `retro-outbox.json` and `decisions.md`.
7. `/tp-design-complete` and Tier 6 print `pr-section --design-dir D` into the PR body: a `## Framework friction` block listing the filed row ids and seed slugs, or nothing.

`note --design-dir D --title T [--body B]` appends one `### [run-retro] T` entry. Skill prose never edits `decisions.md` for the retro by hand.

## Consent

- The configured `automated_upgrades:` board is the user's consent to the outward write. No board, no post.
- Interactive: show the outbox and ask once before any post. On a decline run `note --design-dir D --title declined`, post nothing, run no `record`; the outbox stays in `D`, and a later post is a manual one on its path.
- `--auto`: post under the configured board and never prompt. `record` logs each id.
- Board set but `notion-file-upgrade-request` missing from the session's skills: pass `--notion-skill absent`. `file` takes the seed fallback, logs one `[run-retro] fallback notion-skill-unavailable` entry and attempts no Notion call.
- A `not filed` reply for one entry (the teamspace has not turned `automated_upgrades` on, or the skill's redaction gate refused it) is normal: that entry takes the seed fallback below, alone.

## Fallback seeds (no board, no `notion-file-upgrade-request`, no Notion MCP, or a `not filed` reply)

Each accepted draft becomes `three-pillars-docs/tp-designs/<slug>/seed.md` on the design branch, marked `origin: run-retro` and `upstream: three-pillars`. It never overwrites an existing slug: that draft becomes an evidence line on the existing seed. In a consumer repo the seed is a proposal in the PR the user reviews; the user forwards or drops it.

## Depth 2

Under `/tp-run-full-design`, Slot 9 runs the learn skill inside a `tp-generator` subagent, so the reviewer is a second subagent level. It is sanctioned beside `tp-drafter`'s (`skills/tp-run-full-design/cheap-tier.md`, Depth 2): the reviewer reads and spawns nothing, so there is never a third level. Interactive and standalone runs spawn it from the main conversation.

## Companion dependency: notion-ops-skills

The board path needs a separate plugin, notion-ops-skills, and its standalone skill `/notion-file-upgrade-request` (that skill's own doc is the spec). It reads an `automated_upgrades:` block in its `base-config.yaml` and is off unless the teamspace turns it on. It runs its own redaction gate, with no override, and files one request per call to the shared **Automated upgrade requests** board. It dedupes by Package plus Signature: a repeat from a new run adds one evidence comment and a Recurrence bump, never a second row, and the same run filed twice is a `noop`. It reads nothing from the session and no outbox file: every field arrives as a flag.

`--notion-skill present` means `notion-file-upgrade-request` is in the session's skill list. It is not a mode of any other skill. Until it is listed, the seed fallback applies and nothing here is broken.

The call, one per outbox entry, has the entry's `payload` keys as flags, `_` turned into `-`: `--root-cause-group`, `--source-run`, `--reviewer-verdict`, `--evidence` (repeated, one per pointer) and `--rrsi-flag` (repeated; left out when the list is empty). `--reviewer-verdict` takes the word before the first `:` of the payload's reviewer verdict (`accept` or `merge-with`), never the reason. The reply is one line, `filed: <create|bump|repair|noop> <row url>` or `not filed: <reason>`.

## `retro-outbox.json`

The only input of the filing loop. `file` writes it, sealed, holding only entries that passed every local check:

```json
{"board": "<board key>", "entries": [{"slug": "<proposed slug>", "retro_key": "<key>", "board": "<board key>", "payload": {"...": "BOARD_FIELDS"}}]}
```

An entry exists only for a reviewer `accept` with a clean `leaks()` pass, and never for the `feedback` board (a machine report never goes to the human Feedback board). `retro_key` stays on the entry and is never a flag: it is how `record` finds the entry again.

`record` takes `[{slug, reply}]`, one row per entry the skill was called for, each `reply` the skill's reply line verbatim (it also takes the mapped `[{slug, id}]`, `id` the row url). It matches each `slug` against the outbox, then maps the reply:

- `filed: <action> <url>` becomes `{slug, id: <url>}`: `id:<slug>:<url>`, the entry's retro key and its slug go into `filed`, and `decisions.md` logs the url.
- `not filed: <reason>` seeds that entry alone through the seed fallback above and logs one `[run-retro] not filed` entry that names the reasons; the other entries are unaffected. `record` prints the seed paths in `seeds`: stage exactly those.

## The board contract

Each `payload` has exactly the keys of `run_retro_file.BOARD_FIELDS`, in that order; the constant is the one source of the field list, so this doc does not copy it. The values are shapes (mechanism tokens, counts, evidence pointers), never values from the run: no env value, token or path content. `package` is `three-pillars`, `type` is `Bug` or `Idea` from the draft, and `version` is the shipped plugin version, read from `.claude-plugin/plugin.json` (`unknown` when unreadable). The skill validates every field, and the board's signature comes from the package and the root cause group, so a repeat of the same cause is a recurrence.

## Re-runs

`draft` rewrites the drafts but keeps `filed`; `file` skips every draft and evidence line whose key or slug is in `filed`. Draft, file, record, then draft and file again yields an empty outbox and no new seed or evidence line.
