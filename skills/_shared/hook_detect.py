"""hook_detect: find pre-commit hooks in a repo that run tests.

Design red-commit-hook-refusal, Part 2. Stdlib only, never writes. The red-commit
gate needs to know whether the repo already has a test-running commit hook, so
this reports each such hook as `{"kind", "path", "wired"}` — `wired` says the
gate is already mentioned in one of the repo's commit hooks.

Usage:
    python3 hook_detect.py --root .
"""

import json
import os
import re
import subprocess
import sys

# The four hook hosts the framework meets, in report order.
GIT_HOOK = "git-hook"
PRE_COMMIT_FRAMEWORK = "pre-commit-framework"
HUSKY = "husky"
LEFTHOOK = "lefthook"

_PRE_COMMIT_FRAMEWORK_FILE = ".pre-commit-config.yaml"
_HUSKY_PRE_COMMIT = os.path.join(".husky", "pre-commit")
_HUSKY_COMMIT_MSG = os.path.join(".husky", "commit-msg")
_LEFTHOOK_FILES = ("lefthook.yml", "lefthook.yaml", ".lefthook.yml")

CONFIG_PATH = os.path.join(".three-pillars", "config.json")

# Test runners named as whole words anywhere in the hook text.
_TEST_WORDS = (
    "pytest",
    "py.test",
    "unittest",
    "tox",
    "nox",
    "vitest",
    "jest",
    "mocha",
    "rspec",
    "phpunit",
    "bats",
    "ctest",
)

# Runner commands that only read as test runs with their subcommand present.
_TEST_PHRASES = (
    r"go\s+test",
    r"cargo\s+test",
    r"cargo\s+nextest",
    r"npm\s+test",
    r"npm\s+run\s+test",
    r"yarn\s+test",
    r"pnpm\s+test",
    r"make\s+test",
    r"dotnet\s+test",
    r"gradle\b[^\n]*\btest",
    r"mvn\b[^\n]*\btest",
)

_TEST_RUN_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:%s)(?![A-Za-z0-9_-])" % "|".join(
        [re.escape(w) for w in _TEST_WORDS] + list(_TEST_PHRASES)
    )
)

_GATE_MARKER = "red_commit_gate"


def _read_text(path):
    """File text, or None when the path is missing or unreadable."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except (OSError, UnicodeError):
        return None


def _git(root, *args):
    res = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )
    if res.returncode != 0:
        return None
    return res.stdout.strip()


def _hooks_dir(root):
    """The hooks directory git would use (honours core.hooksPath, linked worktrees)."""
    out = _git(root, "rev-parse", "--git-path", "hooks")
    if not out:
        return None
    path = out if os.path.isabs(out) else os.path.join(str(root), out)
    return os.path.abspath(path)


def _recorded_test_command(root):
    """The repo's recorded `test.command`, verbatim; None when absent."""
    text = _read_text(os.path.join(str(root), CONFIG_PATH))
    if text is None:
        return None
    try:
        config = json.loads(text)
    except ValueError:
        return None
    test = config.get("test") if isinstance(config, dict) else None
    if isinstance(test, dict):
        command = test.get("command")
        if isinstance(command, str) and command.strip():
            return command
    return None


def _runs_tests(text, recorded):
    """True when the hook text names a test run (or the repo's own test command)."""
    if text is None:
        return False
    if _TEST_RUN_RE.search(text):
        return True
    return bool(recorded) and recorded in text


def _git_hook_path(hooks_dir):
    """The live `pre-commit` git hook path, or None (a `.sample` is never live)."""
    if not hooks_dir:
        return None
    path = os.path.join(hooks_dir, "pre-commit")
    if path.endswith(".sample") or not os.path.isfile(path):
        return None
    return path


def _candidates(root, hooks_dir):
    """(kind, path) pairs for every hook file this repo hosts."""
    out = []
    git_hook = _git_hook_path(hooks_dir)
    if git_hook:
        out.append((GIT_HOOK, git_hook))
    out.append((PRE_COMMIT_FRAMEWORK, os.path.join(str(root), _PRE_COMMIT_FRAMEWORK_FILE)))
    out.append((HUSKY, os.path.join(str(root), _HUSKY_PRE_COMMIT)))
    for name in _LEFTHOOK_FILES:
        out.append((LEFTHOOK, os.path.join(str(root), name)))
    return [(kind, path) for kind, path in out if os.path.isfile(path)]


def _wired(root, hooks_dir, hook_texts):
    """True when any commit hook in the repo already mentions the gate."""
    texts = list(hook_texts)
    extra = [os.path.join(str(root), _HUSKY_COMMIT_MSG)]
    if hooks_dir:
        extra.append(os.path.join(hooks_dir, "commit-msg"))
    for path in extra:
        texts.append(_read_text(path))
    return any(t is not None and _GATE_MARKER in t for t in texts)


def detect(root):
    """Every pre-commit hook under `root` that runs tests: `{"kind","path","wired"}`."""
    root = str(root)
    hooks_dir = _hooks_dir(root)
    recorded = _recorded_test_command(root)
    entries = []
    wired_sources = []
    for kind, path in _candidates(root, hooks_dir):
        text = _read_text(path)
        if text is None:
            continue  # an unreadable hook is skipped, never fatal
        if _GATE_MARKER in text:
            wired_sources.append(text)
        if _runs_tests(text, recorded):
            entries.append({"kind": kind, "path": path, "wired": False})
    wired = _wired(root, hooks_dir, wired_sources)
    for entry in entries:
        entry["wired"] = wired
    return entries


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = "."
    if "--root" in argv:
        idx = argv.index("--root")
        if idx + 1 < len(argv):
            root = argv[idx + 1]
    sys.stdout.write(json.dumps(detect(root), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
