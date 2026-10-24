#!/usr/bin/env python3
"""jdi_eligibility.py — is a just-do-it design eligible for the jdi tier?

`check(design_dir, base, head, repo=".") -> (rc, line)`:
  (0, "ELIGIBLE")            — under the cap, no excluded surface
  (1, "ESCALATE <reason>")   — cap exceeded, excluded surface, binary file
  (2, "ESCALATE bad-input: …") — malformed input; never treated as eligible

`route(design_dir, base, head, repo=".") -> (class, line | None)`: Tier 1
routing. The declared class is the floor — only a declared `just-do-it` runs
`check`, and an ineligible one (or bad input) is stamped up to `light`.

The cap and the exclusion tuples are IMPORTED from the shipped hot_patch_check
(never duplicated); the jdi lane adds only its own small surface tuple.
`three-pillars-docs/` paths are paper: exempt from the line sum, still checked
against the surfaces. `check` never raises. Stdlib only.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Import hot_patch_check as a sibling module (works standalone and under pytest).
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from hot_patch_check import DIFF_CAP, EXCLUDED_FILES, EXCLUDED_PREFIXES
except ImportError:  # a consumer repo without the shipped lane: escalate, never eligible
    DIFF_CAP = EXCLUDED_FILES = EXCLUDED_PREFIXES = None
    _IMPORT_ERROR = "hot_patch_check is not importable"
else:
    _IMPORT_ERROR = None

try:
    import weight_class
except ImportError:  # a consumer repo without the weight-class lane
    weight_class = None

# jdi-only surfaces on top of the hot-patch exclusions
JDI_EXCLUDED_PREFIXES = (".githooks/",)
JDI_EXCLUDED_FILES = frozenset({
    "skills/_shared/launch_design_run.py",
    "skills/_shared/github_pr_author.py",
})

PAPER_PREFIX = "three-pillars-docs/"
INLINE_MAX_FILES = 2
INLINE_MAX_LINES = 80
_GROWTH = re.compile(r"^\*\*Growth\*\*:\s*([+-]?\d+)", re.MULTILINE)
_SCOPE_BACKTICK = re.compile(r"`([^`\n]+)`")


def surface_hit(path: str) -> str | None:
    """Return a description of the excluded surface `path` hits, else None."""
    if _IMPORT_ERROR:
        return "unavailable"
    p = path.replace("\\", "/")
    for prefix in list(EXCLUDED_PREFIXES) + list(JDI_EXCLUDED_PREFIXES):
        if p.startswith(prefix):
            return f"touches protected prefix '{p}'"
    if p in EXCLUDED_FILES or p in JDI_EXCLUDED_FILES:
        return f"touches protected file '{p}'"
    return None


def scope_paths(design_dir: str) -> list[str]:
    """Backticked path spans in design.md's `## Scope`, up to `### Out of scope`.

    Raises ValueError when design.md is missing or has no `## Scope` heading.
    """
    md = Path(design_dir) / "design.md"
    if not md.is_file():
        raise ValueError(f"no design.md in '{design_dir}'")
    text = md.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == "## Scope":
            start = i + 1
            break
    if start is None:
        raise ValueError(f"design.md in '{design_dir}' has no '## Scope' heading")
    body: list[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("### Out of scope"):
            break
        body.append(line)
    return _SCOPE_BACKTICK.findall("\n".join(body))


def _git(args: list[str], repo: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo] + args,
                          capture_output=True, text=True)


def _resolve(ref: str, repo: str) -> str | None:
    r = _git(["rev-parse", "--verify", "--quiet", ref], repo)
    return r.stdout.strip() if r.returncode == 0 else None


def _numstat(base: str, head: str, repo: str) -> list[tuple[int | None, int | None, str]]:
    """(added, deleted, path) rows for `base...head`; None counts mean binary."""
    out = _git(["diff", "--numstat", "--no-renames", "-z", f"{base}...{head}"], repo)
    if out.returncode != 0:  # a diff we could not observe is never ELIGIBLE
        raise ValueError(f"git diff {base}...{head} failed: {out.stderr.strip()}")
    rows: list[tuple[int | None, int | None, str]] = []
    for record in out.stdout.split("\0"):
        if not record:
            continue
        parts = record.split("\t", 2)
        if len(parts) < 3:
            continue
        added_s, deleted_s, path = parts
        if added_s == "-" or deleted_s == "-":
            rows.append((None, None, path))
        else:
            try:
                rows.append((int(added_s), int(deleted_s), path))
            except ValueError:
                rows.append((None, None, path))
    return rows


def check(design_dir: str, base: str, head: str, repo: str = ".") -> tuple[int, str]:
    """Eligibility verdict for a jdi run: (rc, line) — see the module docstring."""
    try:
        return _check(design_dir, base, head, repo)
    except Exception as exc:  # noqa: BLE001 — never raises to the caller
        return 2, f"ESCALATE bad-input: {exc}"


def _check(design_dir: str, base: str, head: str, repo: str) -> tuple[int, str]:
    if _IMPORT_ERROR:
        return 2, f"ESCALATE bad-input: {_IMPORT_ERROR}"
    if not Path(design_dir).is_dir():
        return 2, f"ESCALATE bad-input: no design dir '{design_dir}'"
    try:
        scoped = scope_paths(design_dir)
    except ValueError as exc:
        return 2, f"ESCALATE bad-input: {exc}"
    base_sha, head_sha = _resolve(base, repo), _resolve(head, repo)
    if base_sha is None or head_sha is None:
        missing = base if base_sha is None else head
        return 2, f"ESCALATE bad-input: cannot resolve '{missing}' in '{repo}'"

    rows = _numstat(base_sha, head_sha, repo)
    # surfaces first: on every diff path, then on the declared Scope paths
    for _, _, path in rows:
        hit = surface_hit(path)
        if hit:
            return 1, f"ESCALATE surface: {hit}"
    for path in scoped:
        hit = surface_hit(path)
        if hit:
            return 1, f"ESCALATE surface: Scope names {hit}"

    total = 0
    for added, deleted, path in rows:
        if added is None or deleted is None:
            return 1, (f"ESCALATE binary: '{path.replace(chr(92), '/')}' — "
                       "binary files are not eligible for a just-do-it run")
        if path.replace("\\", "/").startswith(PAPER_PREFIX):
            continue  # paper never eats the fix budget
        total += added + deleted
    if total > DIFF_CAP:
        return 1, f"ESCALATE diff-cap: {total} changed lines exceeds cap of {DIFF_CAP}"
    return 0, "ELIGIBLE"


def inline_fit(plan_path: str) -> bool:
    """True when the plan fits the inline bound (files and lines); never raises."""
    try:
        import task_scope

        tasks = task_scope.plan_tasks(Path(plan_path).read_text(encoding="utf-8"))
        if not tasks:
            return False
        files: set[str] = set()
        lines = 0
        for t in tasks:
            paths, unparsed = task_scope.parse_files(t.get("fields", {}).get("File", ""))
            if unparsed:
                return False
            files.update(p for p in paths if not p.startswith(PAPER_PREFIX))
            m = _GROWTH.search(t.get("raw", ""))
            lines += abs(int(m.group(1))) if m else 50
        return len(files) <= INLINE_MAX_FILES and lines <= INLINE_MAX_LINES
    except Exception:  # noqa: BLE001 — an unreadable plan never fits
        return False


def route(design_dir: str, base: str, head: str,
          repo: str = ".", plan: str | None = None) -> tuple[str, str | None]:
    """Tier 1 routing: the class the run routes as, plus the escalation line.

    The declared class is the floor — a run never routes lighter than declared,
    so only a declared `just-do-it` pays for `check`. An ineligible jdi run (or
    bad input) is stamped up to `light` and returns that stamp's log line.
    Raises ValueError on bad input (a missing design dir, a stamp that failed).
    """
    if weight_class is None:
        raise ValueError("weight_class is not importable")
    d = Path(design_dir)
    if not d.is_dir():
        raise ValueError(f"no design dir '{design_dir}'")
    declared, _ = weight_class.read_class(d)
    if declared != "just-do-it":
        return declared, None
    rc, line = check(str(d), base, head, repo=repo)
    if rc == 0:
        if plan and inline_fit(plan):
            return "inline", None
        return "just-do-it", None
    reason = line.removeprefix("ESCALATE ").strip()
    try:
        log = weight_class.escalate(d, reason, to="light")
    except Exception as exc:  # noqa: BLE001 — a failed stamp is bad input
        raise ValueError(f"escalation to light failed: {exc}") from exc
    return "light", log


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jdi_eligibility.py",
        description="Is a just-do-it design eligible for the jdi tier?",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="Print ELIGIBLE / ESCALATE <reason>, exit 0/1/2")
    c.add_argument("--design-dir", metavar="DIR", required=True,
                   help="Design directory holding design.md (its `## Scope` is checked)")
    c.add_argument("--base", metavar="REF", required=True,
                   help="Base commit of the implementation diff")
    c.add_argument("--head", metavar="REF", required=True,
                   help="Head commit of the implementation diff")
    c.add_argument("--repo", metavar="DIR", default=".",
                   help="Repository to run git in (default: the current directory)")
    r = sub.add_parser("route",
                       help="Print 'route: <class>' (+ escalation line), exit 0/2")
    r.add_argument("--design-dir", metavar="DIR", required=True,
                   help="Design directory holding design.md (its class is the floor)")
    r.add_argument("--base", metavar="REF", required=True,
                   help="Base commit of the implementation diff")
    r.add_argument("--head", metavar="REF", required=True,
                   help="Head commit of the implementation diff")
    r.add_argument("--repo", metavar="DIR", default=".",
                   help="Repository to run git in (default: the current directory)")
    r.add_argument("--plan", metavar="FILE", default=None,
                   help="plan.md; a just-do-it design whose plan fits routes `inline`")
    return p


def main(argv: list[str] | None = None) -> int:
    """Run `check` or `route`; print its line(s) and return the rc (0 / 1 / 2)."""
    args = _build_parser().parse_args(argv)
    if args.cmd == "route":
        try:
            klass, log = route(args.design_dir, args.base, args.head,
                               repo=args.repo, plan=args.plan)
        except Exception as exc:  # noqa: BLE001 — bad input, never a jdi route
            print(f"ESCALATE bad-input: {exc}")
            return 2
        print(f"route: {klass}")
        if log:
            print(log)
        return 0
    rc, line = check(args.design_dir, args.base, args.head, repo=args.repo)
    print(line)
    return rc


if __name__ == "__main__":
    sys.exit(main())
