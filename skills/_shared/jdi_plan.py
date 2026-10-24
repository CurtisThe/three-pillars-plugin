#!/usr/bin/env python3
"""jdi_plan.py — the mechanical one-task plan.md for a just-do-it run.

`write --design-dir <d> [--repo .]` renders plan.md from design.md with zero
tokens: frontmatter `weight-class: just-do-it` + `plan-schema: 2`, one Phase 1
holding one Task 1.1 whose **File** is the design's `## Scope` paths (via
`jdi_eligibility.scope_paths`, `(modify)` when the path exists under `repo`),
whose **Targets** are the Scope `test_*.py` paths (`none` when there are none),
and whose Test/Red/Green prose is design.md's `## Behaviors` / `## Done when`.

`write` is idempotent and resume-safe: it writes only when the bytes differ and
never overwrites a plan.md that carries a `**Status**:` line or declares a class
other than `just-do-it` (that plan belongs to a real phase, or to a heavier run).
Bad input (no design.md, no `## Scope`) prints `jdi-plan: bad-input …` and exits 2
with nothing written. Stdlib only.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jdi_eligibility  # noqa: E402
import weight_class  # noqa: E402

STATUS_PREFIX = "**Status**:"
_TEST_BASENAME = re.compile(r"test_[^/]*\.py\Z")


class BadInput(Exception):
    """design.md is missing, unreadable, or has no `## Scope`."""


def _heading_body(text: str, heading: str) -> str:
    """The trimmed body under `## <heading>`, up to the next `##`/`###` heading."""
    lines = text.splitlines()
    out: list[str] = []
    seen = False
    for line in lines:
        if seen:
            if line.startswith("## ") or line.startswith("### "):
                break
            out.append(line)
        elif line.strip() == f"## {heading}":
            seen = True
    return "\n".join(out).strip()


def _design_text(design_dir: Path) -> str:
    md = design_dir / "design.md"
    if not md.is_file():
        raise BadInput(f"no design.md in '{design_dir}'")
    try:
        return md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise BadInput(f"cannot read '{md}': {exc}") from exc


def render(design_dir: str, repo: str = ".") -> str:
    """The one-task plan.md text for a just-do-it design. Raises ValueError."""
    d = Path(design_dir)
    text = _design_text(d)
    try:
        scoped = jdi_eligibility.scope_paths(str(d))
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if not scoped:
        raise ValueError(f"'## Scope' in '{d}' names no backticked path")
    klass = weight_class.parse_frontmatter(text).get("weight-class", "just-do-it")
    slug = weight_class.parse_frontmatter(text).get("slug") or d.name
    groups = _pack(scoped, _max_files(repo))
    est = str(weight_class.parse_frontmatter(text).get("estimated-lines", "")).strip()
    behaviors = _heading_body(text, "Behaviors") or "See design.md `## Behaviors`."
    done = _heading_body(text, "Done when") or "The targets pass."
    beh = behaviors.replace("\n", " ").strip()
    dn = done.replace("\n", " ").strip()
    tasks = "".join(
        _task(i, paths, repo, beh, dn, est if i == 1 else "")
        for i, paths in enumerate(groups, 1))
    return (
        "---\n"
        f"weight-class: {klass}\n"
        "plan-schema: 2\n"
        "---\n\n"
        f"# {slug} — Implementation Plan\n\n"
        "Mechanical plan rendered by `jdi_plan.py write` from design.md.\n\n"
        "## Phase 1: Implementation\n\n" + tasks
    )


def _max_files(repo: str) -> int:
    import task_eligibility
    try:
        return task_eligibility.configured_max_files(Path(repo))
    except ValueError:
        return 10 ** 6


def _pack(scoped: list[str], cap: int) -> list[list[str]]:
    """Scope paths -> task path lists: one task when it fits, else code+test
    groups packed first-fit into tasks of at most `cap` paths."""
    if len(scoped) <= cap:
        return [list(scoped)]
    tests = [p for p in scoped if _TEST_BASENAME.match(p.split("/")[-1])]
    used: set[str] = set()
    groups: list[list[str]] = []
    for p in scoped:
        if p in tests:
            continue
        head, _, base = p.rpartition("/")
        mate = f"{head}/test_{base}" if head else f"test_{base}"
        grp = [p] + ([mate] if mate in tests else [])
        used.update(grp)
        groups.append(grp)
    groups += [[p] for p in tests if p not in used]
    tasks: list[list[str]] = []
    for g in groups:
        for t in tasks:
            # a test-less group never shares a task with a tested one
            same = any(_TEST_BASENAME.match(x.split("/")[-1]) for x in t) == any(
                _TEST_BASENAME.match(x.split("/")[-1]) for x in g)
            if same and len(t) + len(g) <= cap:
                t.extend(g)
                break
        else:
            tasks.append(list(g))
    return tasks


def _task(n: int, paths: list[str], repo: str, beh: str, dn: str, est: str) -> str:
    file_items = ", ".join(
        f"`{p}` ({'modify' if (Path(repo) / p).is_file() else 'new'})" for p in paths)
    tests = [p for p in paths if _TEST_BASENAME.match(p.split("/")[-1])]
    targets = ", ".join(f"`{p}`" for p in tests) if tests else "none"
    # Entry point `none` is valid only when Targets is `none` (task_oracle.validate_pair)
    non_test = [p for p in paths if p not in tests]
    entry = f"`{(non_test or paths)[0]}`" if tests else "none"
    growth = f"**Growth**: +{est}\n" if est.isdigit() else ""
    return (
        f"### Task 1.{n}: Implement the design's Scope\n"
        f"**File**: {file_items}\n"
        f"**Test**: {beh}\n"
        f"**Targets**: {targets}\n"
        + growth +
        "**Oracle**: example\n"
        f"**Entry point**: {entry}\n"
        f"**Red**: {beh}\n"
        f"**Green**: {dn}\n"
        "**Refactor**: None expected.\n"
        f"**Done when**: {dn}\n\n"
    ).rstrip("\n") + "\n" + ("\n" if n else "")


def _resumed(plan_md: Path) -> bool:
    """True when plan.md belongs to a phase or a heavier run — never rewritten."""
    try:
        text = plan_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return True
    if STATUS_PREFIX in text:
        return True
    return weight_class.parse_frontmatter(text).get("weight-class") != "just-do-it"


def write(design_dir: str, repo: str = ".") -> tuple[int, str]:
    """Render and write plan.md when that is safe → (rc, line)."""
    d = Path(design_dir)
    try:
        text = render(str(d), repo)
    except (ValueError, BadInput) as exc:
        return 2, f"jdi-plan: bad-input {exc}"
    plan_md = d / "plan.md"
    if plan_md.is_file() and _resumed(plan_md):
        return 0, f"jdi-plan: unchanged {plan_md} (resumed or heavier plan)"
    data = text.encode("utf-8")
    if plan_md.is_file() and plan_md.read_bytes() == data:
        return 0, f"jdi-plan: unchanged {plan_md}"
    plan_md.write_bytes(data)
    return 0, f"jdi-plan: wrote {plan_md}"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jdi_plan.py",
                                description="Mechanical one-task plan.md for jdi runs")
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="Render plan.md from design.md (idempotent)")
    w.add_argument("--design-dir", metavar="DIR", required=True,
                   help="Design directory holding design.md")
    w.add_argument("--repo", metavar="DIR", default=".",
                   help="Repo the File paths are judged against (default: cwd)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rc, line = write(args.design_dir, repo=args.repo)
    print(line)
    return rc


if __name__ == "__main__":
    sys.exit(main())
