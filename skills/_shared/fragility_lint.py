#!/usr/bin/env python3
"""fragility_lint.py — the test-fragility lint: pure core, waivers and `scan`.

design: fragile-test-prevention (detailed-design-lint §Shape, §Waivers, §Scoping)

Follows `fail_open_lint.py`'s shape without importing it: a pathlib/os walk, one line
per hit, an inline waiver, and exit 2 on anything the lint cannot judge. It never edits
code. The AST rules live in `fragility_rules_gating` and `fragility_rules_flag` (a flag
rule never gates unless the gating set names it); this module owns the waiver lookup,
the walk, the output and the exit codes.

Waiver: `# tp-allow-fragile: <reason>` as a `tokenize` COMMENT token on any line of the
hit's enclosing statement (a compound statement's own header only), or standing alone on
the line directly above it. A hit keeps its gating flag whatever the waiver says;
`Hit.waiver_reason` is None (no waiver), "" (an empty reason: does not silence the hit,
printed `[waiver-empty]`) or the reason (printed `[waived: <reason>]`, never blocking).

CLI: `scan <paths...> [--json] [--rules FILE]` prints one `path:line: <rule-id>
[gating|flag] <message>` line per hit and exits 0; an unreadable or unparseable `.py` file
(or a missing path) prints `could-not-evaluate: <path>: <why>` and exits 2. A code file it
cannot judge prints `skipped (non-python): <path>`; non-code files are not listed. `--rules`
(default `fragility_repo_rules.RULES_PATH` under the cwd, or the repo top for `check`) adds
the per-repo rules; a broken file is could-not-evaluate, and `--json` counts `repo_rules`.

`check --base REF [--head REF | --cached] [--json]` lints the `--diff-filter=AM` files of
the diff and keeps only the hits on the lines it adds (`fragility_diff.added_lines`), so
existing code never blocks. `--head` lints `git show <head>:<path>`, `--cached` the index
blob, neither the working file. Exit 1 on a gating hit no waiver silences, else 2 if the
diff or a `.py` file could not be judged, else 0. `check_diff` is the in-process form.
stdlib-only.
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Callable, Iterable, Iterator, NamedTuple

from fragility_diff import DiffUnavailable, added_lines
from fragility_registry import RULES, ConfigError, gating_set
from fragility_repo_rules import NO_RULES, RepoRules, load as load_rules, visit as visit_repo
from fragility_rules_flag import repo_gating, visit as visit_flag
from fragility_rules_gating import visit as visit_gating

SUMMARIES = {rule.id: rule.summary for rule in RULES}
_REPO = "a per-repo rule (its reason is in the rules file)"
CODE_SUFFIXES = frozenset(
    ".js .ts .tsx .jsx .go .rs .java .kt .rb .sh .c .cc .cpp .h .cs .swift .php".split())
_SKIP_DIRS = frozenset({".git", "__pycache__", "node_modules"})
_RETIRED_DIR = ("three-pillars-docs", "completed-tp-designs")
_WAIVER = re.compile(r"#\s*tp-allow-fragile:(.*)", re.DOTALL)
_UNJUDGEABLE = (OSError, ValueError, SyntaxError, RecursionError, tokenize.TokenError)


class Hit(NamedTuple):
    path: str
    line: int
    rule_id: str
    gating: bool
    waiver_reason: str | None = None
    reason: str | None = None

    @property
    def waived(self) -> bool:
        """A waiver with a reason. An empty reason waives nothing."""
        return bool(self.waiver_reason)


class LintResult(NamedTuple):
    exit: int
    hits: list[Hit]
    skipped: list[str]
    could_not_evaluate: list[str]
    judge_dimension_required: bool
    repo_rules: int = 0


# --- the pure core -------------------------------------------------------------

def _waivers(text: str) -> dict[int, tuple[str, bool]]:
    """line -> (reason, stands alone on its line) for each waiver COMMENT token."""
    found: dict[int, tuple[str, bool]] = {}
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        match = _WAIVER.match(tok.string) if tok.type == tokenize.COMMENT else None
        if match:
            found[tok.start[0]] = (match.group(1).strip(), tok.line.strip().startswith("#"))
    return found


def _spans(tree: ast.AST) -> list[tuple[int, int]]:
    """The (first, last) line of every statement; a compound statement ends before its body."""
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt):
            body = getattr(node, "body", None)
            last = max(node.lineno, body[0].lineno - 1) if isinstance(body, list) and body \
                else node.end_lineno
            spans.append((node.lineno, last))
    return spans


def _waiver_for(waivers: dict, spans: list, line: int, end_line: int) -> str | None:
    """The waiver reason for a hit spanning `line..end_line`: found on the innermost
    enclosing statement's lines, or standing alone directly above it. None if there is none."""
    enclosing = [s for s in spans if s[0] <= line and end_line <= s[1]]
    first, last = min(enclosing, key=lambda s: s[1] - s[0], default=(line, end_line))
    reasons = [waivers[n][0] for n in range(first - 1, last + 1)
               if n in waivers and (n >= first or waivers[n][1])]
    return next((r for r in reasons if r), reasons[0] if reasons else None)


