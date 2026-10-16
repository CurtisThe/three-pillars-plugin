---
name: tp-test-setup
description: "Configure test infrastructure for the TDD pipeline, informed by the project's stated architecture. Runs after /tp-docs-init so test-runner and layout choices are grounded in the documented system structure."
---

# Test Setup

Configure a project's test infrastructure so the TDD pipeline can run tests immediately — with choices informed by `three-pillars-docs/architecture.md` rather than guessed at before the architecture is documented.

**No arguments** — operates on the current repository, not a `[a-z0-9-]+` design directory.

## Sequencing

This skill deliberately runs **after** `/tp-setup` (vision) and `/tp-docs-init` (architecture, roadmap, known-issues):

1. `/tp-setup` — the **why** into `three-pillars-docs/vision.md`.
2. `/tp-docs-init` — the **how** into `three-pillars-docs/architecture.md`, plus roadmap and known-issues.
3. `/tp-test-setup` — test infrastructure, informed by architecture (this skill).

The ordering matters: picking a test runner, layout, and coverage tool before the architecture is documented is premature. By the time this skill runs, `architecture.md` should describe the key components, language/runtime choices, and integration boundaries — all of which should shape the testing strategy.

## Prerequisites

- `three-pillars-docs/architecture.md` should exist. If it's missing, tell the user `/tp-docs-init` is the recommended next step and ask whether they want to proceed anyway. Do not hard-block — a user who knows what they're doing may want to set up tests in parallel with architecture work. Just make sure they've made the call explicitly.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

1. **Read context**:
   - Read `three-pillars-docs/vision.md` per `skills/_shared/read-project-docs.md` — the vision's principles may constrain test choices (e.g., "no network calls in tests", "fast feedback is non-negotiable").
   - Read `three-pillars-docs/architecture.md` if it exists. Pay attention to: language/framework, key components, integration boundaries, async/concurrency model, data stores, external dependencies. These inform test tooling and layout.
   - Read `three-pillars-docs/known_issues.md` if it exists — flaky or slow test areas may already be documented.

