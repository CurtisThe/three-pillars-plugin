---
name: tdd-setup
description: "Conversational project testing setup. Analyzes language, framework, and existing infrastructure, then configures test tools so the TDD pipeline can run immediately."
---

# Setup

Configure a project's test infrastructure so the TDD pipeline can run tests immediately.

**No arguments** — operates on the current repository, not a `[a-z0-9-]+` design directory.

## Steps

1. **Analyze the project**:
   - Detect language(s) and framework(s) from source files, package manifests (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Gemfile`, etc.)
   - Check for existing test infrastructure: test directories, test config files, test scripts in package manifests
   - Check for existing test files and their patterns
   - Read `docs/architecture.md` if it exists for additional context

2. **Present findings**:
   - Language/framework detected
   - Existing test infrastructure (if any)
   - What's missing or needs configuration

3. **If test infrastructure already exists**, confirm it works:
   - Try running the existing test command
   - If tests pass, report success and check that `.claude/settings.json` has the right `Bash(...)` permission for the TDD pipeline
   - If tests fail, diagnose and offer to fix

4. **If no test infrastructure exists**, propose a setup:
   - **Test runner**: Recommend the standard choice for the detected stack (e.g., vitest for modern JS/TS, pytest for Python, go test for Go, cargo test for Rust)
   - **Directory layout**: Recommend the conventional layout (e.g., `__tests__/`, `tests/`, `test/`, colocated `*.test.*`)
   - **Coverage**: Recommend if available for the stack (e.g., c8/v8 for JS, coverage.py for Python)
   - Present options and let the user choose — don't assume

5. **On confirmation, configure**:
   - Install dependencies (e.g., `npm install -D vitest`, `pip install pytest`)
   - Create config files if needed (e.g., `vitest.config.ts`, `pytest.ini`)
   - Create a starter test file that demonstrates the project's test pattern
   - Add or update test scripts in package manifest if applicable

6. **Configure Claude Code permissions**:
   - Check `.claude/settings.json` for existing `Bash(...)` permissions
   - Add the test command permission so the TDD pipeline can run tests without prompting (e.g., `"Bash(npm test:*)"`, `"Bash(pytest:*)"`)
   - Show the user what permission is being added and why

7. **Ensure session artifacts are gitignored**:
   - Check the project's `.gitignore` for these patterns:
     ```
     docs/tdd-designs/*/handoff.md
     docs/tdd-designs/*/decisions.md
     ```
   - If missing, append them (with a `# three-pillars session artifacts` comment) and tell the user what was added and why (these files may contain sensitive session context and autonomous decision logs that should not enter version control)

8. **Verify**: Run the test suite once to confirm everything works.

## Rules
- Always let the user choose between options — don't silently install tools.
- Prefer the ecosystem's standard/default tooling over exotic alternatives.
- Don't modify existing test files — only create new starter files.
- If the project already has a fully working test setup, say so and skip to verifying the Claude Code permission.
- The starter test file should be a real, passing test that demonstrates the pattern — not a placeholder that tests `1 + 1`.
- Keep the starter test relevant to the actual project (e.g., test an existing utility function, test an API route returns 200).