def lint_source(path: str, text: str, rules: Iterable[str] | None = None,
                repo: list = ()) -> list[Hit]:
    """The hits of one module. `rules` is the gating set (default: the registry's); each
    per-repo rule of `repo` gates by its own flag. Raises on text that does not parse."""
    gating = {*(gating_set(None) if rules is None else rules), *(r.id for r in repo if r.gating)}
    reasons = {r.id: r.reason for r in repo}
    tree = ast.parse(text, filename=path)
    waivers, spans = _waivers(text), _spans(tree)
    return [Hit(path, f.line, f.rule_id, f.rule_id in gating,
                _waiver_for(waivers, spans, f.line, f.end_line), reasons.get(f.rule_id))
            for f in sorted([*visit_gating(tree, path), *visit_flag(tree, path),
                             *visit_repo(tree, path, repo)], key=lambda found: found.line)]


# --- the walk ----------------------------------------------------------------------

def _skip_dir(directory: Path) -> bool:
    return (directory.name in _SKIP_DIRS or (directory / "pyvenv.cfg").is_file()
            or directory.parts[-2:] == _RETIRED_DIR)


def _walk(arg: str) -> Iterator[Path]:
    """`arg` if it is a file, else every file under it, skipping uninteresting dirs."""
    root = Path(arg)
    if root.is_file():
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _skip_dir(Path(dirpath, d)))
        yield from (Path(dirpath, name) for name in sorted(filenames))


class _Run:
    """Collects one lint run: hits, skipped code files and could-not-evaluate lines."""

    def __init__(self, rules: Iterable[str] | None, repo: RepoRules = NO_RULES):
        self.rules = None if rules is None else list(rules)
        self.repo, self.cannot = list(repo.rules), list(repo.errors)
        self.hits: list[Hit] = []
        self.skipped: list[str] = []

    def add(self, name: str, load: Callable[[], str]) -> None:
        suffix = Path(name).suffix
        if suffix in CODE_SUFFIXES:
            self.skipped.append(name)
        elif suffix == ".py":
            try:
                self.hits += lint_source(name, load(), self.rules, self.repo)
            except _UNJUDGEABLE as exc:
                self.cannot.append(f"{name}: {' '.join(str(exc).split())}")

    def result(self, exit_code: int) -> LintResult:
        # `skipped` holds only code files, so any entry makes the judge dimension required.
        return LintResult(exit_code, self.hits, self.skipped, self.cannot, bool(self.skipped),
                          len(self.repo))


def scan(paths: Iterable[str], rules: Iterable[str] | None = None,
         repo: RepoRules = NO_RULES) -> LintResult:
    """Every hit under `paths`; exit 2 if a path, `.py` file or `repo` is unjudged, else 0."""
    run = _Run(rules, repo)
    for arg in paths:
        if not Path(arg).exists():
            run.cannot.append(f"{arg}: no such file or directory")
        for path in _walk(arg):
            run.add(path.as_posix(), lambda p=path: p.read_text(encoding="utf-8"))
    return run.result(2 if run.cannot else 0)


# --- check: the lint gated on a diff's added lines ---------------------------------------

class CheckResult(LintResult):
    """What `check_diff` returns: a `LintResult` whose hits are all on added lines."""
    __slots__ = ()


def _git(root: str | Path, *args: str) -> bytes:
    try:
        done = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    except OSError as exc:
        raise DiffUnavailable(f"could not run git in {root}: {exc}") from exc
    if done.returncode != 0:
        why = done.stderr.decode("utf-8", "replace").strip() or f"exit {done.returncode}"
        raise DiffUnavailable(f"git {args[0]} failed: {why}")
    return done.stdout


_SYMLINK_MODE = "120000"


def _diff_files(root: str | Path, base: str, head: str | None, cached: bool) -> list[str]:
    """The `--diff-filter=AM` file set of the diff. `--no-renames` lists a rename's new path
    as added, so a renamed file is linted on the lines the rename changes. A symlink (new
    mode 120000) is not source in any mode: its blob is the link target's path, and the
    file it points at is linted under its own name."""
    spec = ["--cached", base] if cached else [f"{base}...{head}" if head else base]
    out = _git(root, "diff", "--raw", "-z", "--diff-filter=AM", "--no-renames",
               "--no-ext-diff", *spec, "--")
    fields = out.decode("utf-8", "replace").split("\0")
    return sorted(name for meta, name in zip(fields[0::2], fields[1::2])
                  if name and meta.split()[1:2] != [_SYMLINK_MODE])


