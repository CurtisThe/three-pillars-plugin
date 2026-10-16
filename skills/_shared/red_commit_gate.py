"""red_commit_gate: pure gate deciding whether a `Red:` commit is really red.

Design red-commit-hook-refusal, Part 1. Stdlib only, no subprocess: the CLI
(`red_commit_gate_cli.py`) owns the git/test-command calls; everything here is
a pure function of its arguments so the rules are testable in isolation.
"""

import fnmatch
import os
import re

# A `Red:` subject must be followed by whitespace, so `Red:design 1.2` is not red.
_RED_SUBJECT = re.compile(r"^Red:\s")

# Basenames that identify a test file across the ecosystems the framework uses.
_TEST_BASENAME_GLOBS = (
    "test_*.py",
    "*_test.py",
    "*_test.go",
    "*.test.js",
    "*.test.jsx",
    "*.test.ts",
    "*.test.tsx",
    "*.test.mjs",
    "*.spec.js",
    "*.spec.jsx",
    "*.spec.ts",
    "*.spec.tsx",
    "*.spec.mjs",
    "*Test.java",
    "*_spec.rb",
    "*_test.rb",
)

# Directory names that make any file under them test-side.
_TEST_DIR_NAMES = frozenset({"test", "tests", "__tests__", "spec"})

# Failure markers. Case-sensitive whole words, plus the two cross-glyph marks.
_FAIL_WORDS = ("FAIL", "FAILED", "ERROR", "not ok")
_FAIL_WORD_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:" + "|".join(re.escape(w) for w in _FAIL_WORDS) + r")(?![A-Za-z0-9_])"
)
_FAIL_GLYPHS = ("✗", "✖")

# First token on a line shaped like a path.
_PATH_TOKEN_RE = re.compile(r"[\w.@+/-]+\.\w+")
_NODE_SUFFIX_RE = re.compile(r"::.*$")
_LINE_SUFFIX_RE = re.compile(r":\d+(?::\d+)?(?:\s|$).*$")


def is_red(message):
    """True when the first non-blank, non-comment line starts with `Red: `."""
    for line in (message or "").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        return bool(_RED_SUBJECT.match(line))
    return False


def is_test_path(path, extra_globs=()):
    """True when `path` names (or sits among) test files."""
    name = os.path.basename(path)
    for glob in _TEST_BASENAME_GLOBS:
        if fnmatch.fnmatch(name, glob):
            return True
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    if any(part in _TEST_DIR_NAMES for part in parts[:-1]) or (
        parts and parts[-1] in _TEST_DIR_NAMES
    ):
        return True
    for glob in extra_globs or ():
        if fnmatch.fnmatch(path, glob) or fnmatch.fnmatch(name, glob):
            return True
    return False


def _has_marker(line):
    if _FAIL_WORD_RE.search(line):
        return True
    return any(g in line for g in _FAIL_GLYPHS)


def _clean_token(token, top):
    """Strip node/line suffixes and relativise against `top`; None if unusable."""
    token = _NODE_SUFFIX_RE.sub("", token)
    token = _LINE_SUFFIX_RE.sub("", token)
    if not token or token.startswith("http"):
        return None
    if top and token.startswith(top.rstrip("/") + "/"):
        token = token[len(top.rstrip("/")) + 1 :]
    return token


def _first_path_token(line, top):
    """First whitespace token on `line` that is shaped like a path."""
    for raw in line.split():
        if raw.startswith("http"):
            continue
        cand = _clean_token(raw, top)
        if cand and _PATH_TOKEN_RE.fullmatch(cand):
            return cand
    return None


def failing_paths(output, top=None):
    """Paths of failing test files named on marker lines of `output`."""
    found = set()
    for line in (output or "").splitlines():
        if not _has_marker(line):
            continue
        token = _first_path_token(line, top)
        if token is None:
            continue
        if "/" in token or is_test_path(token):
            found.add(token)
    return found


def _exit_code_verdict(exit_code):
    if exit_code == 0:
        return {"status": "pass", "reason": ""}
    return {"status": "refuse", "reason": "tests failed"}


def decide(message, staged, exit_code, output, extra_globs=(), top=None):
    """Gate verdict for one commit: `{"status", "reason"}`."""
    staged = list(staged or ())
    if not is_red(message):
        return _exit_code_verdict(exit_code)
    if not staged or any(not is_test_path(p, extra_globs) for p in staged):
        # The bare `Red:` prefix buys nothing without an all-test staging.
        return _exit_code_verdict(exit_code)
    if exit_code == 0:
        return {"status": "refuse", "reason": "red-not-red: tests pass on a Red: commit"}
    fails = failing_paths(output, top)
    if not fails:
        return {"status": "refuse", "reason": "no failing test file found in the output"}
    outside = sorted(fails - set(staged))
    if outside:
        return {
            "status": "refuse",
            "reason": "failures outside the staged test files: " + ", ".join(outside),
        }
    return {"status": "pass", "reason": ""}
