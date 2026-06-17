---
name: tp-inflight
description: Print the in-flight design registry — every origin/tp/* design branch with its owner, phase, branch, age, and staleness — built live from the remote. Read-only, fail-open, no lock, no side effects. Use to see what other designs are in flight before you start work.
argument-hint: "[--json]"
---

# In-Flight Design Registry

Show what design work is currently in flight across the team. The registry is built **live** from `origin/tp/*` branches and each branch's committed `three-pillars-docs/tp-designs/{name}/lock.json` — the same source of truth the collaboration preflight uses, surfaced on demand.

This skill is **read-only**: it acquires no lock, writes nothing, and never blocks. If `origin` is unreachable it reports the registry as **unavailable** (it cannot list in-flight designs — there is no local-listing fallback) and still exits cleanly; your local work is unaffected.

**Arguments**:
- `--json` (optional) — emit the registry as structured JSON instead of the human table (for piping into other tooling).

## Steps

0. **Run first-run preflight** per `skills/_shared/first-run.md`.

1. **Refresh tp/* refs (fail-open)**: the registry reads lock blobs out of objects already present locally, so fetch the in-flight branches first:
   ```bash
   git fetch --quiet origin 'refs/heads/tp/*:refs/remotes/origin/tp/*' || true
   ```
   The trailing `|| true` is load-bearing — if there is no remote, you are offline, or auth fails, **continue anyway**. A fetch failure must never block the skill; the helper reports the registry as unavailable (origin unreachable) on its own and still exits 0.

2. **Build and print the registry** by running the shared helper:
   ```bash
   python3 "$TP_ROOT"/skills/_shared/inflight_registry.py          # human table (default)
   python3 "$TP_ROOT"/skills/_shared/inflight_registry.py --json   # structured JSON
   ```
   Pass `--json` through when the user asked for it. The helper lists `origin/tp/*` via `git ls-remote` (always live — no cache), reads each branch's `lock.json`, and renders one row per in-flight design with owner, phase, branch, age, and a flag column (`⚠ stale` when older than the 30-day staleness threshold, `· unreadable` when the lock blob couldn't be read).

3. **Relay the output** to the user verbatim. If the registry is **degraded** (origin unreachable), say so plainly — the table/JSON already carries a degraded banner/flag, so just surface it rather than retrying the fetch.

4. **Point stale designs at graceful handoff**: if any row is flagged `⚠ stale` (likely abandoned, `last_touched` > 30 days), mention that the design can be claimed cleanly via `/tp-design-release {name}` by its current owner — or taken over with `--force-takeover` on the next lock-enforcing skill. **Never act on staleness automatically** — surface it only.

## Rules
- **Read-only, no side effects**: this skill never writes a lock, never commits, never pushes. It only reads refs/objects and prints.
- **Fail-open always**: the `git fetch` is best-effort (`|| true`) and the helper itself always exits 0. A remote/network problem makes the registry unavailable; it never errors out.
- **Always live, no cache**: the branch list comes from `git ls-remote` every invocation. There is no TTL or stored snapshot.
- **Staleness is informational**: a `⚠ stale` flag is a *likely-abandoned* hint (30-day threshold), never an instruction to auto-release or auto-take-over.
- Do not interpret different design names as collisions here — `/tp-inflight` is awareness-only. The same-name collision *gate* lives in the collaboration preflight (`skills/_shared/collaboration.md`), not in this skill.

## Owner column semantics

The **owner** column in the printed table is rendered by `display_label` in
`skills/_shared/orchestrator_identity.py` (inherited from `inflight_registry.format_table`).
An orchestrator-held lock (`owner: "orchestrator:<email>"`) renders as `<email> (orchestrator)`;
a human-held lock renders verbatim; a released lock renders `-`. The `(orchestrator)` marker
signals that the lock was written by an autonomous runner, not a human developer.