def _loader(top: Path, name: str, head: str | None, cached: bool) -> Callable[[], str]:
    """A commit's text is `git show <head>:<path>`, the index's is `git show :<path>`, and
    with neither it is the working file: a dirty worktree never changes a commit's verdict."""
    def load() -> str:
        if head is None and not cached:
            return (top / name).read_text(encoding="utf-8")
        try:
            return _git(top, "show", f"{head or ''}:{name}").decode("utf-8")
        except DiffUnavailable as exc:
            raise OSError(str(exc)) from exc
    return load


def check_diff(root: str | Path, base: str, head: str | None = None, *,
               cached: bool = False, rules_file: str | Path | None = None) -> CheckResult:
    """The hits a diff adds. Exit 1 on a gating hit no waiver silences, else 2 if the diff, a
    `.py` file or the per-repo `rules_file` could not be judged, else 0."""
    run = _Run(None)
    try:
        added = added_lines(root, base, head, cached=cached)
        top = Path(_git(root, "rev-parse", "--show-toplevel").decode("utf-8", "replace").strip())
        names = _diff_files(top, base, head, cached)
        run = _Run(repo_gating(top), load_rules(top, rules_file))
    except (DiffUnavailable, ConfigError) as exc:
        run.cannot.append(f"<diff>: {exc}")
    if run.cannot:
        return CheckResult(*run.result(2))
    for name in names:
        kept = len(run.hits)
        run.add(name, _loader(top, name, head, cached))
        run.hits[kept:] = [h for h in run.hits[kept:] if h.line in added.get(name, ())]
    blocked = any(h.gating and not h.waived for h in run.hits)
    return CheckResult(*run.result(1 if blocked else 2 if run.cannot else 0))


# --- output ------------------------------------------------------------------------

def render(hit: Hit) -> str:
    """`path:line: <rule-id> [gating|flag] <message>`, plus the waiver tag if any."""
    flag = "gating" if hit.gating else "flag"
    message = SUMMARIES.get(hit.rule_id) or hit.reason or _REPO
    line = f"{hit.path}:{hit.line}: {hit.rule_id} [{flag}] {message}"
    if hit.waived:
        return f"{line} [waived: {hit.waiver_reason}]"
    return f"{line} [waiver-empty]" if hit.waiver_reason == "" else line


def emit(result: LintResult, as_json: bool) -> None:
    if as_json:
        hits = [{"path": h.path, "line": h.line, "rule": h.rule_id, "gating": h.gating,
                 "waiver": h.waiver_reason,
                 "source": "generic" if h.rule_id in SUMMARIES else "repo"} for h in result.hits]
        print(json.dumps({"hits": hits, "skipped": result.skipped,
                          "could_not_evaluate": result.could_not_evaluate,
                          "judge_dimension_required": result.judge_dimension_required,
                          "exit": result.exit, "repo_rules": result.repo_rules}, indent=2))
        return
    for hit in result.hits:
        print(render(hit))
    for path in result.skipped:
        print(f"skipped (non-python): {path}")
    for line in result.could_not_evaluate:
        print(f"could-not-evaluate: {line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fragility_lint.py",
                                     description="Test-fragility lint (never edits code).")
    commands = parser.add_subparsers(dest="command", required=True)
    scan_cmd = commands.add_parser("scan", help="report every hit under the paths (exit 0 or 2)")
    scan_cmd.add_argument("paths", nargs="+")
    check_cmd = commands.add_parser(
        "check", help="lint the added lines of a diff (exit 1 on a gating hit, 2 if unjudged)")
    check_cmd.add_argument("--base", required=True, help="the ref the diff starts from")
    where = check_cmd.add_mutually_exclusive_group()
    where.add_argument("--head", help="lint the text committed at this ref")
    where.add_argument("--cached", action="store_true", help="lint the staged text")
    for cmd in (scan_cmd, check_cmd):
        cmd.add_argument("--json", action="store_true", help="print a JSON document")
        cmd.add_argument("--rules", type=Path, help="per-repo rules file (default: the root's)")
    args = parser.parse_args(argv)
    result = (scan(args.paths, repo=load_rules(".", args.rules)) if args.command == "scan" else
              check_diff(".", args.base, args.head, cached=args.cached, rules_file=args.rules))
    emit(result, args.json)
    return result.exit


if __name__ == "__main__":
    sys.exit(main())
