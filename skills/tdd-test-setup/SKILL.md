---
name: tdd-test-setup
description: "Configure test infrastructure for the TDD pipeline, informed by the project's stated architecture. Runs after /tdd-docs-init so test-runner and layout choices are grounded in the documented system structure."
---

# Test Setup

Configure a project's test infrastructure so the TDD pipeline can run tests immediately — with choices informed by `docs/architecture.md` rather than guessed at before the architecture is documented.

**No arguments** — operates on the current repository, not a `[a-z0-9-]+` design directory.

## Sequencing

This skill deliberately runs **after** `/tdd-setup` (vision) and `/tdd-docs-init` (architecture, roadmap, known-issues):

1. `/tdd-setup` — the **why** into `docs/vision.md`.
2. `/tdd-docs-init` — the **how** into `docs/architecture.md`, plus roadmap and known-issues.
3. `/tdd-test-setup` — test infrastructure, informed by architecture (this skill).

The ordering matters: picking a test runner, layout, and coverage tool before the architecture is documented is premature. By the time this skill runs, `architecture.md` should describe the key components, language/runtime choices, and integration boundaries — all of which should shape the testing strategy.

## Prerequisites

- `docs/architecture.md` should exist. If it's missing, tell the user `/tdd-docs-init` is the recommended next step and ask whether they want to proceed anyway. Do not hard-block — a user who knows what they're doing may want to set up tests in parallel with architecture work. Just make sure they've made the call explicitly.

## Steps

1. **Read context**:
   - Read `docs/vision.md` per `skills/_shared/read-project-docs.md` — the vision's principles may constrain test choices (e.g., "no network calls in tests", "fast feedback is non-negotiable").
   - Read `docs/architecture.md` if it exists. Pay attention to: language/framework, key components, integration boundaries, async/concurrency model, data stores, external dependencies. These inform test tooling and layout.
   - Read `docs/known_issues.md` if it exists — flaky or slow test areas may already be documented.

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
   - Create a starter test file that demonstrates the project's test pattern. The starter should exercise a real piece of the system, not `1 + 1`. Prefer testing something mentioned in `architecture.md` (e.g., a key component's happy path) so the test itself demonstrates the vision-architecture-test chain.
   - Add or update test scripts in package manifest if applicable.

7. **Configure Claude Code permissions**:
   - Check `.claude/settings.json` for existing `Bash(...)` permissions.
   - Add the test command permission so the TDD pipeline can run tests without prompting (e.g., `"Bash(npm test:*)"`, `"Bash(pytest:*)"`).
   - Show the user what permission is being added and why.

8. **Ensure session artifacts are gitignored**:
   - Check the project's `.gitignore` for these patterns:
     ```
     docs/tdd-designs/*/handoff.md
     docs/tdd-designs/*/decisions.md
     ```
   - If missing, append them (with a `# three-pillars session artifacts` comment) and tell the user what was added and why (these files may contain sensitive session context and autonomous decision logs that should not enter version control).

9. **Verify**: Run the test suite once to confirm everything works.

## Rules
- **Never decide testing framework before architecture is documented.** If `docs/architecture.md` is missing, warn the user, recommend `/tdd-docs-init`, and ask whether to proceed anyway — do not silently guess.
- Always let the user choose between options — don't silently install tools.
- Prefer the ecosystem's standard/default tooling over exotic alternatives unless the architecture demands otherwise (e.g., async frameworks, workspace monorepos).
- Don't modify existing test files — only create new starter files.
- If the project already has a fully working test setup that matches the architecture, say so and skip to verifying the Claude Code permission.
- The starter test file should be a real, passing test that demonstrates the pattern — not a placeholder that tests `1 + 1`.
- Tie test-runner and layout recommendations to specific lines in `architecture.md` when you can — "because architecture.md says X" is a stronger justification than "this is the default for the stack."
