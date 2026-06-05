# Repo Map Preamble (optional)

Optional preamble for skills that benefit from up-front structural context about the codebase being designed for. Reduces token consumption ~15–42% by replacing exploratory Read/Grep/Glob turns with a pre-computed PageRank summary of file and symbol structure.

## When to call this preamble

**Call from**: design and audit skills that need awareness of the user's codebase as a whole — `tp-design`, `tp-design-detail`, `tp-design-audit`, `tp-implementation-audit`.

**Do NOT call from**: implementation skills (`tp-phase-implement`, `tp-task-cycle`), planning skills whose primary input is `design.md` not the codebase (`tp-plan`, `tp-spike-plan`), or skills that touch the codebase trivially or not at all (`tp-setup`, `tp-design-release`, commit/lock-management).

Position the call **after the lock preflight** and **before** any "read project docs" / "explore codebase" steps, so the map informs both.

## Procedure

### Step 1 — Detect aider

```bash
if ! command -v aider >/dev/null 2>&1; then
  REPO_MAP=""
fi
```

If aider is absent, set `REPO_MAP=""` and continue the skill normally. Do **not** prompt the user. If exploration during the skill turns out to be expensive (many Reads/Greps), mention it once at the end: *"(Tip: `pipx install aider-chat` would let me skip a lot of file-reading next time.)"*

### Step 2 — Generate the map (if aider available)

```bash
REPO_MAP=$(BROWSER=true aider --show-repo-map --model gpt-4o --yes --no-check-update --no-show-release-notes 2>/dev/null \
  | sed -n '/^Here are summaries/,$p')
```

The `sed -n '/^Here are summaries/,$p'` strips aider's startup chatter (gitignore mutations, model warnings, optional network errors) and keeps only the map proper. The first kept line is aider's instruction header, which is useful context for the model.

**Why `BROWSER=true`:** aider has multiple `webbrowser.open()` call sites — onboarding OAuth
(no `--model` + no API key), the model-warnings doc page (`--model` set but its key missing),
release notes, install offers, and more. Under `--yes`, every `io.offer_url(...)` auto-confirms
and launches a browser. `2>/dev/null` does **not** suppress this — the launch is a subprocess,
not stderr. Python's `webbrowser` module honors `$BROWSER`; `true` is a no-op binary that
"succeeds" without opening anything, neutralizing every `webbrowser.open()` in the aider
invocation regardless of which trigger fires. Scoped to the subprocess — it's a command-prefix
env var, never exported to the user's shell. See
`three-pillars-docs/tp-designs/aider-onboarding-browser-suppression/design.md` for the full
trigger inventory.

**Why `--model gpt-4o` (still required):** without an explicit model *and* with no LLM API
key, aider's onboarding (`select_default_model`) falls through to an OpenRouter OAuth offer
that `--yes` auto-confirms — and even though `BROWSER=true` blocks the *launch*, the prompt
still wastes a turn. `--model` makes `select_default_model` return immediately and never
enter onboarding. No API key is required: `--show-repo-map` is fully offline and only needs
the model's local tokenizer (tiktoken) to size the map, so an unset/invalid key produces at
most a stderr warning that `2>/dev/null` already discards. `gpt-4o` is just a stable,
always-present metadata alias — its choice does not affect the map content.

Aider auto-creates a tag cache at `.aider.tags.cache.v4/cache.db` in the repo root and adds `.aider*` to `.gitignore` on first run.

**Cost (FastAPI-sized, 1,119 .py files):**
- Cold (no cache): 5s on a 9950X3D, 10–30s on slower laptops
- Warm (cache present, no edits): ~2.6s
- Warm + a few file edits: ~2.6s — aider mtime-checks per file and only re-parses changed ones

**Token cost: zero.** Aider runs offline (tree-sitter + PageRank, no LLM calls).

### Step 3 — Use the map

If `$REPO_MAP` is non-empty and over ~500 bytes, treat it as additional internal context for the remainder of the skill:

- When deciding which files to Read for exploration, prefer files that appear in the map — they are the load-bearing modules per PageRank
- When making architectural recommendations, ground them in the symbols visible in the map (class names, function signatures)
- When the design or audit needs to name concrete file paths or interfaces, prefer ones the map confirms exist

If the map is empty or below ~500 bytes (small repo, parse error, fallback case), proceed without it — do not retry, do not block.

### Step 4 — Don't leak the map into artifacts

The map is **internal context**, not user-visible documentation. Never paste it into `design.md`, `detailed-design.md`, audit findings, plan tasks, or commit messages. It is regenerable in 5 seconds; persisting it duplicates aider's job and bloats the repo.

## Properties

- **Optional**: zero overhead when aider is absent
- **Self-caching**: aider's mtime-keyed tag cache; no skill-side invalidation
- **Idempotent**: safe to call from any qualifying skill; no global state mutation beyond the cache directory
- **Per-worktree**: each worktree has its own cache, no cross-contamination

## Containerized execution (optional)

If the user prefers to run aider inside a sandbox (no host install, no `.git/` write outside a container), they can place an `aider` wrapper earlier on PATH that invokes a containerized aider — for example:

```bash
#!/bin/sh
# ~/.local/bin/aider — containerized wrapper
exec podman run --rm --network=none --tmpfs=/tmp \
  -v "$PWD:/workspace" \
  -v "$PWD/.aider-cache:/cache" \
  -e OPENAI_API_KEY=x -w /workspace \
  --entrypoint aider \
  localhost/aider-map:latest "$@"
```

The preamble itself does not need to know whether aider is host-installed or wrapped — `command -v aider` finds either.

## Why this exists

Empirical finding from the `codesight-integration` spike (2026-04, see `three-pillars-docs/tp-designs/codesight-integration/spike-results.md` or its archived location): pre-analyzed structural context delivered as CLI content injection reduces design-phase token consumption by ~15–42% (heavier system prompts benefit more) compared to ad-hoc Read/Grep/Glob exploration. The same algorithm delivered via MCP costs ~70% MORE than CLI on the same workflow due to per-turn schema overhead — so this preamble deliberately uses CLI delivery, not an MCP server.