2. **Analyze the project codebase**:
   - Detect language(s) and framework(s) from source files and package manifests (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Gemfile`, etc.).
   - Check for existing test infrastructure: test directories, test config files, test scripts in package manifests.
   - Check for existing test files and their patterns.

3. **Present findings**:
   - Language/framework detected
   - Existing test infrastructure (if any)
   - Architecture-relevant signals that shape the recommendation (e.g., "architecture.md says the system is async-first, so the test runner needs async support")
   - What's missing or needs configuration

4. **If test infrastructure already exists**, confirm it works:
   - Try running the existing test command.
   - If tests pass, report success and check that `.claude/settings.json` has the right `Bash(...)` permission for the TDD pipeline.
   - If tests fail, diagnose and offer to fix.
   - Cross-check the existing setup against `architecture.md`: does it actually test what the architecture describes? Flag gaps but do not auto-fix.

5. **If no test infrastructure exists**, propose a setup informed by architecture:
   - **Test runner**: Recommend the standard choice for the detected stack AND the architecture's constraints. Examples: vitest for modern JS/TS; pytest (plus `pytest-asyncio` if the architecture is async) for Python; `go test` for Go; `cargo test` for Rust. If the vision's principles include a constraint like "no network calls in tests", mention how the chosen runner supports that (fixtures, mocks, sandboxing).
   - **Directory layout**: Recommend the conventional layout for the stack (`__tests__/`, `tests/`, `test/`, colocated `*.test.*`). If `architecture.md` names integration boundaries, suggest a parallel `tests/integration/` split.
   - **Coverage**: Recommend if available for the stack (c8/v8 for JS, coverage.py for Python, built-in for Go).
   - Present options and let the user choose — don't assume.

6. **On confirmation, configure**:
   - Install dependencies (e.g., `npm install -D vitest`, `pip install pytest`).
   - Create config files if needed (e.g., `vitest.config.ts`, `pytest.ini`).
   - Configure the runner to emit machine-readable results so later pipeline steps can read them: for pytest, `--junitxml=...` through `addopts` in the config file; for other runners, the machine-readable equivalent recorded in the repo's `test.command` (step 6b).
   - Create a starter test file that demonstrates the project's test pattern. The starter should exercise a real piece of the system, not `1 + 1`. Prefer testing something mentioned in `architecture.md` (e.g., a key component's happy path) so the test itself demonstrates the vision-architecture-test chain.
   - Offer property testing alongside the starter test: a Hypothesis property paired with a concrete example (Python) or the stack's equivalent. **Offer, never install** — ask, and only add the dependency if the user confirms. Never install a test library silently.
   - Scaffold the per-repo fragility rules file `.three-pillars/fragility-rules.json` with the empty form `{"schema_version": 1, "rules": []}` (create the directory if missing).
   - Add or update test scripts in package manifest if applicable.

6b. **Record the test setup in the repo config** through the shipped writer CLI `repo_config_load.py set` (which validates against the schema and writes atomically):
   - `python3 "$TP_ROOT"/skills/_shared/repo_config_load.py set test.command '"npm test"'` — the canonical command step 9 verifies, as a JSON string.
   - `python3 "$TP_ROOT"/skills/_shared/repo_config_load.py set test.runner '"pytest"'` for a pytest suite, or `set test.runner '"other"'` for any non-pytest runner (the schema allows exactly `pytest` and `other`).
   - Non-pytest runners are recorded with `runner: "other"`; downstream Targets verification then reports `unverified (non-pytest runner)` for them rather than crashing.
   - For a non-pytest runner, say that the 3-run condition for changed tests reports `unverified` until the `test-runner-adapter` design lands; the setup still records the runner so the pipeline degrades to that signal rather than crashing.
   - The `--exec` lanes run the recorded command through the shell, but per-node Targets verification (local implement, the Tier 3.5 re-run) runs a pytest `test.command` as one argv with no shell. Only a plain argv is accepted there: words of `[A-Za-z0-9_./:=,@+%-]` or quoted strings with no backslash, `$`, backtick, quote or newline inside, separated by spaces or tabs. Anything else (`&&`, `;`, `|`, a redirect, a glob, `$`, `~`, a backtick, a `#`, a backslash, a `NAME=` prefix) is refused as `runner-needs-shell` naming the first offending character, and the same rule applies to an operator's `--test-cmd` override. Record a plain argv for a pytest suite (e.g. `python3 -m pytest -q tests`).

7. **Configure Claude Code permissions**:
   - Check `.claude/settings.json` for existing `Bash(...)` permissions.
   - Add the test command permission so the TDD pipeline can run tests without prompting (e.g., `"Bash(npm test:*)"`, `"Bash(pytest:*)"`).
   - Show the user what permission is being added and why.

8. **Ensure session artifacts are gitignored**:
   - Check the project's `.gitignore` for these patterns:
     ```
     three-pillars-docs/tp-designs/*/handoff.md
     three-pillars-docs/completed-tp-designs/*/handoff.md
     three-pillars-docs/tp-designs/*/demos/scratch/
     three-pillars-docs/completed-tp-designs/*/demos/scratch/
     three-pillars-docs/tp-designs/*/demos/**/*.tmp
     three-pillars-docs/completed-tp-designs/*/demos/**/*.tmp
     ```
   - If missing, append the relevant lines (each comment on its own line — git .gitignore does NOT support inline/trailing comments) and tell the user what was added and why.
   - **Note**: `decisions.md` and `demos/` are tracked evidence — they are part of the design's permanent record and must survive cross-machine sync, archival, and review. Only `handoff.md` is purely ephemeral. The `demos/scratch/` subdirectory and `*.tmp` files inside `demos/` are the throwaway hatch for genuine ad-hoc scratch work that must NOT be committed; everything else under `demos/` is tracked.

9. **Verify**: Run the test suite once to confirm everything works.

9b. **Wire up the test hygiene artifacts**:
   - Link the project's test README to the fragility guidance: add a link from the project's test README (create a tests/README.md if none exists) to `$TP_ROOT/skills/_shared/test-fragility.md`, so test authors see the never-fragile-test rules where they write tests.
   - **Offer** (never install) a pre-commit hook that runs `python3 "$TP_ROOT"/skills/_shared/fragility_lint.py check --base HEAD --cached`, so it lints what is staged, not unstaged edits. Present the hook command, explain what it does, and only wire it into the repo's pre-commit hook if the user confirms — consistent with the "don't silently install tools" rule.
   - **Offer (e)** — a repo hook that already runs the tests before every commit refuses the `Red:` commit of the red-then-green protocol. Run `python3 "$TP_ROOT"/skills/_shared/hook_detect.py --root .` and make the offer per `skills/_shared/consumer-offers.md` §Offer (e): test-running pre-commit hook — never wire it without the user's confirmed answer.

10. **Commit the artifacts** per `skills/_shared/commit-after-work.md`. Artifact paths to stage — include only those actually created or modified in steps 6–9b (run `git status --short` first and cross-check):
    - Test config files (e.g., `vitest.config.ts`, `pytest.ini`, `jest.config.js`, whatever was created)
    - Starter test file (path reported by step 6)
    - Package manifest and lockfile if test deps were added (e.g., `package.json`, `package-lock.json`, `pyproject.toml`, `poetry.lock`)
    - `.claude/settings.json` (if step 7 modified it)
    - `.gitignore` (if step 8 modified it)
    - `.three-pillars/config.json` (if step 6b recorded `test.command` / `test.runner` — the committed repo config, per `skills/_shared/repo-config.md`)
    - `.three-pillars/fragility-rules.json` (if step 6 scaffolded it)
    - The test README (if step 9b created or modified it)
    Do NOT stage `node_modules/`, `__pycache__/`, `.venv/`, or other build artifacts — those should already be gitignored.

    Commit message: `Setup: test infrastructure`.

## Rules
- **Never decide testing framework before architecture is documented.** If `three-pillars-docs/architecture.md` is missing, warn the user, recommend `/tp-docs-init`, and ask whether to proceed anyway — do not silently guess.
- Always let the user choose between options — don't silently install tools.
- Prefer the ecosystem's standard/default tooling over exotic alternatives unless the architecture demands otherwise (e.g., async frameworks, workspace monorepos).
- Don't modify existing test files — only create new starter files.
- If the project already has a fully working test setup that matches the architecture, say so and skip to verifying the Claude Code permission.
- The starter test file should be a real, passing test that demonstrates the pattern — not a placeholder that tests `1 + 1`.
- Tie test-runner and layout recommendations to specific lines in `architecture.md` when you can — "because architecture.md says X" is a stronger justification than "this is the default for the stack."
